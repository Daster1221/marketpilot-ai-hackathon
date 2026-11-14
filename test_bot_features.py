import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import telegram_bot as b
import bot_features as f
import telegram_screen as screen


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=patch.object(app,'ROOT',Path(self.temp.name));self.root.start()
        (app.ROOT/'data').mkdir()
        b.init_db()
        self.api=patch.object(b,'tg',return_value={'message_id':200});self.mock=self.api.start()
        self.env=patch.dict(app.os.environ,{'TELEGRAM_OWNER_ID':'42','TELEGRAM_CHANNEL_ID':'@test'});self.env.start()
        b.save({'chat':42,'step':5,'answers':'{}','editing':None})

    def tearDown(self):
        self.env.stop();self.api.stop();self.root.stop();self.temp.cleanup()

    def post(self,chat=42):
        with app.db() as c:
            return c.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(?,"Тема","<b>Текст</b>","deepseek")',(chat,)).lastrowid

    def test_fast_mode_skips_planning_and_uses_one_draft_call(self):
        f.callback(42,'feat_toggle:fast')
        with patch.object(app,'prepare_posts',return_value={'posts':[{'topic':'Тема','body':'Текст','image_prompt':''}]}) as draft, patch.object(app,'plan_publication') as plan:
            b.message(42,'Сделай пост')
        draft.assert_called_once();plan.assert_not_called()

    def test_content_plan_is_saved_and_selecting_topic_preserves_idea_scope(self):
        f.start_plan(42)
        with patch.object(app,'ai_json',return_value={'items':[{'topic':'Люди производства','angle':'Собрать интервью'}]}):
            b.message(42,'План на неделю')
        with app.db() as c:
            row=c.execute('SELECT * FROM bot_content_plans WHERE chat=42').fetchone()
        with patch.object(b,'plan_event') as plan:
            f.callback(42,'feat_plan_post:'+row['nonce']+':0')
        self.assertIn('не подтверждённое событие',plan.call_args.args[1])
        with self.assertRaises(ValueError):
            f.callback(99,'feat_plan_post:'+row['nonce']+':0')

    def test_photo_changes_revision_and_is_published_only_after_send(self):
        post=self.post();b.show_post(42,post)
        f.receive_photo(42,[{'file_id':'own-photo'}])
        self.assertEqual(f.image_for(post),'own-photo')
        self.assertEqual(screen.get(42)['media'],'own-photo')
        with self.assertRaises(ValueError):
            b.callback(42,f'send:{post}:1')
        b.callback(42,f'send:{post}:2')
        self.assertFalse(any(x.args[0]=='sendPhoto' and x.args[1]['chat_id']=='@test' for x in self.mock.call_args_list))
        with app.db() as c:
            approval=c.execute('SELECT * FROM bot_confirmations WHERE post=?',(post,)).fetchone()
        b.callback(42,f'confirm:{post}:2:'+approval['nonce'])
        self.assertTrue(any(x.args[0]=='sendPhoto' and x.args[1].get('photo')=='own-photo' and x.args[1]['chat_id']=='@test' for x in self.mock.call_args_list))

    def test_deletion_is_confirmed_and_ownership_scoped(self):
        post=self.post();other=self.post(99)
        with app.db() as c:
            c.execute('INSERT INTO bot_versions(post,rev,body) VALUES(?,1,"Текст")',(post,))
        with self.assertRaises(ValueError):
            f.callback(99,f'feat_delete:{post}:1')
        f.callback(42,f'feat_delete:{post}:1')
        with app.db() as c:
            self.assertIsNotNone(c.execute('SELECT id FROM bot_posts WHERE id=?',(post,)).fetchone())
            nonce=c.execute('SELECT nonce FROM bot_feature_confirmations WHERE chat=42').fetchone()[0]
        f.callback(42,'feat_delete_confirm:'+nonce)
        with app.db() as c:
            self.assertIsNone(c.execute('SELECT id FROM bot_posts WHERE id=?',(post,)).fetchone())
            self.assertIsNone(c.execute('SELECT post FROM bot_versions WHERE post=?',(post,)).fetchone())
            self.assertIsNotNone(c.execute('SELECT id FROM bot_posts WHERE id=?',(other,)).fetchone())

    def test_auto_voice_and_optional_send_confirmation(self):
        f.callback(42,'feat_toggle:auto_voice')
        with patch.object(b,'recognize_voice',return_value='Моя задача'),patch.object(b,'message') as message:
            b.voice_message(42,{'duration':1})
        message.assert_called_once_with(42,'Моя задача')
        post=self.post()
        f.callback(42,'feat_toggle:confirm_publish')
        self.assertFalse(any(x.args[1].get('chat_id')=='@test' for x in self.mock.call_args_list if x.args[0]=='sendMessage'))
        b.callback(42,f'send:{post}:1')
        self.assertTrue(any(x.args[1].get('chat_id')=='@test' for x in self.mock.call_args_list if x.args[0]=='sendMessage'))

    def test_inline_photo_paginates_caption_and_edits_without_new_message(self):
        screen.show(42,'<b>Заголовок</b>\n\n'+'Факты '*400,[],True,b.tg,media='photo-file-id')
        state=screen.get(42)
        self.assertGreater(len(json.loads(state['pages'])),1)
        sent=[x for x in self.mock.call_args_list if x.args[0]=='sendPhoto']
        self.assertLessEqual(len(sent[-1].args[1]['caption']),1024)
        self.mock.reset_mock()
        screen.turn_page(42,'page:'+state['nonce']+':1',b.tg)
        self.assertEqual(self.mock.call_args.args[0],'editMessageCaption')


if __name__=='__main__':
    unittest.main()
