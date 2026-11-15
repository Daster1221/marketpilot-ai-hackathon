import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
import post_format
import telegram_bot as bot
import telegram_screen as screen


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = patch.object(app, 'ROOT', Path(self.temp.name))
        self.root.start()
        (app.ROOT / 'data').mkdir()
        bot.init_db()
        self.api = Mock(return_value={'message_id': 100})

    def tearDown(self):
        self.root.stop()
        self.temp.cleanup()

    def test_navigation_edits_one_message_and_removes_reply_keyboard(self):
        screen.show(42, 'Меню', [[bot.btn('Профиль', 'profile')]], False, self.api)
        screen.show(42, 'Профиль', [[bot.btn('Назад', 'home')]], False, self.api)
        sent = [call for call in self.api.call_args_list if call.args[0] == 'sendMessage']
        edits = [call for call in self.api.call_args_list if call.args[0] == 'editMessageText']
        self.assertEqual(len(sent), 2)  # Disposable keyboard cleanup + the single screen.
        self.assertTrue(sent[0].args[1]['reply_markup']['remove_keyboard'])
        self.assertEqual([call.args[1]['message_id'] for call in edits], [100])
        self.assertEqual(edits[-1].args[1]['text'], 'Профиль')

    def test_unchanged_screen_does_not_call_api_again(self):
        screen.show(42, 'Меню', [], False, self.api)
        before = self.api.call_count
        screen.show(42, 'Меню', [], False, self.api)
        self.assertEqual(self.api.call_count, before)

    def test_missing_message_is_recreated_but_network_error_is_not(self):
        screen.show(42, 'Первый', [], False, self.api)
        def missing(method, payload):
            if method == 'editMessageText' and payload['message_id'] == 100:
                raise bot.TelegramAPIError('missing', 'unavailable')
            return {'message_id': 101}
        self.api.side_effect = missing
        screen.show(42, 'Второй', [], False, self.api)
        self.assertEqual(screen.get(42)['message_id'], 101)
        self.api.reset_mock(side_effect=True)
        self.api.side_effect = ValueError('network unavailable')
        with self.assertRaises(ValueError):
            screen.show(42, 'Третий', [], False, self.api)
        self.assertEqual([call.args[0] for call in self.api.call_args_list], ['editMessageText'])

    def test_message_id_survives_restart(self):
        screen.show(42, 'Первый', [], False, self.api)
        bot.init_db()
        screen.show(42, 'Второй', [], False, self.api)
        self.assertEqual(sum(call.args[0] == 'sendMessage' for call in self.api.call_args_list), 2)

    def test_pagination_preserves_long_formatted_content_and_requires_last_page_for_confirmation(self):
        text = '<b>' + 'Я😀&amp;' * 1200 + '</b>'
        screen.show(42, text, [[bot.btn('Подтвердить', 'confirm:1:1:nonce')]], True, self.api)
        first = screen.get(42)
        pages = json.loads(first['pages'])
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(post_format.length(page) <= 3600 for page in pages))
        for page in pages:
            self.assertEqual(post_format.normalize(page), page)
        self.assertEqual(''.join(post_format.plain(page) for page in pages), post_format.plain(text))
        buttons = screen.payload_for(first)['reply_markup']['inline_keyboard']
        self.assertFalse(any(button['callback_data'].startswith('confirm:') for row in buttons for button in row))
        screen.turn_page(42, f'page:{first["nonce"]}:{len(pages) - 1}', self.api)
        buttons = self.api.call_args.args[1]['reply_markup']['inline_keyboard']
        self.assertTrue(any(button['callback_data'].startswith('confirm:') for row in buttons for button in row))
        screen.show(42, 'Другой экран', [], False, self.api)
        with self.assertRaises(ValueError):
            screen.turn_page(42, f'page:{first["nonce"]}:0', self.api)

    def test_cleanup_never_deletes_active_screen(self):
        screen.show(42, 'Меню', [], False, self.api)
        self.api.reset_mock()
        screen.delete(42, 100, self.api)
        self.api.assert_not_called()
        screen.delete(42, 99, self.api)
        self.api.assert_called_once_with('deleteMessage', {'chat_id': 42, 'message_id': 99})

    def test_cleanup_failure_is_nonfatal(self):
        self.api.side_effect = ValueError('too old')
        screen.delete(42, 99, self.api)

    def test_image_loading_uses_premium_without_model_names_or_seconds(self):
        import model_selection
        with patch.object(bot,'tg',self.api),patch.object(model_selection,'model_for',return_value='anthropic/claude-sonnet-5-5'):
            wait=bot.loading(42,'Создаю изображение');wait.threaded=False
            with wait:
                first=screen.get(42)
                text=json.loads(first['pages'])[0]
                self.assertIn('emoji-id="5458724582187885302"',text)
                self.assertNotIn('Claude',text);self.assertNotIn('gpt-image',text);self.assertNotIn('Текст:',text);self.assertNotIn('Изображение:',text)
                self.assertTrue(wait.tick())
                self.assertNotEqual(text,json.loads(screen.get(42)['pages'])[0])
                screen.show(42,'Меню',[],False,self.api)
                self.assertFalse(wait.tick())

    def test_loading_animates_and_stops_after_navigation(self):
        with screen.Loading(42, 'Готовлю черновик', self.api, threaded=False) as wait:
            first = self.api.call_args.args[1]['text']
            self.assertTrue(wait.tick())
            second = self.api.call_args.args[1]['text']
            self.assertNotEqual(first, second)
            self.assertNotIn('%', second)
            self.assertNotRegex(second, r'\d+\s*с\b')
            self.assertTrue(any(call.args[0] == 'sendChatAction' for call in self.api.call_args_list))
            screen.show(42, 'Меню', [], False, self.api)
            count = self.api.call_count
            self.assertFalse(wait.tick())
            self.assertFalse(wait.visible)
            self.assertEqual(self.api.call_count, count)
        self.assertTrue(wait.stop_event.is_set())

    def test_menu_click_bypasses_busy_ai_queue_and_ack_does_not_block(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        bot.set_context(42, {'mode': 'task', 'task': 'Пост'})
        bot.enqueue({'update_id': 1, 'message': {'chat': {'id': 42}}})
        update = {'update_id': 2, 'callback_query': {'id': 'click-2', 'data': 'home', 'from': {'id': 42}, 'message': {'message_id': 80, 'chat': {'id': 42, 'type': 'private'}}}}
        with patch.dict(app.os.environ, {'TELEGRAM_OWNER_ID': '42'}), patch.object(bot, 'is_busy', return_value=True), patch.object(bot, 'tg', self.api), patch.object(bot, '_ACK_POOL') as pool, patch.object(bot, 'consume_one') as consume:
            bot.dispatch_authorized(update)
            pool.submit.assert_called_once_with(bot.acknowledge, 'click-2', None)
            consume.assert_not_called()
        with app.db() as con:
            states = dict(con.execute('SELECT id,status FROM bot_inbox'))
        self.assertEqual(states, {1: 'queued', 2: 'done'})
        self.assertEqual(bot.context(42)['task'], 'Пост')

    def test_mutating_click_is_not_delayed_until_after_generation(self):
        update = {'update_id': 2, 'callback_query': {'id': 'click-2', 'data': 'confirm:1:1:nonce', 'from': {'id': 42}, 'message': {'message_id': 80, 'chat': {'id': 42, 'type': 'private'}}}}
        with patch.object(bot, 'is_busy', return_value=True), patch.object(bot, 'handle') as handle, patch.object(bot, '_ACK_POOL') as pool:
            bot.dispatch_authorized(update)
            handle.assert_not_called()
            self.assertIn('выполняется', pool.submit.call_args.args[2])
        with app.db() as con:
            self.assertEqual(con.execute('SELECT status FROM bot_inbox').fetchone()[0], 'done')

    def test_ai_result_is_saved_without_overwriting_menu(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        def generate(*args):
            bot.fast_navigation(42, 'home')
            return {'posts': [{'topic': 'Тема', 'body': 'Готовый текст', 'image_prompt': ''}]}
        with patch.object(bot, 'tg', self.api), patch.object(app, 'prepare_posts', side_effect=generate):
            bot.create_posts(42, 'Один пост')
        state = screen.get(42)
        self.assertIn('Ваш AI-редактор', json.loads(state['pages'])[0])
        with app.db() as con:
            self.assertEqual(con.execute('SELECT body FROM bot_posts').fetchone()[0], 'Готовый текст')

    def test_text_input_removed_after_processing(self):
        update = {'message': {'message_id': 50, 'from': {'id': 42}, 'chat': {'id': 42, 'type': 'private'}, 'text': '/start'}}
        with patch.dict(app.os.environ, {'TELEGRAM_OWNER_ID': '42'}), patch.object(bot, 'tg', self.api):
            bot.handle(update)
        self.assertIn(('deleteMessage', {'chat_id': 42, 'message_id': 50}), [call.args for call in self.api.call_args_list])

    def test_multiple_generated_posts_remain_accessible_in_one_screen(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        posts = [{'topic': 'Анонс', 'body': 'Первый', 'image_prompt': ''}, {'topic': 'Напоминание', 'body': 'Второй', 'image_prompt': ''}]
        with patch.object(bot, 'tg', self.api), patch.object(app, 'prepare_posts', return_value={'posts': posts}):
            bot.create_posts(42, 'Два поста')
        buttons = self.api.call_args.args[1]['reply_markup']['inline_keyboard']
        data = [button['callback_data'] for row in buttons for button in row]
        self.assertIn('view:1:1', data)
        self.assertIn('view:2:1', data)
        self.assertEqual(sum(call.args[0] == 'sendMessage' for call in self.api.call_args_list), 2)

    def test_realistic_api_refuses_editing_keyboard_removal_messages(self):
        messages = {}
        next_id = 0
        def api(method, payload):
            nonlocal next_id
            if method == 'sendMessage':
                next_id += 1
                messages[next_id] = dict(payload)
                return {'message_id': next_id}
            if method == 'editMessageText':
                old = messages.get(payload['message_id'])
                if not old or old.get('reply_markup', {}).get('remove_keyboard'):
                    raise bot.TelegramAPIError('message cannot be edited', 'unavailable')
                messages[payload['message_id']] = dict(payload)
                return {'message_id': payload['message_id']}
            if method == 'deleteMessage':
                messages.pop(payload['message_id'], None)
                return True
        screen.show(42, 'Меню', [[bot.btn('Профиль', 'profile')]], False, api)
        screen.show(42, 'Профиль', [[bot.btn('Назад', 'home')]], False, api)
        self.assertEqual(len(messages), 1)
        active = screen.get(42)['message_id']
        self.assertEqual(messages[active]['text'], 'Профиль')
        self.assertIn('inline_keyboard', messages[active]['reply_markup'])
        # Simulate the screen persisted by the previous faulty implementation.
        messages[active]['reply_markup'] = {'remove_keyboard': True}
        screen.show(42, 'Новое меню', [[bot.btn('Профиль', 'profile')]], False, api)
        self.assertEqual(len(messages), 1)
        self.assertNotEqual(screen.get(42)['message_id'], active)
        screen.show(42, 'Профиль ещё раз', [], False, api)
        self.assertEqual(len(messages), 1)


if __name__ == '__main__':
    unittest.main()


class ProjectDocumentTests(unittest.TestCase):
    def test_project_document_uses_dedicated_document_upload_field(self):
        with patch.dict(app.os.environ,{'TELEGRAM_BOT_TOKEN':'fixture-not-real'}),patch.object(app,'remote_photo',return_value={'ok':True,'result':{'message_id':1}}) as upload:
            bot.tg('sendDocument',{'chat_id':42,'_document_path':'safe-fixture.txt'})
        self.assertEqual(upload.call_args.kwargs['field'],'document')
        self.assertNotIn('_document_path',upload.call_args.args[1])
