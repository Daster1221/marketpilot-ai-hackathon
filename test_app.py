import json
import io
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import app


class WorkflowTests(unittest.TestCase):
    def test_planning_validates_ideas_and_keeps_editorial_direction_separate(self):
        with patch.object(app, 'ai_json', return_value={'facts': [{'label': 'Событие', 'value': 'Экскурсия'}], 'question': '', 'ideas': []}):
            with self.assertRaises(ValueError):
                app.plan_publication('Компания', 'Экскурсия')
        with patch.object(app, 'ai_json', return_value={'facts': [{'label': 'Событие', 'value': 'Экскурсия'}], 'question': 'Когда?', 'ideas': []}):
            result = app.plan_publication('Компания', 'Экскурсия')
        self.assertEqual(result['question'], 'Когда?')
        with patch.object(app, 'ai_json', return_value={'post': {'topic': 'Новость', 'body': '<b>Экскурсия</b>'}}) as ai:
            app.prepare_posts('Компания', 'Экскурсия', '20 ноября', angle='Акцент на технологиях')
        payload = ai.call_args.args[1]
        self.assertEqual(payload['task'], 'Экскурсия')
        self.assertEqual(payload['clarification'], 'Дата события: 20 ноября')
        self.assertEqual(payload['current_event_date'], '20 ноября')
        self.assertEqual(payload['editorial_direction']['angle'], 'Акцент на технологиях')

    def test_edit_request_has_bounded_memory_and_no_history(self):
        with patch.object(app, 'ai_json', return_value={'body': '<b>Новый текст</b>', 'memory': 'Коротко; на вы'}) as ai:
            result = app.rewrite_post('Без скидок', 'Текущий текст', 'Сократи', memory='x' * 2000)
        payload = ai.call_args.args[1]
        self.assertEqual(set(payload), {'brand_rules', 'body', 'instruction', 'memory', 'brand_name_mode', 'publication_date'})
        self.assertEqual(len(payload['memory']), app.EDIT_MEMORY_LIMIT)
        self.assertEqual(result['memory'], 'Коротко; на вы')

    def test_oversized_edit_summary_does_not_get_saved(self):
        with patch.object(app, 'ai_json', return_value={'body': 'Новый текст', 'memory': 'x' * (app.EDIT_MEMORY_LIMIT + 1)}):
            with self.assertRaises(ValueError):
                app.rewrite_post('', 'Текст', 'Правка')

    def test_task_count_and_limits(self):
        for text, count in [('Нужно два поста о турнире', 2), ('Напиши 1 пост о кофе', 1), ('Сделай 5 постов', 5)]:
            self.assertEqual(app.requested_count(text), count)
        with self.assertRaises(ValueError):
            app.requested_count('Нужно 20 постов')

    def test_task_response_count_is_validated(self):
        with patch.object(app, 'ai_json', return_value={'posts': [{'topic': 'Тема', 'body': 'Текст'}]}):
            with self.assertRaises(ValueError):
                app.prepare_posts('Профиль', 'Два поста')

    def test_task_can_request_clarification(self):
        with patch.object(app, 'ai_json', return_value={'question': 'Когда турнир?'}):
            result = app.prepare_posts('Профиль', 'Два поста о турнире')
            self.assertEqual(result['question'], 'Когда турнир?')
            self.assertEqual(result['status'], 'needs_clarification')
            self.assertEqual(result['posts'], [])

    def test_proxyapi_endpoint_and_key_are_used(self):
        with patch.dict(app.os.environ, {'DEEPSEEK_BASE_URL': 'https://api.proxyapi.ru/v1/'}), patch.object(app, 'remote_json', return_value={'ok': True}) as request:
            app.deepseek_request({'model': 'deepseek/deepseek-v4.1-flash'}, 'test-proxy-key')
            self.assertEqual(request.call_args.args[0], 'https://api.proxyapi.ru/v1/chat/completions')
            self.assertEqual(request.call_args.args[2], 'test-proxy-key')

    def test_local_env_overrides_old_values_and_removes_quotes(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(app.os.environ, {'DEEPSEEK_API_KEY': 'old'}):
            path = Path(folder) / '.env'
            path.write_text('\ufeffDEEPSEEK_API_KEY="new-key"\n# comment\n', encoding='utf-8')
            app.load_env(path)
            self.assertEqual(app.os.environ['DEEPSEEK_API_KEY'], 'new-key')

    def test_malformed_ai_response_is_explained(self):
        with patch.dict(app.os.environ, {'DEEPSEEK_API_KEY': 'test'}):
            for result in [{}, {'choices': [{'message': {'content': 'invalid json'}}]}, {'choices': [{'message': {'content': '{"posts":[null,null,null]}'}}]}]:
                with patch.object(app, 'deepseek_request', return_value=result):
                    with self.assertRaises(ValueError):
                        app.generate('Бриф для теста')

    def test_deepseek_errors_explain_action_without_exposing_key(self):
        for status, expected in [(401, 'API-ключ'), (402, 'средств'), (429, 'лимит')]:
            error = urllib.error.HTTPError('https://api.deepseek.com', status, 'secret-provider-detail', {}, None)
            with patch.object(app, 'remote_json', side_effect=error):
                with self.assertRaises(ValueError) as raised:
                    app.deepseek_request({}, 'secret-api-key')
            self.assertIn(expected, str(raised.exception))
            self.assertNotIn('secret', str(raised.exception))

    def test_approval_and_duplicate_guard(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, 'ROOT', Path(folder)):
            (app.ROOT / 'data').mkdir()
            with app.db() as con:
                con.execute('CREATE TABLE posts(id INTEGER PRIMARY KEY, topic TEXT, body TEXT, image_prompt TEXT, status TEXT, source TEXT, message_id TEXT)')
                con.execute('INSERT INTO posts VALUES(1,"Тема","Текст","Описание","draft","demo",NULL)')
            def post(route, **data):
                raw = json.dumps({'id': 1, **data}).encode()
                handler = object.__new__(app.Handler)
                handler.path = '/api/' + route
                handler.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(raw))}
                handler.rfile = io.BytesIO(raw)
                result = []
                handler.reply = lambda status, value: result.append(status)
                handler.do_POST()
                return result[0]

            try:
                with patch.dict(app.os.environ, {'TELEGRAM_BOT_TOKEN': 'test', 'TELEGRAM_CHANNEL_ID': 'test'}), patch.object(app, 'remote_json', return_value={'ok': True, 'result': {'message_id': 10}}) as remote:
                    self.assertEqual(post('publish'), 400)
                    remote.assert_not_called()
                    self.assertEqual(post('approve'), 200)
                    self.assertEqual(post('edit', body='Новый текст'), 200)
                    self.assertEqual(post('publish'), 400)
                    self.assertEqual(post('approve'), 200)
                    self.assertEqual(post('publish'), 200)
                    self.assertEqual(post('publish'), 400)
                    remote.assert_called_once()
                    self.assertEqual(remote.call_args.args[1]['text'], 'Новый текст')
            finally:
                pass


if __name__ == '__main__':
    unittest.main()
