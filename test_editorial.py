import unittest
from unittest.mock import patch

import app
import editorial
import post_format


class EditorialTests(unittest.TestCase):
    def test_current_style_preserves_spoilers_tags_and_punctuation(self):
        body = '<b>Масленица!</b>\n\nКто придёт?\n<aside>9:00–13:00 — игры.</aside>\n<tg-spoiler>Сюрприз!</tg-spoiler>\n#Масленица #Уфа'
        text, notes = editorial.clean_body(body, 'Масленица, Уфа, игры с 9:00 до 13:00. Сюрприз!')
        self.assertNotIn('—', text)
        self.assertNotIn('–', text)
        self.assertIn('9:00-13:00 - игры.', text)
        self.assertIn('<tg-spoiler>Сюрприз!</tg-spoiler>', text)
        self.assertIn('#Масленица #Уфа', text)
        self.assertIn('Кто придёт?', text)
        self.assertIn('Масленица!', text)

    def test_one_post_is_default_and_contract_cannot_approve(self):
        response = {'status': 'ready_for_review', 'approval_status': 'approved', 'post': {'topic': 'Новость', 'body': '<b>Салаватстекло: новый участок</b>\nДанные.', 'warnings': ['Проверить разрешение на публикацию.']}}
        with patch.object(app, 'ai_json', return_value=response) as ai:
            result = app.prepare_posts('', 'Подготовь пост: открыли новый участок.')
        self.assertEqual(ai.call_args.args[1]['count'], 1)
        self.assertEqual(result['approval_status'], 'draft')
        self.assertEqual(len(result['posts']), 1)
        self.assertIn('САЛАВАТСТЕКЛО', result['posts'][0]['body'])
        self.assertNotIn('Проверить разрешение', result['posts'][0]['body'])
        self.assertTrue(result['posts'][0]['warnings'])

    def test_emoji_removed_tags_preserved_and_markers_limited(self):
        result, notes = editorial.clean_body('<b>Новость 😀</b>\n○ Данные\n\n○ Итог\n\n○ Лишний\n#Футбол #Уфа')
        self.assertNotIn('😀', result)
        self.assertIn('#Уфа', result)
        self.assertIn('#Футбол', result)
        self.assertLessEqual(result.count('○'), 2)
        self.assertTrue(notes)

    def test_markers_are_not_list_bullets(self):
        result, _ = editorial.clean_body('○ Первый\n○ Второй\n○ Третий')
        self.assertEqual(result, '- Первый\n- Второй\n- Третий')

    def test_brand_modes_preserve_legal_name_and_quote(self):
        body = 'Салаватстекло; АО «Салаватстекло»\n<blockquote>Мы из Салаватстекло</blockquote>\n#Салаватстекло'
        brand, _ = editorial.clean_body(body, 'Мы из Салаватстекло')
        self.assertTrue(post_format.plain(brand).startswith('САЛАВАТСТЕКЛО; АО «Салаватстекло»'))
        self.assertIn('<blockquote>Мы из Салаватстекло</blockquote>', brand)
        self.assertIn('#Салаватстекло', brand)
        text, _ = editorial.clean_body('САЛАВАТСТЕКЛО', mode='editorial')
        self.assertEqual(text, 'Салаватстекло')

    def test_relative_dates_need_publication_date(self):
        response = {'post': {'topic': 'Новость', 'body': 'Завтра встреча в зале.'}}
        with patch.object(app, 'ai_json', return_value=response):
            result = app.prepare_posts('', 'Один пост о встрече.')
        self.assertEqual(result['status'], 'needs_clarification')
        self.assertEqual(result['posts'], [])
        self.assertIn('дату', result['question'])
        self.assertEqual(editorial.request_settings('publication_date=2026-11-13')['publication_date'], '2026-11-13')

    def test_publication_date_in_natural_language_does_not_need_year(self):
        self.assertEqual(editorial.request_settings('дата публикации тоже 15 марта в 13.00')['publication_date'], '15 марта')
        self.assertEqual(editorial.request_settings('Публикуем 15 марта 2027 в 13:00')['publication_date'], '2027-03-15')
        response = {'post': {'topic': 'Поздравление', 'body': '<b>С днём рождения!</b>\nСегодня поздравляем Владислава Владиславовича. Пишите поздравления в комментариях!'}}
        with patch.object(app, 'ai_json', return_value=response):
            result = app.prepare_posts('', 'Сегодня день рождения.', 'Дата публикации тоже 15 марта в 13.00. Не указывай возраст.')
        self.assertEqual(result['status'], 'ready_for_review')
        self.assertIn('15 марта поздравляем', result['posts'][0]['body'])
        self.assertNotIn('Сегодня', result['posts'][0]['body'])
        with self.assertRaises(ValueError):
            editorial.request_settings('Публикуем 31 февраля')

    def test_noncalendar_environment_does_not_trigger_weekday_validation(self):
        text, _ = editorial.clean_body('<b>Рабочая среда</b>\nРазвитие среды для сотрудников.')
        self.assertIn('Рабочая среда', text)

    def test_unconfirmed_quote_and_url_are_not_ready_posts(self):
        for body in ['<blockquote>Выдуманная цитата</blockquote>', 'Регистрация https://unconfirmed.example/path']:
            with patch.object(app, 'ai_json', return_value={'post': {'topic': 'Новость', 'body': body}}):
                result = app.prepare_posts('', 'Подготовь один пост о компании.')
            self.assertEqual(result['status'], 'needs_clarification')

    def test_extra_url_is_removed_without_blocking_a_useful_draft(self):
        body = '<b>Начался турнир</b>\nИграют команды сотрудников.\nПодробнее: https://made-up.example/'
        with patch.object(app, 'ai_json', return_value={'post': {'topic': 'Турнир', 'body': body}}):
            result = app.prepare_posts('', 'Один пост: начался турнир, играют команды сотрудников.')
        self.assertEqual(result['status'], 'ready_for_review')
        self.assertNotIn('made-up', result['posts'][0]['body'])
        self.assertIn('Играют команды', result['posts'][0]['body'])
        self.assertTrue(result['posts'][0]['warnings'])

    def test_invented_quote_is_removed_without_blocking_real_facts(self):
        body = '<b>Турнир завершён</b>\nКоманда цеха заняла первое место.\n<blockquote>Это было лучшее событие года</blockquote>'
        with patch.object(app, 'ai_json', return_value={'post': {'topic': 'Турнир', 'body': body}}):
            result = app.prepare_posts('', 'Один пост: турнир завершён, команда цеха заняла первое место.')
        self.assertEqual(result['status'], 'ready_for_review')
        self.assertIn('первое место', result['posts'][0]['body'])
        self.assertNotIn('лучшее событие', result['posts'][0]['body'])
        self.assertNotIn('<blockquote>', result['posts'][0]['body'])
        self.assertIn('Неподтверждённая цитата удалена.', result['posts'][0]['warnings'])

    def test_real_quote_tolerates_typography_without_losing_block(self):
        body = '<b>Встреча</b>\n<blockquote>Мы работаем — вместе.</blockquote>'
        text, notes = editorial.clean_body(body, 'Сотрудник сказал: «Мы работаем - вместе.»')
        self.assertIn('<blockquote>Мы работаем — вместе.</blockquote>', text)
        self.assertNotIn('Неподтверждённая цитата удалена.', notes)

    def test_fact_callout_is_not_mistaken_for_direct_speech(self):
        text, notes, blocks = editorial.clean_body('<b>Итоги обучения</b>\nКурс завершён.\n<aside><b>37 коллег</b> из пяти подразделений прошли обучение.</aside>',
                                                  'Обучили 37 сотрудников, подразделений было пять.', return_blocks=True)
        self.assertIn('<blockquote><b>37 коллег</b>', text)
        self.assertNotIn('<aside>', text)
        self.assertNotIn('MPFACT', text)
        self.assertEqual(len(blocks), 1)
        self.assertNotIn('Неподтверждённая цитата удалена.', notes)

    def test_fact_callout_and_fake_quote_are_handled_separately(self):
        text, notes, blocks = editorial.clean_body('<b>Курс завершён</b>\n<aside>Обучение прошли <b>37 коллег</b>.</aside>\n<blockquote>Такого успеха ещё не было</blockquote>',
                                                  'Курс завершили 37 сотрудников.', return_blocks=True)
        self.assertIn('37 коллег', text)
        self.assertNotIn('Такого успеха', text)
        self.assertEqual(len(blocks), 1)
        self.assertIn('Неподтверждённая цитата удалена.', notes)

    def test_fact_callout_survives_editing_without_history_growth(self):
        block = 'Курс прошли <b>37 сотрудников</b>.'
        body = '<b>Обучение</b>\n\n<blockquote>' + block + '</blockquote>'
        with patch.object(app, 'ai_json', return_value={'body': body, 'memory': 'Коротко'}) as ai:
            result = app.rewrite_post('', body, 'Сохрани цифры', fact_blocks=[block])
        self.assertIn('<aside>', ai.call_args.args[1]['body'])
        self.assertNotIn('history', ai.call_args.args[1])
        self.assertIn('<blockquote>', result['body'])
        self.assertEqual(result['fact_blocks'], [block])

    def test_training_examples_are_separate_from_current_facts(self):
        response = {'post': {'topic': 'Новость', 'body': '<b>37 коллег завершили обучение</b>\nПять подразделений.'}}
        with patch.object(app, 'ai_json', return_value=response) as ai:
            app.prepare_posts('', 'Один пост: обучение завершили 37 сотрудников из пяти подразделений.')
        system, data = ai.call_args.args
        self.assertIn('ВЫМЫШЛЕННЫЕ учебные примеры', system)
        self.assertIn('Не превращай каждый пост в анкету', system)
        self.assertIn('37 сотрудников', data['task'])
        self.assertNotIn('training_facts_only', data)
        text, notes = editorial.clean_body('<b>Встреча</b>\n<blockquote>Мы **работаем** вместе.</blockquote>', 'Мы работаем вместе.')
        self.assertIn('<blockquote>Мы <b>работаем</b> вместе.</blockquote>', text)
        self.assertNotIn('Неподтверждённая цитата удалена.', notes)

    def test_profile_website_and_equivalent_root_url_are_allowed(self):
        with patch.object(app, 'ai_json', return_value={'post': {'topic': 'Компания', 'body': '<b>О компании</b>\nНаш сайт: https://EXAMPLE.ru/'}}):
            result = app.prepare_posts('Сайт компании https://example.ru', 'Один пост о компании.')
        self.assertEqual(result['status'], 'ready_for_review')
        self.assertIn('https://EXAMPLE.ru/', result['posts'][0]['body'])

    def test_unconfirmed_url_does_not_match_a_prefix_of_confirmed_url(self):
        text, notes = editorial.clean_body('<b>Новость</b>\nДанные: https://example.ru', 'Сайт: https://example.ru.fake/')
        self.assertNotIn('https://example.ru', text)
        self.assertTrue(notes)

    def test_long_draft_is_retained_with_technical_warning(self):
        with patch.object(app, 'ai_json', return_value={'post': {'topic': 'Инструкция', 'body': 'Данные ' * 800}}):
            result = app.prepare_posts('', 'Один пост с инструкцией.')
        self.assertGreater(post_format.length(result['posts'][0]['body']), 4096)
        self.assertTrue(result['posts'][0]['warnings'])

    def test_rewrite_uses_same_editorial_rules_and_keeps_summary_bounded(self):
        with patch.object(app, 'ai_json', return_value={'body': '<b>Салаватстекло</b>\nНовость 🎉', 'memory': 'Коротко', 'warnings': ['Проверить факты']}) as ai:
            result = app.rewrite_post('', 'Новость', 'Уточни стиль', memory='Коротко')
        self.assertIn(editorial.CORE_RULES, ai.call_args.args[0])
        self.assertNotIn('training_facts_only', ai.call_args.args[0])
        self.assertNotIn('🎉', result['body'])
        self.assertEqual(result['memory'], 'Коротко')
        self.assertIn('Проверить факты', result['warnings'])


if __name__ == '__main__':
    unittest.main()
