import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import app,telegram_bot as bot,vk_publish as vk

class VKTextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=patch.object(app,'ROOT',Path(self.temp.name));self.root.start()
        (app.ROOT/'data').mkdir();self.env=patch.dict(app.os.environ,{'TELEGRAM_OWNER_ID':'42,99','VK_GROUP_ID':'12345','VK_ACCESS_TOKEN':'fixture-not-real'});self.env.start();bot.init_db()
        with app.db() as c:
            self.pid=c.execute('INSERT INTO bot_posts(chat,topic,body) VALUES(42,"Матч",?)',('<b>Матч!</b>\n<blockquote>20 ноября</blockquote>\n<tg-spoiler>Деталь</tg-spoiler>',)).lastrowid
            c.execute('INSERT INTO bot_post_images VALUES(?,"telegram-photo-id")',(self.pid,))
    def tearDown(self):self.env.stop();self.root.stop();self.temp.cleanup()
    def test_preview_does_not_publish_then_only_text_is_sent_once(self):
        with patch.object(vk,'call',return_value={'post_id':77}) as api:
            p=vk.prepare(42,self.pid,1);api.assert_not_called()
            r=vk.publish(42,self.pid,1,p['nonce'])
            with self.assertRaises(ValueError):vk.publish(42,self.pid,1,p['nonce'])
        api.assert_called_once();params=api.call_args.args[0]
        self.assertNotIn('attachments',params);self.assertNotIn('<b>',params['message']);self.assertIn('Деталь',params['message'])
        self.assertEqual(params['owner_id'],'-12345');self.assertTrue(r['url'].endswith('_77'))
        with app.db() as c:self.assertEqual(c.execute('SELECT status FROM bot_posts').fetchone()[0],'draft')
    def test_foreign_user_changed_revision_and_wrong_nonce_cannot_publish(self):
        p=vk.prepare(42,self.pid,1)
        with patch.object(vk,'call') as api:
            with self.assertRaises(ValueError):vk.publish(99,self.pid,1,p['nonce'])
            with self.assertRaises(ValueError):vk.publish(42,self.pid,1,'wrong')
            with app.db() as c:c.execute('UPDATE bot_posts SET rev=2,body="Правка"')
            with self.assertRaises(ValueError):vk.publish(42,self.pid,1,p['nonce'])
        api.assert_not_called()
    def test_timeout_is_durable_and_never_retried_automatically(self):
        p=vk.prepare(42,self.pid,1)
        with patch.object(vk,'call',side_effect=TimeoutError) as api:
            with self.assertRaises(ValueError):vk.publish(42,self.pid,1,p['nonce'])
            bot.init_db()
            with self.assertRaises(ValueError):vk.prepare(42,self.pid,1)
        api.assert_called_once();self.assertEqual(vk.status(42,self.pid)['state'],'unknown')
    def test_vk_rejection_allows_only_a_new_explicit_confirmation(self):
        p=vk.prepare(42,self.pid,1)
        with patch.object(vk,'call',side_effect=vk.VKError('Отказ')):
            with self.assertRaises(vk.VKError):vk.publish(42,self.pid,1,p['nonce'])
        self.assertEqual(vk.status(42,self.pid)['state'],'failed')
        again=vk.prepare(42,self.pid,1);self.assertNotEqual(p['nonce'],again['nonce'])
    def test_changed_destination_invalidates_confirmation(self):
        p=vk.prepare(42,self.pid,1)
        with patch.dict(app.os.environ,{'VK_GROUP_ID':'99999'}),patch.object(vk,'call') as api:
            with self.assertRaises(ValueError):vk.publish(42,self.pid,1,p['nonce'])
        api.assert_not_called()
