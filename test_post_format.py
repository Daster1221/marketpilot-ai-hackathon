import unittest
import post_format


class FormatTests(unittest.TestCase):
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
