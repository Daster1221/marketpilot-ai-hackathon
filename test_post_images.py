import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
from PIL import Image
from io import BytesIO
import telegram_bot as bot
import miniapp_api
import post_images as images


class PostImageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=patch.object(app,'ROOT',Path(self.temp.name));self.root.start()
        import art_director
        self.director=patch.object(art_director,'plan',return_value={'concept':'Совместная игра','prompt':'A warm shared gaming table with paired objects and natural light.','overlay':'poster','layout':'side_panel','tone':'light','model':art_director.MODEL});self.director.start()
        (app.ROOT/'data').mkdir();bot.init_db()
        self.env=patch.dict(app.os.environ,{'DEEPSEEK_API_KEY':'unit-test-not-real'});self.env.start()
        with app.db() as con:
            self.pid=con.execute('INSERT INTO bot_posts(chat,topic,body) VALUES(42,"Клуб","<b>Клуб коллег</b>")').lastrowid
            con.execute('INSERT INTO bot_post_review(post,warnings) VALUES(?,"[]")',(self.pid,))
        fixture=BytesIO();Image.new('RGB',(64,64),'#C1D0D3').save(fixture,format='PNG');self.raw=fixture.getvalue()
        self.result={'data':[{'b64_json':base64.b64encode(self.raw).decode()}]}
        refs=app.ROOT/'assets'/'visual-references';refs.mkdir(parents=True)
        (refs/'recognition.png').write_bytes(self.raw)

    def tearDown(self):
        self.director.stop();self.env.stop();self.root.stop();self.temp.cleanup()

    def test_generation_attaches_once_and_is_shared_with_authenticated_miniapp(self):
        with patch.object(images,'generate_image',return_value=self.result) as api:
            self.assertTrue(images.attach(42,self.pid,'Стекольная компания'))
            self.assertFalse(images.attach(42,self.pid))
        api.assert_called_once()
        request=api.call_args.args[0]
        self.assertIn('shared gaming table',request)
        self.assertNotIn('Клуб коллег',request)  # FLUX receives a visual idea, not a copy of the post.
        raw,mime=miniapp_api.image(42,self.pid)
        self.assertEqual(mime,'image/png')
        self.assertEqual(Image.open(BytesIO(raw)).size,(1080,1080))
        with self.assertRaises(ValueError):miniapp_api.image(99,self.pid)
        import bot_features
        self.assertIn('_photo_path',images.payload(bot_features.image_for(self.pid)))
        with app.db() as con:
            self.assertEqual(con.execute('SELECT rev FROM bot_posts WHERE id=?',(self.pid,)).fetchone()[0],2)

    def test_concurrent_text_edit_does_not_get_an_outdated_illustration(self):
        def edit_then_return(*args,**kwargs):
            with app.db() as con:con.execute('UPDATE bot_posts SET body="Другой текст",rev=2 WHERE id=?',(self.pid,))
            return self.result
        with patch.object(images,'generate_image',side_effect=edit_then_return):images.attach(42,self.pid)
        import bot_features
        self.assertFalse(bot_features.image_for(self.pid))

    def test_cover_refresh_uses_saved_scene_and_changes_cache_key_without_api(self):
        with patch.object(images,'generate_image',return_value=self.result):images.attach(42,self.pid)
        import bot_features
        old=bot_features.image_for(self.pid)
        with app.db() as con:con.execute('UPDATE bot_posts SET body="<b>Новый заголовок</b>",rev=3 WHERE id=?',(self.pid,))
        with patch.object(images,'generate_image') as api:self.assertTrue(images.refresh_cover(42,self.pid))
        api.assert_not_called()
        self.assertNotEqual(old,bot_features.image_for(self.pid))
        self.assertIn('-r3-cover.png',bot_features.image_for(self.pid))

    def test_explicit_no_image_instruction_costs_nothing(self):
        with patch.object(images,'generate_image') as api:
            self.assertFalse(images.attach(42,self.pid,instruction='Сделай пост без картинки'))
        api.assert_not_called()
        with app.db() as con:
            self.assertIn('NO_VISUAL',con.execute('SELECT decision FROM bot_visual_reviews').fetchone()[0])

    def test_paid_timeout_keeps_text_and_is_not_retried(self):
        with patch.object(images,'generate_image',side_effect=TimeoutError) as api:
            self.assertFalse(images.attach(42,self.pid))
            self.assertFalse(images.attach(42,self.pid))
        api.assert_called_once()
        with app.db() as con:
            self.assertEqual(con.execute('SELECT body FROM bot_posts').fetchone()[0],'<b>Клуб коллег</b>')
            self.assertIn('Текст и прежняя картинка сохранены',con.execute('SELECT warnings FROM bot_post_review').fetchone()[0])

    def test_image_text_image_cycle_preserves_body_memory_and_latest_scene(self):
        import bot_features
        miniapp_api.init_db()
        with patch.object(images,'generate_image',return_value=self.result):images.attach(42,self.pid)
        with app.db() as con:
            con.execute('INSERT INTO mini_edit_memory VALUES(?,?,?)',(self.pid,2,'Сохраняй дружелюбный тон'))
        with patch.object(images,'generate_image',return_value=self.result):images.regenerate(42,self.pid,2,'Сделай светлее','edit-one')
        first=bot_features.image_for(self.pid)
        with app.db() as con:
            self.assertEqual(con.execute('SELECT body FROM bot_posts').fetchone()[0],'<b>Клуб коллег</b>')
            self.assertEqual(con.execute('SELECT rev FROM mini_edit_memory').fetchone()[0],3)
        saved=miniapp_api.save_post(42,self.pid,{'rev':3,'body':'<b>Исправленный текст</b>'})
        self.assertEqual(saved['rev'],4)
        with patch.object(images,'generate_image',return_value=self.result):images.regenerate(42,self.pid,4,'Теперь добавь тёплый свет','edit-two')
        with app.db() as con:
            p=con.execute('SELECT body,rev FROM bot_posts').fetchone()
            self.assertEqual(p['body'],'<b>Исправленный текст</b>');self.assertEqual(p['rev'],5)
            decision=__import__('json').loads(con.execute('SELECT decision FROM bot_visual_reviews').fetchone()[0])
        self.assertNotEqual(first,bot_features.image_for(self.pid))
        self.assertTrue((app.ROOT/'data'/'generated_images'/decision['scene_file']).is_file())
        with patch.object(images,'generate_image') as api:
            with self.assertRaises(ValueError):images.regenerate(42,self.pid,4,'Повтор старого запроса','edit-two')
        api.assert_not_called()

    def test_failed_image_edit_keeps_previous_photo_and_text(self):
        import bot_features
        with patch.object(images,'generate_image',return_value=self.result):images.attach(42,self.pid)
        old=bot_features.image_for(self.pid)
        with patch.object(images,'generate_image',side_effect=TimeoutError):
            with self.assertRaises(ValueError):images.regenerate(42,self.pid,2,'Измени фон','failed-edit')
        self.assertEqual(bot_features.image_for(self.pid),old)
        with app.db() as con:self.assertEqual(con.execute('SELECT body FROM bot_posts').fetchone()[0],'<b>Клуб коллег</b>')

    def test_full_poster_text_edit_keeps_artwork_and_requires_review_without_charges(self):
        import bot_features
        __import__('art_director').plan.return_value.update(render_mode='generated_poster',texts=['КОМАНДА'])
        with patch.object(images,'generate_image',return_value=self.result):images.attach(42,self.pid)
        old=bot_features.image_for(self.pid)
        with app.db() as con:con.execute('UPDATE bot_posts SET body="<b>Изменённый текст</b>",rev=3 WHERE id=?',(self.pid,))
        with patch.object(images,'generate_image') as api:images.refresh_cover(42,self.pid)
        api.assert_not_called()
        self.assertEqual(bot_features.image_for(self.pid),old)
        with app.db() as con:
            decision=__import__('json').loads(con.execute('SELECT decision FROM bot_visual_reviews').fetchone()[0])
        self.assertTrue(decision['image_text_needs_review'])

    def test_user_photo_is_never_overwritten_and_foreign_actor_cannot_generate(self):
        with app.db() as con:con.execute('INSERT INTO bot_post_images VALUES(?,"user-photo-id")',(self.pid,))
        with patch.object(images,'generate_image') as api:
            self.assertFalse(images.attach(42,self.pid));self.assertFalse(images.attach(99,self.pid))
        api.assert_not_called()

    def test_unsafe_download_and_private_file_access_are_rejected(self):
        self.assertIsNone(images.local_path(str(app.ROOT/'.env')))
        for url in ('http://example.com/a.png','file:///etc/passwd','https://localhost/a.png'):
            with self.assertRaises(ValueError):images.decode_image({'data':[{'url':url}]})
        with self.assertRaises(ValueError):images.decode_image({'data':[{'b64_json':base64.b64encode(b'not-an-image').decode()}]})

    def test_reference_image_is_sent_as_binary_not_just_described(self):
        folder=app.ROOT/'assets'/'visual-references';folder.mkdir(parents=True,exist_ok=True)
        (folder/'recognition.png').write_bytes(self.raw)
        import json,urllib.request
        decision={'content_type':'factory_hiring'}
        with patch.object(urllib.request,'urlopen',return_value=BytesIO(json.dumps(self.result).encode())) as request:
            images.generate_image('Complete poster',decision)
        sent=request.call_args.args[0]
        self.assertTrue(sent.full_url.endswith('/images/edits'))
        self.assertIn(b'name="image"',sent.data);self.assertIn(self.raw,sent.data)
        self.assertIn(images.MODEL.encode(),sent.data)
        self.assertNotIn(b'name="response_format"',sent.data)
        self.assertEqual(decision['style_reference'],'recognition.png')
