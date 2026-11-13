"""Resolve explicit event-date corrections before sending material to the model."""
import re
from datetime import date

MONTHS = ('января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря')
DATE = r'(\d{1,2})\s+(' + '|'.join(MONTHS) + r')(?:\s+(\d{4}))?'
WEEKDAY = r'(?:понедельник\w*|вторник\w*|сред[ауы]|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*)'
RULES = '''Правила дат: current_event_date содержит последнее явное исправление даты события. Оно заменяет старую дату и старый день недели. Дата события и дата публикации независимы. Без года не вычисляй день недели: напиши подтверждённые число и месяц. Не спрашивай дату публикации, если можно написать пост с конкретной датой события. Не добавляй «сегодня» или «завтра» по собственной инициативе. Уточняй только оставшуюся неоднозначность обычным языком.'''


def resolve(task, clarification):
    lines = clarification.splitlines()
    corrections = []
    for i, line in enumerate(lines):
        match = re.fullmatch(r'\s*(?:(?:нет|исправление|переносим на|дата события)\s*[:,]?\s*)?' + DATE + r'\s*[.!]?\s*', line, flags=re.I)
        if match:
            day, month = int(match[1]), MONTHS.index(match[2].lower()) + 1
            year = int(match[3]) if match[3] else None
            try:
                date(year or 2000, month, day)
            except ValueError:
                continue
            label = f'{day} {MONTHS[month - 1]}' + (f' {year}' if year else '')
            corrections.append((i, label))
    if not corrections:
        return {'task': task, 'clarification': clarification, 'current_event_date': None}
    selected = corrections[-1][1]
    # Only unambiguous standalone corrections are collapsed; other details stay.
    indices = {i for i, _ in corrections}
    remaining = [line for i, line in enumerate(lines) if i not in indices]
    remaining.append('Дата события: ' + selected)
    # Remove a superseded weekday; a year must never be guessed to reconcile it.
    task = re.sub(r'\b(?:в|во)\s+' + WEEKDAY + r'\s*,?\s*', '', task, flags=re.I)
    old_date = r'\b\d{1,2}(?:-?го)?\s*(?:числа\s+)?(?:в\s+)?(?:' + '|'.join(MONTHS) + r'|январе|феврале|марте|апреле|мае|июне|июле|августе|сентябре|октябре|ноябре|декабре)(?:\s+\d{4})?\b'
    if len(list(re.finditer(old_date, task, flags=re.I))) == 1 and not re.search(r'публикац|публикуем', task, flags=re.I):
        task = re.sub(old_date, selected, task, flags=re.I)
    return {'task': task, 'clarification': '\n'.join(remaining), 'current_event_date': selected}
