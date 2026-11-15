import json
import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import app
import telegram_bot as bot


class TelegramTests(unittest.TestCase):
    def test_post_list_pages_are_complete_scoped_and_remembered(self):
        with app.db() as con:
            for i in range(14):
                con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,?,"Текст","demo")',(f'Пост {i}',))
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(99,"Чужой пост","Текст","demo")')
        seen=set()
        with patch.object(bot,'say') as show:
            for page in range(3):
                bot.callback(42,f'posts_page:{page}')
                rows=show.call_args.kwargs['inline']
                ids=[b['callback_data'].split(':')[1] for row in rows for b in row if b['callback_data'].startswith('view:')]
                self.assertLessEqual(len(ids),6)
                self.assertFalse(seen.intersection(ids))
                seen.update(ids)
            bot.list_posts(42)
            self.assertIn('3/3',show.call_args.args[1])
        self.assertEqual(len(seen),14)

    def test_create_button_is_green_and_menu_has_no_house(self):
        self.assertEqual(bot.btn('✨ Создать пост','new'),{'text':'Создать пост','callback_data':'new','style':'success'})
        self.assertEqual(bot.btn('⌂ В меню','home')['text'],'В меню')

    def test_followup_to_open_draft_edits_that_post_instead_of_replanning(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Матч","<b>Матч 15 декабря, 15:00</b>","deepseek")')
        bot.show_post(42, 1)
        with patch.object(app, 'rewrite_post', return_value={'body': '<b>Матч 15 декабря, 15:00</b>\nПризы: мерч.', 'memory': 'Призы: мерч'}) as rewrite, patch.object(app, 'plan_publication') as planning:
            bot.message(42, 'Добавь мерч и сделай подачу ярче')
        self.assertIn('15 декабря, 15:00', rewrite.call_args.args[1])
        planning.assert_not_called()
        self.assertEqual(bot.session(42)['editing'], 1)
        bot.callback(42, 'stop_edit')
        bot.callback(42, 'new')
        self.assertIsNone(bot.focused_post(42))
        self.assertEqual(bot.context(42)['mode'], 'new_task')

    def test_failed_plan_keeps_facts_and_all_corrections_for_retry(self):
        original = {'mode': 'plan_correct', 'task': 'Матч', 'clarification': '15 декабря', 'facts': [{'label': 'Событие', 'value': 'Матч'}], 'ideas': [], 'plan_nonce': 'old'}
        bot.set_context(42, original)
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        with patch.object(app, 'plan_publication', side_effect=ValueError('Временно недоступно')):
            with self.assertRaises(ValueError):
                bot.message(42, 'В Уфе')
        pending = bot.context(42)
        self.assertEqual(pending['mode'], 'plan_retry')
        self.assertEqual(pending['facts'], original['facts'])
        self.assertEqual(pending['task'], 'Матч')
        self.assertEqual(pending['clarification'], '15 декабря\nВ Уфе')
        with patch.object(bot, 'plan_event') as retry:
            bot.callback(42, 'retry')
        retry.assert_called_once_with(42, 'Матч', '15 декабря\nВ Уфе')

    def test_failed_edit_keeps_instruction_and_retries_current_draft(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Матч","Текущий пост с фактами","deepseek")')
        bot.show_post(42, 1)
        with patch.object(app, 'rewrite_post', side_effect=ValueError('Временно недоступно')):
            with self.assertRaises(ValueError):
                bot.message(42, 'Добавь мерч')
        self.assertEqual(bot.context(42)['retry_instruction'], 'Добавь мерч')
        with patch.object(app, 'rewrite_post', return_value={'body': 'Текущий пост с фактами. Призы: мерч.', 'memory': 'Добавлен мерч'}) as rewrite:
            bot.callback(42, 'retry')
        self.assertEqual(rewrite.call_args.args[1:3], ('Текущий пост с фактами', 'Добавь мерч'))
        self.assertNotIn('retry_instruction', bot.context(42))

    def test_event_facts_ideas_and_chosen_draft_without_automatic_publication(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        plan = {'facts': [{'label': 'Событие', 'value': 'Экскурсия'}], 'question': '', 'ideas': [
            {'title': 'Технологии', 'angle': 'Показать производство'},
            {'title': 'Люди', 'angle': 'Рассказать о работе специалистов'},
            {'title': 'Приглашение', 'angle': 'Объяснить условия участия'}]}
        with patch.object(app, 'plan_publication', return_value=plan) as planning, patch.object(app, 'prepare_posts') as writing:
            bot.message(42, 'Экскурсия для студентов')
            nonce = bot.context(42)['plan_nonce']
            self.assertEqual(bot.context(42)['mode'], 'plan_facts')
            writing.assert_not_called()
            bot.callback(42, 'plan_ideas:' + nonce)
            self.assertEqual(bot.context(42)['mode'], 'plan_ideas')
            self.assertEqual(planning.call_count, 1)
        with patch.object(app, 'prepare_posts', return_value={'posts': [{'topic': 'Экскурсия', 'body': '<b>Новость</b>', 'image_prompt': ''}]}) as writing:
            bot.callback(42, 'plan_draft:' + nonce + ':1')
            self.assertIn('Люди', writing.call_args.kwargs['angle'])
        self.assertEqual(bot.context(42), {})
        with self.assertRaises(ValueError):
            bot.callback(42, 'plan_draft:' + nonce + ':1')
        self.assertFalse(any(c.args[0] == 'sendMessage' and c.args[1]['chat_id'] == '@test' for c in self.api_mock.call_args_list))

    def test_planning_clarifications_keep_previous_facts(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        plan = {'facts': [{'label': 'Событие', 'value': 'Матч'}], 'question': 'Где играем?', 'ideas': []}
        with patch.object(app, 'plan_publication', return_value=plan) as planning:
            bot.plan_event(42, 'Матч', '15 ноября')
            self.assertEqual(bot.context(42)['mode'], 'plan_clarify')
            bot.message(42, 'В Уфе')
        self.assertEqual(planning.call_args.args[2], '15 ноября\nВ Уфе')
        self.assertEqual(bot.context(42)['mode'], 'plan_clarify')

    def test_company_reset_requires_confirmation_and_preserves_posts(self):
        bot.message(42, 'Компания')
        bot.message(99, 'Другая компания')
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема","Текст","demo")')
        bot.callback(42, 'company_reset')
        nonce = bot.context(42)['reset_nonce']
        self.assertEqual(bot.session(42)['step'], 1)
        bot.callback(42, 'settings')
        with self.assertRaises(ValueError):
            bot.callback(42, 'company_reset_confirm:' + nonce)
        bot.callback(42, 'company_reset')
        bot.callback(42, 'company_reset_confirm:' + bot.context(42)['reset_nonce'])
        self.assertEqual(bot.session(42)['answers'], '{}')
        self.assertEqual(bot.session(42)['step'], 0)
        self.assertEqual(bot.context(42), {})
        self.assertEqual(bot.session(99)['step'], 1)
        with app.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM bot_posts').fetchone()[0], 1)

    def test_home_layout_and_app_placeholder_preserve_context(self):
        bot.set_context(42, {'mode': 'new_task'})
        with patch.object(bot, 'say') as show:
            bot.home(42)
        rows = show.call_args.kwargs['inline']
        self.assertEqual([len(row) for row in rows], [1, 2, 2, 2])
        self.assertEqual(rows[0][0]['callback_data'], 'new')
        self.assertFalse(any(button.get('callback_data')=='tg_app' or button.get('web_app') for row in rows for button in row))
        with patch.object(bot, 'say') as show:
            bot.callback(42, 'tg_app')
            show.assert_not_called()
        self.assertEqual(bot.context(42), {'mode': 'new_task'})

    def test_unlisted_user_cannot_start(self):
        with patch.object(bot, 'message') as receive:
            bot.handle({'message': {'message_id': 7, 'chat': {'id': 777, 'type': 'private'}, 'from': {'id': 777}, 'text': '/start'}})
        receive.assert_not_called()
        bot.message(777, '/start')
        bot.message(777, 'Моя кофейня')
        self.assertIn('Моя кофейня', bot.session(777)['answers'])
        self.assertNotIn('Моя кофейня', bot.session(42)['answers'])

    def test_public_user_cannot_publish_to_team_channel(self):
        self.assertEqual(bot.publication_channel(777), '')
        self.assertEqual(bot.publication_channel(42), '@test')
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(777,"Тема","Текст","demo")')
        bot.callback(777, 'send:1:1')
        with app.db() as con:
            self.assertIsNone(con.execute('SELECT * FROM bot_confirmations').fetchone())
        self.assertFalse(any(c.args[0] == 'getChat' for c in self.api_mock.call_args_list))
        with self.assertRaises(ValueError):
            bot.callback(42, 'view:1:1')

    def test_bot_switch_resets_transport_and_preserves_business_data(self):
        bot.activate_bot(100)
        bot.message(42, '/start')
        bot.message(42, 'Компания')
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема","Текст","demo")')
        bot.enqueue({'update_id': 900, 'message': {'chat': {'id': 42}}})
        bot.activate_bot(100)
        with app.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM bot_inbox').fetchone()[0], 1)
        bot.activate_bot(200)
        with app.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM bot_inbox').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM bot_inbox_archive').fetchone()[0], 1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM bot_screens').fetchone()[0], 0)
            self.assertIsNone(con.execute('SELECT value FROM bot_meta WHERE key="offset"').fetchone())
            self.assertEqual(con.execute('SELECT COUNT(*) FROM bot_posts').fetchone()[0], 1)
            self.assertIsNotNone(con.execute('SELECT * FROM bot_sessions WHERE chat=42').fetchone())

    def test_telegram_error_does_not_expose_token(self):
        with patch.dict(app.os.environ, {'TELEGRAM_BOT_TOKEN': 'secret-token'}), patch.object(app, 'remote_json', side_effect=urllib.error.HTTPError('https://api.telegram.org/botsecret-token/getMe', 401, 'Unauthorized', {}, None)):
            # Use the real adapter rather than the class-wide mock.
            self.api.stop()
            try:
                with self.assertRaises(ValueError) as raised:
                    bot.tg('getMe', {})
                self.assertIn('TELEGRAM_BOT_TOKEN', str(raised.exception))
                self.assertNotIn('secret-token', str(raised.exception))
            finally:
                self.api.start()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = patch.object(app, 'ROOT', Path(self.temp.name))
        self.root.start()
        (app.ROOT / 'data').mkdir()
        bot.init_db()
        self.api = patch.object(bot, 'tg', return_value={'message_id': 123})
        self.api_mock = self.api.start()
        self.env = patch.dict(app.os.environ, {'TELEGRAM_OWNER_ID': '42', 'TELEGRAM_CHANNEL_ID': '@test'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.api.stop()
        self.root.stop()
        self.temp.cleanup()

    def test_questionnaire_survives_reload(self):
        bot.message(42, '/start')
        answers = ['Кофейня в Уфе', 'Студенты', 'Мало обращений', 'С юмором', 'Не выдумывать цены']
        for answer in answers:
            bot.message(42, answer)
        state = bot.session(42)
        self.assertEqual(state['step'], len(bot.QUESTIONS))
        self.assertEqual(json.loads(state['answers'])['style'], 'С юмором')
        self.assertIn('Мало обращений', bot.brief(state))
        self.assertEqual(bot.context(42)['mode'], 'review')
        bot.callback(42, 'profile_ok')
        self.assertEqual(bot.context(42), {})

    def confirmation(self, post_id=1):
        with app.db() as con:
            row = con.execute('SELECT * FROM bot_confirmations WHERE post=?', (post_id,)).fetchone()
        return f'confirm:{post_id}:{row["rev"]}:{row["nonce"]}'

    def test_edit_revokes_approval_stale_buttons_and_duplicates(self):
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема","Первый текст","demo")')
        with self.assertRaises(ValueError):
            bot.callback(42, 'confirm:1:1:fake')
        bot.callback(42, 'send:1:1')
        old_confirmation = self.confirmation()
        self.assertFalse(any(c.args[1].get('chat_id') == '@test' for c in self.api_mock.call_args_list if c.args[0] == 'sendMessage'))
        bot.callback(42, 'edit:1:1')
        with self.assertRaises(ValueError):
            bot.callback(42, old_confirmation)
        bot.callback(42, 'replace:1:1')
        bot.message(42, 'Новый текст')
        with self.assertRaises(ValueError):
            bot.callback(42, old_confirmation)
        with self.assertRaises(ValueError):
            bot.callback(42, 'confirm:1:2:fake')
        bot.callback(42, 'send:1:2')
        confirmation = self.confirmation()
        bot.callback(42, confirmation)
        with self.assertRaises(ValueError):
            bot.callback(42, confirmation)
        sends = [c for c in self.api_mock.call_args_list if c.args[0] == 'sendMessage' and c.args[1]['chat_id'] == '@test']
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0].args[1]['text'], 'Новый текст')

    def test_other_user_cannot_change_owner_data(self):
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема","Текст","demo")')
        with self.assertRaises(ValueError):
            bot.callback(99, 'edit:1:1')

    def test_two_allowed_users_can_access_bot(self):
        with patch.dict(app.os.environ, {'TELEGRAM_OWNER_ID': '8460400176,8071904711'}), patch.object(bot, 'message') as message:
            for user_id in (8460400176, 8071904711):
                bot.handle({'message': {'chat': {'id': user_id, 'type': 'private'}, 'from': {'id': user_id}, 'text': '/start'}})
            self.assertEqual(message.call_count, 2)
            message.assert_any_call(8460400176, '/start')
            message.assert_any_call(8071904711, '/start')
            bot.handle({'message': {'chat': {'id': 99, 'type': 'private'}, 'from': {'id': 99}, 'text': '/start'}})
            self.assertEqual(message.call_count, 2)

    def test_uncertain_delivery_cannot_repeat(self):
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source,status) VALUES(42,"Тема","Текст","demo","approved")')
        bot.callback(42, 'send:1:1')
        confirmation = self.confirmation()
        with patch.object(bot, 'tg', side_effect=TimeoutError):
            with self.assertRaises(ValueError):
                bot.callback(42, confirmation)
        with self.assertRaises(ValueError):
            bot.callback(42, confirmation)
        with app.db() as con:
            self.assertEqual(con.execute('SELECT status FROM bot_posts').fetchone()['status'], 'delivery_unknown')

    def test_cancel_and_restore_invalidate_old_buttons(self):
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема","Текст","demo")')
        bot.callback(42, 'send:1:1')
        old = self.confirmation()
        bot.callback(42, 'cancel:1:1')
        with self.assertRaises(ValueError):
            bot.callback(42, old)
        bot.callback(42, 'restore:1:2')
        with app.db() as con:
            post = con.execute('SELECT * FROM bot_posts').fetchone()
        self.assertEqual((post['status'], post['rev']), ('draft', 3))

    def test_channel_change_invalidates_confirmation(self):
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема","Текст","demo")')
        bot.callback(42, 'send:1:1')
        confirmation = self.confirmation()
        with patch.dict(app.os.environ, {'TELEGRAM_CHANNEL_ID': '@different'}):
            with self.assertRaises(ValueError):
                bot.callback(42, confirmation)

    def test_leaving_preview_invalidates_old_confirmation(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема","Текст","demo")')
        bot.callback(42, 'send:1:1')
        confirmation = self.confirmation()
        bot.callback(42, 'home')
        with self.assertRaises(ValueError):
            bot.callback(42, confirmation)

    def test_task_clarification_and_ai_rewrite(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{"company":"Кофейня"}', 'editing': None})
        posts = [{'topic': 'Анонс', 'body': 'Первый', 'image_prompt': ''}, {'topic': 'Напоминание', 'body': 'Второй', 'image_prompt': ''}]
        with patch.object(app, 'prepare_posts', side_effect=[{'question': 'Когда и где?'}, {'posts': posts}]) as prepare:
            bot.create_posts(42, 'Два поста о турнире')
            self.assertEqual(bot.context(42)['mode'], 'clarify')
            bot.message(42, '15 ноября в спортзале')
            self.assertEqual(prepare.call_args.args[2], '15 ноября в спортзале')
        bot.callback(42, 'edit:2:1')
        with patch.object(app, 'rewrite_post', return_value={'body': 'Короткий второй', 'memory': 'Коротко'}) as rewrite:
            bot.message(42, 'Сделай короче')
            self.assertEqual(rewrite.call_args.args[1:], ('Второй', 'Сделай короче'))
        with app.db() as con:
            rows = con.execute('SELECT * FROM bot_posts ORDER BY id').fetchall()
        self.assertEqual([p['body'] for p in rows], ['Первый', 'Короткий второй'])
        self.assertEqual(rows[1]['rev'], 2)

    def test_old_quote_dead_end_can_resume_without_quotes(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        bot.set_context(42, {'mode': 'clarify', 'task': 'Один пост о турнире', 'clarification': 'Первое место у цеха', 'question': 'Цитата не подтверждена материалами. Пришлите её дословную формулировку.'})
        bot.callback(42, 'continue_task')
        markup = self.api_mock.call_args.args[1]['reply_markup']['inline_keyboard']
        self.assertIn('without_quotes', [b['callback_data'] for row in markup for b in row])
        with patch.object(bot, 'create_posts') as create:
            bot.callback(42, 'without_quotes')
            self.assertIn('без цитат', create.call_args.args[1])
            self.assertEqual(create.call_args.args[2], 'Первое место у цеха')

    def test_multiple_clarifications_preserve_previous_facts(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        bot.set_context(42, {'mode': 'clarify', 'task': 'Один пост', 'clarification': '15 ноября, в зале'})
        with patch.object(bot, 'create_posts') as create:
            bot.message(42, 'Вход свободный')
            self.assertIn('15 ноября', create.call_args.args[2])
            self.assertIn('Вход свободный', create.call_args.args[2])

    def test_post_buttons_have_two_clear_rows(self):
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема","Текст","demo")')
        with patch.dict(app.os.environ,{'VK_ACCESS_TOKEN':''}):bot.show_post(42, 1)
        markup = self.api_mock.call_args.args[1]['reply_markup']['inline_keyboard']
        self.assertEqual([len(row) for row in markup], [2, 1, 1, 2, 1, 2, 1])
        self.assertIn("запланировать", markup[2][0]["text"])
        self.assertEqual([button['callback_data'].split(':')[0] for row in markup for button in row], ['edit', 'cancel', 'send', 'schedule', 'history', 'posts', 'feat_art', 'feat_photo_help', 'feat_image_remove', 'feat_delete'])

    def test_four_edit_iterations_use_only_temporary_compact_memory(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{"company":"Компания"}', 'editing': None})
        with patch.object(app, 'prepare_posts', return_value={'posts': [{'topic': 'Тема', 'body': '<b>Первый</b>', 'image_prompt': ''}]}):
            bot.create_posts(42, 'Один пост о кофе', 'Без цен')
        bot.callback(42, 'edit:1:1')
        instructions = ['Обращайся на вы', 'Сократи', 'Добавь вопрос', 'Убери эмодзи']
        summaries = ['На вы', 'На вы; коротко', 'На вы; коротко; вопрос', 'На вы; коротко; вопрос; без эмодзи']
        results = [{'body': f'Версия {i + 2}', 'memory': summary} for i, summary in enumerate(summaries)]
        with patch.object(app, 'rewrite_post', side_effect=results) as rewrite, patch.object(bot, 'post_memory', side_effect=AssertionError('Archive must not enter the AI context')):
            for i, instruction in enumerate(instructions):
                bot.message(42, instruction)
                self.assertEqual(bot.session(42)['editing'], 1)
                self.assertEqual(rewrite.call_args.kwargs, {'memory': summaries[i - 1] if i else '', 'brand_name_mode': 'editorial', 'publication_date': None})
                self.assertEqual(bot.context(42)['memory'], summaries[i])
        bot.init_db()
        history, origin = bot.post_memory(42, 1)
        self.assertEqual(len(history), 5)
        self.assertEqual(history[-1]['body'], 'Версия 5')
        self.assertEqual(bot.context(42)['memory'], summaries[-1])
        bot.callback(42, 'stop_edit')
        self.assertIsNone(bot.session(42)['editing'])
        self.assertEqual(bot.context(42), {})
        bot.callback(42, 'edit:1:5')
        with patch.object(app, 'rewrite_post', return_value={'body': 'Версия 6', 'memory': 'Подробно'}) as rewrite:
            bot.message(42, 'Верни подробности')
            self.assertEqual(rewrite.call_args.kwargs, {'memory': '', 'brand_name_mode': 'editorial', 'publication_date': None})

    def test_cancelling_post_clears_edit_memory(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': 1})
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема","Текст","demo")')
        bot.set_context(42, {'mode': 'edit', 'rev': 1, 'memory': 'Не упоминать цены'})
        bot.callback(42, 'cancel:1:1')
        self.assertEqual(bot.context(42), {})
        self.assertIsNone(bot.session(42)['editing'])
        bot.callback(42, 'restore:1:2')
        bot.callback(42, 'edit:1:3')
        self.assertEqual(bot.context(42)['memory'], '')

    def test_editing_another_post_does_not_inherit_memory(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': 1})
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Один","Текст","demo")')
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Другой","Иной текст","demo")')
        bot.set_context(42, {'mode': 'edit', 'rev': 1, 'memory': 'Требование только к первому посту'})
        bot.callback(42, 'edit:2:1')
        self.assertEqual(bot.context(42)['memory'], '')
        self.assertEqual(bot.session(42)['editing'], 2)

    def test_formatting_matches_card_preview_and_publication(self):
        body = '<b>Важное</b> <i>слово</i>\n<blockquote>Настоящая цитата</blockquote>'
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема",?,"deepseek")', (body,))
        bot.show_post(42, 1)
        card = self.api_mock.call_args.args[1]
        self.assertEqual(card['parse_mode'], 'HTML')
        self.assertIn(body, card['text'])
        bot.callback(42, 'send:1:1')
        preview = self.api_mock.call_args.args[1]
        self.assertIn(body, preview['text'])
        self.assertIn('@test', preview['text'])
        self.assertEqual(preview['parse_mode'], 'HTML')
        bot.callback(42, self.confirmation())
        published = [c.args[1] for c in self.api_mock.call_args_list if c.args[0] == 'sendMessage' and c.args[1]['chat_id'] == '@test'][0]
        self.assertEqual((published['text'], published['parse_mode']), (body, 'HTML'))

    def test_editorial_warnings_are_visible_but_never_published(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        post = {'topic': 'Новость', 'body': '<b>Главный факт</b>\nПодробности.', 'image_prompt': '', 'warnings': ['Проверить разрешение на упоминание сотрудника.']}
        with patch.object(app, 'prepare_posts', return_value={'posts': [post], 'status': 'ready_for_review', 'approval_status': 'draft'}):
            bot.create_posts(42, 'Один пост')
        with app.db() as con:
            self.assertEqual(con.execute('SELECT status FROM bot_posts').fetchone()[0], 'draft')
        bot.show_post(42, 1)
        self.assertEqual(self.api_mock.call_args.args[1]['text'], post['body'])
        self.assertNotIn('Черновик', self.api_mock.call_args.args[1]['text'])
        bot.callback(42, 'notes:1:1')
        self.assertIn('Проверить разрешение', self.api_mock.call_args.args[1]['text'])
        bot.callback(42, 'send:1:1')
        self.assertIn('Проверить разрешение', self.api_mock.call_args.args[1]['text'])
        bot.callback(42, self.confirmation())
        sent = [c.args[1] for c in self.api_mock.call_args_list if c.args[0] == 'sendMessage' and c.args[1]['chat_id'] == '@test']
        self.assertEqual(sent[0]['text'], post['body'])

    def test_fact_block_metadata_is_saved_for_next_edit(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        block = '<b>37 коллег</b> прошли обучение.'
        post = {'topic': 'Обучение', 'body': '<b>Итоги</b>\n\n<blockquote>' + block + '</blockquote>', 'image_prompt': '', 'fact_blocks': [block]}
        with patch.object(app, 'prepare_posts', return_value={'posts': [post]}):
            bot.create_posts(42, 'Один пост')
        bot.init_db()
        self.assertEqual(bot.review_metadata(1)['fact_blocks'], [block])
        bot.callback(42, 'edit:1:1')
        with patch.object(app, 'rewrite_post', return_value={'body': post['body'], 'memory': 'Сохранить оформление', 'fact_blocks': [block]}) as rewrite:
            bot.message(42, 'Сохрани оформление')
        self.assertEqual(rewrite.call_args.kwargs['fact_blocks'], [block])
        self.assertEqual(bot.review_metadata(1)['fact_blocks'], [block])

    def test_telegram_limit_blocks_only_publication_of_long_draft(self):
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Инструкция",?,"deepseek")', ('Данные ' * 800,))
        bot.show_post(42, 1)
        with self.assertRaisesRegex(ValueError, '4096'):
            bot.callback(42, 'send:1:1')
        with app.db() as con:
            self.assertEqual(con.execute('SELECT status FROM bot_posts').fetchone()[0], 'draft')

    def test_other_user_cannot_open_post(self):
        with app.db() as con:
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема","Текст","demo")')
        with self.assertRaises(ValueError):
            bot.callback(99, 'send:1:1')

    def test_voice_is_confirmed_before_it_becomes_a_task(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{}', 'editing': None})
        self.api_mock.return_value = {'file_path': 'voice/test.oga', 'message_id': 123}
        response = io.BytesIO(b'test-audio')
        with patch.object(app.urllib.request, 'urlopen', return_value=response), patch.object(bot.speech, 'transcribe', return_value='Два поста о кофе'), patch.dict(app.os.environ, {'TELEGRAM_BOT_TOKEN': 'test-token'}), patch.object(bot, 'message') as message:
            bot.voice_message(42, {'file_id': 'voice-test', 'duration': 4, 'file_size': 10})
            message.assert_not_called()
            pending = bot.context(42)
            bot.callback(42, 'speech:use:' + pending['nonce'])
            message.assert_called_once_with(42, 'Два поста о кофе')
            with self.assertRaises(ValueError):
                bot.callback(42, 'speech:use:' + pending['nonce'])

    def test_queue_saves_before_ack_and_does_not_replay(self):
        update = {'update_id': 123, 'message': {'chat': {'id': 42}, 'text': 'test'}}
        bot.enqueue(update)
        bot.enqueue(update)
        with app.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM bot_inbox').fetchone()[0], 1)
            self.assertEqual(con.execute('SELECT value FROM bot_meta WHERE key="offset"').fetchone()[0], 124)
        with patch.object(bot, 'handle') as handle:
            self.assertTrue(bot.consume_one(42))
            self.assertFalse(bot.consume_one(42))
            handle.assert_called_once()

    def test_queue_failure_is_not_retried_automatically(self):
        bot.enqueue({'update_id': 123, 'message': {'chat': {'id': 42}}})
        with patch.object(bot, 'handle', side_effect=RuntimeError), patch('builtins.print'):
            self.assertTrue(bot.consume_one(42))
            self.assertFalse(bot.consume_one(42))
        with app.db() as con:
            self.assertEqual(con.execute('SELECT status FROM bot_inbox').fetchone()[0], 'failed')

    def test_old_profile_is_migrated_without_losing_posts(self):
        old = {'name': 'Компания', 'about': 'Стекло', 'site': 'https://example.com', 'audience': 'Сотрудники', 'problem': 'Нет времени', 'goal': 'Регулярность', 'style': 'Деловой', 'limits': 'Не выдумывать'}
        with app.db() as con:
            con.execute('DELETE FROM bot_meta WHERE key="form_version"')
            con.execute('INSERT INTO bot_sessions VALUES(42,9,?,NULL)', (json.dumps(old),))
            con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Тема","Текст","demo")')
        bot.init_db()
        state = bot.session(42)
        self.assertEqual(state['step'], 5)
        self.assertIn('Компания', bot.brief(state))
        self.assertIn('Регулярность', bot.brief(state))
        with app.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM bot_posts').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
