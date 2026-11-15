import io
import unittest
from unittest.mock import Mock, patch
import telegram_bot as bot
import miniapp_server


class MiniAppTests(unittest.TestCase):
    def test_unstarted_user_does_not_block_existing_owner_menu(self):
        def telegram(method,payload):
            if payload.get('chat_id')==1376150940:
                raise bot.TelegramAPIError('User not found','chat_not_found')
            return True
        with patch.dict(bot.os.environ,{'MINI_APP_URL':'https://current.example/'}),patch.object(bot,'allowed_user_ids',return_value=['1376150940','8460400176']),patch.object(bot,'tg',side_effect=telegram) as api:
            self.assertTrue(bot.configure_miniapp())
        self.assertEqual(api.call_args.args[1]['chat_id'],8460400176)

    def test_telegram_user_not_found_is_recognized_without_disclosing_token(self):
        import urllib.error
        error=urllib.error.HTTPError('https://api.telegram.org/hidden',400,'Bad Request',{},io.BytesIO(b'{"description":"Bad Request: user not found"}'))
        with patch.dict(bot.os.environ,{'TELEGRAM_BOT_TOKEN':'fixture-not-a-real-token'}),patch.object(bot.app,'remote_json',side_effect=error):
            with self.assertRaises(bot.TelegramAPIError) as result:bot.tg('setChatMenuButton',{})
        self.assertEqual(result.exception.reason,'chat_not_found')

    def test_audio_upload_requires_auth_and_same_origin_and_enforces_size(self):
        import miniapp_api as api
        handler=miniapp_server.Handler.__new__(miniapp_server.Handler)
        handler.path='/transcribe';handler.rfile=io.BytesIO(b'voice')
        handler.headers={'Host':'live.example','Origin':'https://live.example','Content-Type':'audio/webm','Content-Length':'5','X-Request-ID':'voice-request'}
        handler.api_response=Mock()
        with patch.object(api,'authenticate',return_value=42),patch.object(api,'enqueue',return_value={'job_id':'123'}) as enqueue:
            handler.do_POST()
            self.assertEqual(enqueue.call_args.args[1]['audio'],b'voice')
            self.assertEqual(handler.api_response.call_args.args[0],200)
            handler.headers['Content-Length']=str(5*1024*1024+1)
            handler.do_POST();self.assertEqual(handler.api_response.call_args.args[0],400)
            handler.headers['Origin']='https://foreign.example'
            handler.do_POST();self.assertEqual(handler.api_response.call_args.args[0],403)
            self.assertEqual(enqueue.call_count,1)
        with patch.object(api,'authenticate',side_effect=PermissionError('Нет доступа')),patch.object(api,'enqueue') as enqueue:
            handler.do_POST();self.assertEqual(handler.api_response.call_args.args[0],403);enqueue.assert_not_called()

    def test_menu_only_accepts_https_without_credentials(self):
        for url in ('', 'http://localhost:8765', 'https://user:pass@example.com'):
            with patch.dict(bot.os.environ, {'MINI_APP_URL': url}), patch.object(bot, 'tg') as api:
                self.assertFalse(bot.configure_miniapp())
                api.assert_not_called()
        with patch.dict(bot.os.environ, {'MINI_APP_URL': 'https://example.com/'}), patch.object(bot, 'tg') as api:
            self.assertTrue(bot.configure_miniapp())
            self.assertEqual(api.call_args.args[0], 'setChatMenuButton')
            self.assertEqual(api.call_args.args[1]['menu_button']['type'], 'web_app')

    def test_placeholder_never_serves_project_files(self):
        for path in ('/.env', '/data/marketpilot.db', '/../app.py', '/assets/../../.env', '/%2e%2e/app.py'):
            handler = miniapp_server.Handler.__new__(miniapp_server.Handler)
            handler.path=path
            handler.send_error=Mock()
            handler.do_GET()
            handler.send_error.assert_called_once_with(404)
        handler=miniapp_server.Handler.__new__(miniapp_server.Handler)
        handler.path='/data';handler.headers={};handler.api_response=Mock()
        handler.do_GET()
        self.assertEqual(handler.api_response.call_args.args[0],403)
        handler=miniapp_server.Handler.__new__(miniapp_server.Handler)
        handler.path='/?tgWebAppVersion=10'
        handler.send_response=Mock();handler.send_header=Mock();handler.end_headers=Mock();handler.wfile=io.BytesIO()
        handler.do_GET()
        self.assertIn('Салаватстекло',handler.wfile.getvalue().decode())
        self.assertIn('./assets/app.js',handler.wfile.getvalue().decode())
        for path in ('/assets/app.js?v=8', '/assets/style.css?v=8', '/assets/salstek-logo.png'):
            handler=miniapp_server.Handler.__new__(miniapp_server.Handler)
            handler.path=path
            handler.send_response=Mock();handler.send_header=Mock();handler.end_headers=Mock();handler.wfile=io.BytesIO()
            handler.do_GET()
            handler.send_response.assert_called_once_with(200)
            self.assertTrue(handler.wfile.getvalue())


class DocumentUploadTests(unittest.TestCase):
    def test_document_upload_is_signed_same_origin_bounded_and_queued(self):
        import miniapp_api as api
        handler=miniapp_server.Handler.__new__(miniapp_server.Handler)
        handler.path='/documents';handler.rfile=io.BytesIO(b'facts')
        handler.headers={'Host':'live.example','Origin':'https://live.example','Content-Type':'application/octet-stream','Content-Length':'5','X-Filename':'company.txt','X-Request-ID':'document-test'}
        handler.api_response=Mock()
        with patch.object(api,'authenticate',return_value=42),patch.object(api,'enqueue',return_value={'job_id':'123'}) as enqueue:
            handler.do_POST();self.assertEqual(enqueue.call_args.args[1]['document'],b'facts')
            handler.headers['Origin']='https://foreign.example';handler.do_POST()
            self.assertEqual(handler.api_response.call_args.args[0],403);self.assertEqual(enqueue.call_count,1)
