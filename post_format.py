"""Normalize the small subset of Telegram HTML used in generated posts."""
from html import escape
from html.parser import HTMLParser
import re


class PostParser(HTMLParser):
    allowed = {'b', 'i', 'u', 's', 'blockquote', 'tg-spoiler'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.text = []
        self.stack = []
        self.span_spoilers = []

    def handle_starttag(self, tag, attrs):
        if tag == 'span':
            spoiler = dict(attrs).get('class') == 'tg-spoiler'
            self.span_spoilers.append(spoiler)
            if not spoiler:
                return
            tag = 'tg-spoiler'
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
        if tag == 'span':
            if not self.span_spoilers or not self.span_spoilers.pop():
                return
            tag = 'tg-spoiler'
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


def layout(value):
    """Improve spacing and a supplied headline without inventing facts or headings."""
    value = normalize(value).replace('\r\n', '\n')
    # Tolerate accidental Markdown without exposing its markup in Telegram.
    value = re.sub(r'(?m)^#{1,3}\s+(.+)$', r'<b>\1</b>', value)
    value = re.sub(r'\*\*([^*\n]+)\*\*', r'<b>\1</b>', value)
    value = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<i>\1</i>', value)
    value = re.sub(r'\|\|(.+?)\|\|', r'<tg-spoiler>\1</tg-spoiler>', value, flags=re.S)
    value = normalize(value)
    value = re.sub(r'(?m)^((?:Дата|Время|Место|Начало|Регистрация|Участники|Результат|Срок)\s*:)', r'<b>\1</b>', value)
    head, sep, rest = value.partition('\n')
    if sep and plain(head) and length(head) <= 160 and not head.lstrip().startswith(('-', '○', '<blockquote>')):
        if not head.startswith('<b>'):
            head = '<b>' + head + '</b>'
        value = head + '\n\n' + rest.lstrip('\n')
    return normalize(re.sub(r'\n{3,}', '\n\n', value))


def split_pages(value, limit=3600, formatted=False):
    """Split visible text without breaking Unicode characters or HTML entities/tags."""
    if limit < 2:
        raise ValueError('Page limit must be at least two UTF-16 units')
    source = normalize(value) if formatted else value
    pages, parts, stack = [], [], []
    units = 0

    def flush():
        nonlocal parts, units
        if units:
            pages.append(''.join(parts) + ''.join('</' + tag + '>' for tag in reversed(stack)))
        parts = ['<' + tag + '>' for tag in stack]
        units = 0

    def add_text(text):
        nonlocal units
        for char in text:
            size = len(char.encode('utf-16-le')) // 2
            if units + size > limit:
                flush()
            parts.append(escape(char, quote=False) if formatted else char)
            units += size

    if formatted:
        class Pager(HTMLParser):
            def handle_starttag(self, tag, attrs):
                parts.append('<' + tag + '>')
                stack.append(tag)

            def handle_endtag(self, tag):
                parts.append('</' + tag + '>')
                stack.pop()

            def handle_data(self, text):
                add_text(text)
        parser = Pager(convert_charrefs=True)
        parser.feed(source)
        parser.close()
    else:
        add_text(source)
    flush()
    return pages or ['…']


AI_FORMAT_RULES = (
    ' Оформляй body как готовый Telegram-пост в HTML. Первая строка — короткий заголовок с главным фактом целиком в <b>. '
    'После заголовка — пустая строка и ясный лид. Отделяй смысловые абзацы пустой строкой; избегай стены текста. '
    'Выделяй <b>ключевые даты, место, результат или нужное действие</b>, когда они есть в исходных данных. '
    'Для короткой второстепенной ремарки уместен <i>курсив</i>. Не выделяй целые абзацы и не создавай акценты ради акцентов. '
    'Спойлер оформляй как <tg-spoiler>скрытый текст</tg-spoiler>. Используй по просьбе пользователя или для уместного сюрприза, не скрывай дату, адрес и обязательные условия. '
    'Однородные факты, расписание и инструкции оформляй списком с дефисами или номерами. Не делай список для обычного рассказа. '
    'Для отдельной плашки подтверждённых цифр или важных фактов используй внутренний тег <aside>...</aside>; '
    'бот отобразит его как Telegram-блок. Это авторское изложение фактов, а не прямая речь. Не повторяй соседний абзац. '
    '<blockquote> используй только для реальной дословной цитаты из входа. Не выдумывай цитаты и говорящих. '
    'В развёрнутом анонсе с программой или несколькими фактами обязательно сделай одну компактную плашку aside. В коротком служебном уведомлении она необязательна. '
    'Разрешены теги b, i, u, s, tg-spoiler, blockquote и внутренний aside без атрибутов. Не вкладывай блоки друг в друга. '
    'Не используй Markdown, HTML-обёртки, теги ссылок или блоки кода. Подтверждённые URL пиши обычным текстом. '
    'Переносы строк — обычные символы новой строки.'
)
