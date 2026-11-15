"""Normalize the small subset of Telegram HTML used in generated posts."""
from html import escape
from html.parser import HTMLParser
import re


def opening_tag(tag,attrs=()):
    values=dict(attrs)
    if tag=='tg-emoji':
        identifier=values.get('emoji-id','') or ''
        return '<tg-emoji emoji-id="'+identifier+'">' if re.fullmatch(r'[0-9]{1,25}',identifier) else ''
    if tag=='blockquote' and 'expandable' in values:return '<blockquote expandable>'
    return '<'+tag+'>'


class PostParser(HTMLParser):
    allowed = {'b', 'i', 'u', 's', 'blockquote', 'tg-spoiler','tg-emoji'}

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
            opening=opening_tag(tag,attrs)
            if not opening:return
            if tag == 'blockquote' and tag in self.stack:
                return
            # Telegram does not allow a blockquote inside inline formatting.
            if tag == 'blockquote':
                self.close_all()
            self.parts.append(opening)
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
        data = re.sub(r'(?m)^([ \t]*)[■▪◼◾⬛□▫◻]\ufe0f?[ \t]*', r'\1• ', data)
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
    if sep and plain(head) and length(head) <= 160 and not head.lstrip().startswith(('-', '○', '<blockquote')):
        if not head.startswith('<b>'):
            head = '<b>' + head + '</b>'
        value = head + '\n\n' + rest.lstrip('\n')
    return normalize(re.sub(r'\n{3,}', '\n\n', value))


def split_pages(value, limit=3600, formatted=False):
    """Split visible text without breaking Unicode characters or HTML entities/tags."""
    if limit < 2:
        raise ValueError('Page limit must be at least two UTF-16 units')
    source = normalize(value) if formatted else value
    pages, parts, stack,openings = [], [], [],[]
    units = 0

    def flush():
        nonlocal parts, units
        if units:
            pages.append(''.join(parts) + ''.join('</' + tag + '>' for tag in reversed(stack)))
        parts = list(openings)
        units = 0

    def add_text(text):
        nonlocal units
        for token in re.findall(r'\s+|\S+',text):
            token_size=len(token.encode('utf-16-le'))//2
            if token_size<=limit and units+token_size>limit:
                flush()
            for char in token:
                size = len(char.encode('utf-16-le')) // 2
                if units + size > limit:
                    flush()
                parts.append(escape(char, quote=False) if formatted else char)
                units += size

    if formatted:
        class Pager(HTMLParser):
            emoji_parts=None
            def handle_starttag(self, tag, attrs):
                opening=opening_tag(tag,attrs)
                if self.emoji_parts is not None:
                    self.emoji_parts.append(opening);return
                if tag=='tg-emoji':
                    self.emoji_parts=[opening];return
                parts.append(opening);openings.append(opening)
                stack.append(tag)

            def handle_endtag(self, tag):
                nonlocal units
                if self.emoji_parts is not None:
                    self.emoji_parts.append('</'+tag+'>')
                    if tag=='tg-emoji':
                        atom=''.join(self.emoji_parts);self.emoji_parts=None
                        count=length(atom)
                        if count>limit:add_text(plain(atom))
                        else:
                            if units+count>limit:flush()
                            parts.append(atom);units+=count
                    return
                parts.append('</' + tag + '>')
                stack.pop()
                openings.pop()

            def handle_data(self, text):
                if self.emoji_parts is not None:self.emoji_parts.append(escape(text,quote=False))
                else:add_text(text)
        parser = Pager(convert_charrefs=True)
        parser.feed(source)
        parser.close()
    else:
        add_text(source)
    flush()
    return pages or ['…']


AI_FORMAT_RULES = (
    ' Оформи готовый пост в Telegram HTML: короткий заголовок в <b>, удобные абзацы, смысловые выделения там, где они помогают чтению. '
    'Структуру определяет развитие мысли, а не обязательный набор лида, списка и плашки. '
    'Выделяй главную мысль и важные числа жирным, короткую ремарку курсивом; не раскрашивай каждый абзац. Для смысловой плашки доступен <aside>, а для длинного раскрываемого блока <aside expandable>. Используй по делу, не разрывая рассказ. '
    '<blockquote> только для действительно приведённых слов человека. '
    'Используй возможности оформления заметно и по смыслу: расписание, адрес или ключевую авторскую мысль можно вынести в <aside> — бот покажет цитатную плашку, это не прямая речь. Короткий авторский акцент можно оформить <i>. Необязательную интригу или дополнительную деталь можно оформить <tg-spoiler>; не скрывай адрес, дату, условия и главное действие. Если пользователь попросил цитатное оформление, а слов человека нет, используй авторскую плашку <aside>, не выдумывай говорящего. '
    'Разрешены b, i, u, s, tg-spoiler, blockquote и внутренний aside; для aside и blockquote допустим только атрибут expandable. В спойлер не прячь условия участия. '
    'Списки оформляй маркером • или нумерацией. Чёрные квадраты ■, ▪, ◼, ◾, ⬛ запрещены. Не ставь эмодзи перед каждым пунктом. '
    'Используй обычные переносы строк, без Markdown, HTML-обёрток и блоков кода. Ссылки пиши обычным текстом, если они даны в материалах.'
)
