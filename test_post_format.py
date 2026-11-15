import unittest
import post_format


class FormatTests(unittest.TestCase):
    def test_spoilers_survive_normalizing_and_pagination(self):
        value = '<b>Сюрприз</b>\n\n<tg-spoiler>Секрет <i>для коллег</i></tg-spoiler>'
        self.assertEqual(post_format.normalize(value), value)
        self.assertEqual(post_format.normalize('<span class="tg-spoiler">Секрет</span>'), '<tg-spoiler>Секрет</tg-spoiler>')
        self.assertEqual(post_format.normalize('<span>Обычно</span>'), 'Обычно')
        pages = post_format.split_pages(value, limit=15, formatted=True)
        parser = post_format.PostParser()
        parser.feed(''.join(pages))
        self.assertEqual(''.join(parser.text), post_format.plain(value))
        for page in pages:
            self.assertEqual(post_format.normalize(page), page)
        self.assertIn('<tg-spoiler>Сюрприз!</tg-spoiler>', post_format.layout('Новость\n\n||Сюрприз!||'))

    def test_editorial_layout_adds_headline_spacing_and_fact_labels(self):
        value = 'Встреча сотрудников\nДата: 15 ноября\nМесто: актовый зал\n\nУчастие добровольное.'
        result = post_format.layout(value)
        self.assertTrue(result.startswith('<b>Встреча сотрудников</b>\n\n'))
        self.assertIn('<b>Дата:</b> 15 ноября', result)
        self.assertIn('<b>Место:</b> актовый зал', result)
        self.assertEqual(' '.join(post_format.plain(result).split()), ' '.join(value.split()))

    def test_accidental_markdown_becomes_actual_telegram_formatting(self):
        result = post_format.layout('## Встреча\n\n**Важно:** быть вовремя.\n*Участие добровольное.*')
        self.assertIn('<b>Встреча</b>', result)
        self.assertIn('<b>Важно:</b>', result)
        self.assertIn('<i>Участие добровольное.</i>', result)
        self.assertNotIn('**', result)

    def test_valid_format_is_preserved(self):
        html = '<b>Заголовок</b>\n<i>Важно</i>\n<blockquote>Цитата</blockquote>'
        self.assertEqual(post_format.normalize(html), html)

    def test_broken_tags_are_balanced_and_attributes_removed(self):
        self.assertEqual(post_format.normalize('<b onclick="bad">Текст <i>курсив</b>'), '<b>Текст <i>курсив</i></b>')
        self.assertEqual(post_format.normalize('<a href="javascript:bad">Слово</a> & текст'), 'Слово &amp; текст')

    def test_normalization_is_idempotent(self):
        value = '<b>Польза &amp; факты</b> &lt;пример&gt;'
        self.assertEqual(post_format.normalize(post_format.normalize(value)), value)

    def test_limit_counts_visible_text(self):
        self.assertEqual(post_format.length('<b>😀</b>'), 2)
        self.assertEqual(post_format.length('<i>&amp;</i>'), 1)


if __name__ == '__main__':
    unittest.main()


class ListMarkerRegressionTests(unittest.TestCase):
    def test_black_square_markers_become_plain_bullets_without_losing_text(self):
        for marker in ('■','▪','◼','◾','⬛','◾️'):
            body='<b>Возможности</b>\n'+marker+' График\n'+marker+' Выплаты'
            normalized=post_format.layout(body)
            self.assertIn('• График\n• Выплаты',normalized)
            self.assertNotIn(marker,normalized)
            self.assertEqual(post_format.layout(normalized),normalized)
