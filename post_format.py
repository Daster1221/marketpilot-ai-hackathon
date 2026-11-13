"""Normalize the small subset of Telegram HTML used in generated posts."""
from html import escape
from html.parser import HTMLParser


class PostParser(HTMLParser):
    allowed = {'b', 'i', 'u', 's', 'blockquote'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.text = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag in self.allowed:
            if tag == 'blockquote' and tag in self.stack:
                return
            # Telegram does not allow a blockquote inside inline formatting.
            if tag == 'blockquote':
                self.close_all()
            self.parts.append('<' + tag + '>')
            self.stack.append(tag)
        elif tag == 'br':
            self.handle_data('\n')

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack:
                top = self.stack.pop()
                self.parts.append('</' + top + '>')
                if top == tag:
                    break

    def handle_data(self, data):
        self.parts.append(escape(data, quote=False))
        self.text.append(data)

    def close_all(self):
        while self.stack:
            self.parts.append('</' + self.stack.pop() + '>')


def normalize(value):
    parser = PostParser()
    parser.feed(value)
    parser.close()
    parser.close_all()
    return ''.join(parser.parts).strip()


def plain(value):
    parser = PostParser()
    parser.feed(value)
    parser.close()
    return ''.join(parser.text).strip()


def length(value):
    return len(plain(value).encode('utf-16-le')) // 2


AI_FORMAT_RULES = (
    ' Форматируй body в Telegram HTML: <b> для короткого заголовка и важных слов, '
    '<i> для уместных акцентов, <blockquote> только для предоставленных пользователем дословных цитат. '
    'Не выдумывай цитаты, не превращай пересказ в прямую речь. Не выделяй весь текст. '
    'Разрешены только теги b, i, u, s, blockquote без атрибутов. '
    'Не используй Markdown, HTML-обёртки, ссылки или блоки кода. Переносы строк — обычные символы новой строки.'
)
