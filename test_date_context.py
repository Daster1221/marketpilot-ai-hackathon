import unittest
from unittest.mock import patch
import app
import date_context
import editorial


class DateContextTests(unittest.TestCase):
    def test_last_event_correction_replaces_earlier_dates_without_losing_details(self):
        result = date_context.resolve('Волейбол в пятницу 13-го числа в октябре. Будут призы.', 'Начало 13:00, конец 20:00\n15 МАРТА\n15 октября')
        self.assertEqual(result['current_event_date'], '15 октября')
        self.assertNotIn('пятницу', result['task'])
        self.assertNotIn('13-го', result['task'])
        self.assertNotIn('МАРТА', result['clarification'])
        self.assertIn('13:00', result['clarification'])
        self.assertIn('20:00', result['clarification'])
        self.assertIn('призы', result['task'])

    def test_publication_date_is_not_an_event_correction(self):
        result = date_context.resolve('Матч 15 октября', 'Дата публикации 10 октября в 12:00')
        self.assertIsNone(result['current_event_date'])
        self.assertEqual(result['task'], 'Матч 15 октября')

    def test_invalid_and_multiple_program_dates_are_not_silently_replaced(self):
        result = date_context.resolve('Встреча', '31 февраля')
        self.assertIsNone(result['current_event_date'])
        result = date_context.resolve('Начало 13 октября, финал 16 октября', '15 октября')
        self.assertIn('13 октября', result['task'])
        self.assertIn('16 октября', result['task'])

    def test_draft_receives_current_event_date_and_does_not_ask_publication_date(self):
        with patch.object(app, 'ai_json', return_value={'post': {'topic': 'Матч', 'body': '<b>Волейбол</b>\nВ пятницу, 15 октября играем в волейбол.'}}) as model:
            result = app.prepare_posts('', 'Волейбол в пятницу 13-го числа в октябре', '15 МАРТА\n15 октября')
        payload = model.call_args.args[1]
        self.assertEqual(payload['current_event_date'], '15 октября')
        self.assertIsNone(payload['publication_date'])
        self.assertNotIn('МАРТА', payload['clarification'])
        self.assertEqual(result['status'], 'ready_for_review')
        self.assertNotIn('пятницу', result['posts'][0]['body'])
        self.assertIn('15 октября', result['posts'][0]['body'])


if __name__ == '__main__':
    unittest.main()
