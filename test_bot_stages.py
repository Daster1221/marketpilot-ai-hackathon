import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
import bot_stages
import telegram_bot as bot
import telegram_screen


class StageTests(unittest.TestCase):
    def test_loading_hides_banner_and_never_sends_new_photo(self):
        with patch.object(bot, 'tg', self.api):
            bot.say(42, 'Пост', stage='draft')
            self.api.reset_mock()
            wait = bot.loading(42, 'Распознаю голос')
            wait.threaded = False
            with wait:
                wait.tick()
        methods = [call.args[0] for call in self.api.call_args_list]
        self.assertIn('deleteMessage', methods)
        self.assertNotIn('sendPhoto', methods)
        self.assertNotIn('editMessageMedia', methods)
        with app.db() as con:
            self.assertIsNone(con.execute('SELECT * FROM bot_stage_screens WHERE chat=42').fetchone())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = patch.object(app, 'ROOT', Path(self.temp.name))
        self.root.start()
        (app.ROOT / 'data').mkdir()
        (app.ROOT / 'assets' / 'stages').mkdir(parents=True)
        for stage in bot_stages.STAGES:
            (app.ROOT / 'assets' / 'stages' / (stage + '.png')).write_bytes(b'example-png')
        bot.init_db()
        self.api = Mock(return_value={'message_id': 200, 'photo': [{'file_id': 'cached-photo'}]})

    def tearDown(self):
        self.root.stop()
        self.temp.cleanup()

    def test_header_precedes_text_and_is_reused_without_reupload(self):
        telegram_screen.show(42, 'Old text', [], False, self.api)
        self.api.reset_mock()
        bot_stages.show(42, 'event', self.api)
        self.assertEqual(self.api.call_args_list[0].args[0], 'sendPhoto')
        self.assertIsNone(telegram_screen.get(42)['message_id'])
        telegram_screen.show(42, 'New task', [], False, self.api)
        count = self.api.call_count
        bot_stages.show(42, 'event', self.api)
        self.assertEqual(self.api.call_count, count)
        bot_stages.show(42, 'facts', self.api)
        self.assertEqual(self.api.call_args.args[0], 'editMessageMedia')
        self.assertIn('_photo_path', self.api.call_args.args[1])
        bot_stages.show(42, 'event', self.api)
        self.assertNotIn('_photo_path', self.api.call_args.args[1])
        self.assertEqual(self.api.call_args.args[1]['media']['media'], 'cached-photo')
        bot_stages.hide(42, self.api)
        self.assertEqual(telegram_screen.get(42)['message_id'], 200)

    def test_media_cache_is_scoped_to_bot_and_header_to_chat(self):
        with patch.dict(app.os.environ, {'TELEGRAM_BOT_TOKEN': '100:private'}):
            bot_stages.show(42, 'facts', self.api)
            bot_stages.show(99, 'facts', self.api)
            self.assertEqual(self.api.call_args.args[1]['photo'], 'cached-photo')
        with patch.dict(app.os.environ, {'TELEGRAM_BOT_TOKEN': '101:private'}):
            bot_stages.show(777, 'facts', self.api)
            self.assertIn('_photo_path', self.api.call_args.args[1])

    def test_multipart_has_real_binary_and_json_media(self):
        response = Mock()
        response.read.return_value = b'{"ok":true,"result":{}}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        path = app.ROOT / 'assets' / 'stages' / 'facts.png'
        with patch.object(app.urllib.request, 'urlopen', return_value=response) as opening:
            app.remote_photo('https://example.test/upload', {'chat_id': 42, 'media': {'type': 'photo', 'media': 'attach://photo'}}, path)
        request = opening.call_args.args[0]
        self.assertIn(b'name="photo"; filename="stage.png"', request.data)
        self.assertIn(b'example-png', request.data)
        self.assertIn(b'"media": "attach://photo"', request.data)
        self.assertIn('multipart/form-data', request.get_header('Content-type'))


if __name__ == '__main__':
    unittest.main()
