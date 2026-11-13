import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import company_knowledge as knowledge
import telegram_bot as bot


class CompanyKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = patch.object(app, 'ROOT', Path(self.temp.name))
        self.root.start()
        (app.ROOT / 'data').mkdir()
        bot.init_db()

    def tearDown(self):
        self.root.stop()
        self.temp.cleanup()

    def test_site_summary_is_cached_per_user_and_reaches_brief_and_edits(self):
        site = 'https://company.ru/'
        bot.save({'chat': 42, 'step': 5, 'answers': json.dumps({'company': 'Компания', 'site': site}), 'editing': None})
        with patch.object(knowledge, 'fetch', return_value=(site, 'Производство стекла в Уфе. ' * 10, [])) as fetch, patch.object(app, 'ai_json', return_value={'summary': 'Производит стекло в Уфе.'}) as ai:
            knowledge.study(42, site)
            knowledge.study(42, site)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(ai.call_count, 1)
        self.assertIn('Производит стекло', bot.brief(bot.session(42)))
        self.assertIn(site, bot.edit_brand_rules(bot.session(42)))
        self.assertNotIn('Производит стекло', bot.brief(bot.session(99)))

    def test_private_hosts_and_credentials_are_rejected(self):
        for address in ('127.0.0.1', '10.1.2.3', '::1', '169.254.169.254'):
            with patch.object(knowledge.socket, 'getaddrinfo', return_value=[(0, 0, 0, '', (address, 0))]):
                with self.assertRaises(ValueError):
                    knowledge.public_url('http://company.ru')
        with self.assertRaises(ValueError):
            knowledge.normalize_url('https://login:password@company.ru')

    def test_scripts_are_not_company_facts(self):
        page = knowledge.Page()
        page.feed('<h1>Стекло</h1><script>SECRET()</script><style>hidden</style><p>Производство</p>')
        self.assertEqual(page.text, ['Стекло', 'Производство'])

    def test_site_input_keeps_task_and_company_reset_clears_knowledge(self):
        bot.save({'chat': 42, 'step': 5, 'answers': '{"company":"Компания"}', 'editing': None})
        bot.set_context(42, {'mode': 'plan_correct', 'task': 'Матч'})
        with patch.object(bot, 'say'), patch.object(bot, 'study_company', return_value=False):
            bot.callback(42, 'company_site')
            bot.message(42, 'company.ru')
        self.assertEqual(bot.context(42)['task'], 'Матч')
        self.assertEqual(bot.company_site(bot.session(42)), 'https://company.ru/')
        with app.db() as con:
            con.execute('INSERT INTO bot_company_knowledge(chat,url,summary,sources) VALUES(42,?,?,?)', ('https://company.ru/', 'Производство', '[]'))
        with patch.object(bot, 'say'):
            bot.callback(42, 'company_reset')
            bot.callback(42, 'company_reset_confirm:' + bot.context(42)['reset_nonce'])
        self.assertIsNone(knowledge.get(42))


if __name__ == '__main__':
    unittest.main()
