import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
import app,telegram_bot as bot,scheduling as s,miniapp_api as api


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=patch.object(app,'ROOT',Path(self.temp.name));self.root.start()
        (app.ROOT/'data').mkdir()
        self.env=patch.dict(app.os.environ,{'TELEGRAM_OWNER_ID':'42','TELEGRAM_CHANNEL_ID':'-100123'});self.env.start()
        bot.init_db();api.init_db();bot.session(42)
        with app.db() as con:self.pid=con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема","<b>Текст</b>","test")').lastrowid
        self.due=datetime.now(s.TZ)+timedelta(minutes=5)
    def tearDown(self):
        self.env.stop();self.root.stop();self.temp.cleanup()
    def row(self):
        with app.db() as con:return dict(con.execute('SELECT * FROM bot_posts WHERE id=?',(self.pid,)).fetchone())
    def test_only_explicitly_approved_post_sends_once_when_due(self):
        s.schedule(42,self.pid,1,self.due.isoformat())
        self.assertEqual(api.serialize(self.row())['status'],'QUEUED')
        with patch.object(bot,'tg',return_value={'message_id':77}) as send:
            self.assertFalse(s.tick(self.due-timedelta(seconds=1)))
            self.assertTrue(s.tick(self.due+timedelta(seconds=1)))
            self.assertFalse(s.tick(self.due+timedelta(minutes=2)))
        send.assert_called_once();self.assertEqual(send.call_args.args[1]['chat_id'],'-100123')
        self.assertEqual(self.row()['status'],'published')
    def test_ai_calendar_date_without_approval_does_not_publish(self):
        with app.db() as con:con.execute('INSERT INTO bot_post_schedule VALUES(?,?,?)',(self.pid,42,self.due.isoformat()))
        with patch.object(bot,'tg') as send:self.assertFalse(s.tick(self.due+timedelta(hours=1)))
        send.assert_not_called()

    def test_channel_uses_standard_fallback_for_private_premium_preview(self):
        with app.db() as con:
            con.execute('UPDATE bot_posts SET body=? WHERE id=?',('<b><tg-emoji emoji-id="5368324170671202286">👍</tg-emoji> Новость</b>',self.pid))
        s.schedule(42,self.pid,1,self.due.isoformat())
        with patch.object(bot,'tg',return_value={'message_id':77}) as send:s.tick(self.due+timedelta(seconds=1))
        self.assertNotIn('tg-emoji',send.call_args.args[1]['text'])
        self.assertNotIn('👍',send.call_args.args[1]['text'])
    def test_revision_change_cancels_authorized_delivery(self):
        s.schedule(42,self.pid,1,self.due.isoformat())
        with app.db() as con:con.execute('UPDATE bot_posts SET rev=2,body="Правки",status="draft" WHERE id=?',(self.pid,))
        with patch.object(bot,'tg') as send:s.tick(self.due+timedelta(seconds=1))
        send.assert_not_called()
    def test_uncertain_delivery_never_retries(self):
        s.schedule(42,self.pid,1,self.due.isoformat())
        with patch.object(bot,'tg',side_effect=TimeoutError) as send:
            s.tick(self.due+timedelta(seconds=1));s.tick(self.due+timedelta(minutes=1))
        send.assert_called_once();self.assertEqual(self.row()['status'],'delivery_unknown')
    def test_cancel_and_other_user_cannot_publish(self):
        with self.assertRaises(ValueError):s.schedule(99,self.pid,1,self.due.isoformat())
        s.schedule(42,self.pid,1,self.due.isoformat());s.cancel(42,self.pid,1)
        with patch.object(bot,'tg') as send:s.tick(self.due+timedelta(seconds=1))
        send.assert_not_called()
    def test_past_time_rejected_and_ufa_timezone_used(self):
        self.assertEqual(s.parse_due('15.11.2026 18:30').utcoffset(),timedelta(hours=5))
        with self.assertRaises(ValueError):s.schedule(42,self.pid,1,(datetime.now(s.TZ)-timedelta(minutes=1)).isoformat())
