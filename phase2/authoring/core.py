"""Shared authoring helpers for the phase-two v2 suite.

Every task is generated from a fixed seed into one canonical dataset. The English and
Hindi workspaces render that same dataset with identical per-cell format choices, so
both workspaces carry exactly the same facts; only language and script differ. Every
rendered cell is parsed back and compared with the canonical value before a task is
materialized.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import random
import re

DEV = '०१२३४५६७८९'
TO_DEV = str.maketrans('0123456789', DEV)
FROM_DEV = str.maketrans(DEV, '0123456789')
MONTH_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTH_HI = ['जनवरी', 'फ़रवरी', 'मार्च', 'अप्रैल', 'मई', 'जून', 'जुलाई', 'अगस्त', 'सितंबर',
            'अक्टूबर', 'नवंबर', 'दिसंबर']


def D(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def half_up(value, places=0):
    return D(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def out_num(value, places=0):
    """Canonical output text for a number with a fixed number of decimals."""
    return f'{half_up(value, places):.{places}f}'


def out_date(value):
    return value.isoformat()


def out_time(minutes):
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def out_datetime(value):
    return value.strftime('%Y-%m-%d %H:%M')


def ascii_digits(text):
    return text.translate(FROM_DEV)


def indian_group(number):
    digits = str(number)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ','.join(parts + [tail])


def plain(value):
    """Decimal to plain text without exponent or trailing zeros."""
    text = format(D(value).normalize(), 'f')
    return text


# ---------------------------------------------------------------- cell kinds

class Kind:
    def render(self, value, lang, style):
        raise NotImplementedError

    def parse(self, text, lang):
        raise NotImplementedError


def pad(text, style):
    # A few identifiers and codes carry stray spaces, as exported registers often do.
    return text + ' ' if style % 23 == 5 else text


class Id(Kind):
    def __init__(self, noisy=True):
        self.noisy = noisy

    def render(self, value, lang, style):
        if value is None:
            return ''
        return pad(str(value), style) if self.noisy else str(value)

    def parse(self, text, lang):
        return text.strip() or None


class Text(Kind):
    """Free text. A value is either a string or a {'en','hi'} mapping."""

    def render(self, value, lang, style):
        if value is None:
            return ''
        return value[lang] if isinstance(value, dict) else value

    def parse(self, text, lang):
        return text


class Int(Kind):
    def __init__(self, devanagari=True):
        self.devanagari = devanagari

    def render(self, value, lang, style):
        if value is None:
            return ''
        text = str(value)
        return text.translate(TO_DEV) if lang == 'hi' and self.devanagari and style % 3 == 0 else text

    def parse(self, text, lang):
        text = ascii_digits(text.strip())
        return int(text) if text else None


class Num(Kind):
    def __init__(self, places):
        self.places = places

    def render(self, value, lang, style):
        if value is None:
            return ''
        text = plain(value) if self.places is None else f'{D(value):.{self.places}f}'
        return text.translate(TO_DEV) if lang == 'hi' and style % 3 == 0 else text

    def parse(self, text, lang):
        text = ascii_digits(text.strip())
        return D(text) if text else None


class Money(Kind):
    """Whole-rupee amounts in the mixed formats seen in Indian ledgers."""

    def render(self, value, lang, style):
        if value is None:
            return ''
        n = int(value)
        g = indian_group(n)
        option = style % 5
        if lang == 'en':
            return [str(n), g, '₹' + g, 'Rs ' + g, f'Rs. {n}.00'][option]
        return [str(n), '₹' + g, g + ' रुपये', '₹' + g.translate(TO_DEV),
                f'{n}.00 रु.'.translate(TO_DEV)][option]

    def parse(self, text, lang):
        text = ascii_digits(text.strip())
        for token in ('₹', 'Rs.', 'Rs', 'रुपये', 'रु.', ',', ' '):
            text = text.replace(token, '')
        if not text:
            return None
        value = D(text)
        if value != value.to_integral_value():
            raise ValueError('Non-integral rupee amount')
        return int(value)


class Date(Kind):
    def render(self, value, lang, style):
        if value is None:
            return ''
        option = style % 4
        if option == 0:
            return value.isoformat()
        if option == 1:
            text = value.strftime('%d/%m/%Y')
            return text.translate(TO_DEV) if lang == 'hi' and style % 7 == 3 else text
        months = MONTH_EN if lang == 'en' else MONTH_HI
        if option == 2:
            return f'{value.day} {months[value.month - 1]} {value.year}'
        if lang == 'en':
            return f'{value.day:02d}-{months[value.month - 1]}-{value.year}'
        return f'{value.day} {months[value.month - 1]} {value.year}'.translate(TO_DEV)

    def parse(self, text, lang):
        text = ascii_digits(text.strip())
        if not text:
            return None
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
            return date.fromisoformat(text)
        match = re.fullmatch(r'(\d{2})/(\d{2})/(\d{4})', text)
        if match:
            return date(int(match[3]), int(match[2]), int(match[1]))
        match = re.fullmatch(r'(\d{1,2})[ -](\S+)[ -](\d{4})', text)
        months = MONTH_EN if lang == 'en' else MONTH_HI
        return date(int(match[3]), months.index(match[2]) + 1, int(match[1]))


HI_PERIODS = (('सुबह', 4, 11), ('दोपहर', 12, 15), ('शाम', 16, 19), ('रात', 20, 23))


def hi_period(hour):
    for word, low, high in HI_PERIODS:
        if low <= hour <= high:
            return word
    raise ValueError('Hour outside the generated range')


class Time(Kind):
    """Minutes after midnight, restricted to 04:00-23:59 so every form is unambiguous."""

    def render(self, value, lang, style):
        if value is None:
            return ''
        hour, minute = divmod(value, 60)
        if not 4 <= hour <= 23:
            raise ValueError('Generated time outside 04:00-23:59')
        h12 = hour % 12 or 12
        option = style % 3
        if option == 0:
            return f'{hour:02d}:{minute:02d}'
        if lang == 'en':
            suffix = 'AM' if hour < 12 else 'PM'
            return f'{h12}:{minute:02d} {suffix if option == 1 else suffix.lower()}'
        text = f'{hi_period(hour)} {h12}:{minute:02d}'
        return text if option == 1 else (text + ' बजे').translate(TO_DEV)

    def parse(self, text, lang):
        text = ascii_digits(text.strip()).replace(' बजे', '')
        if not text:
            return None
        match = re.fullmatch(r'(\d{2}):(\d{2})', text)
        if match:
            return int(match[1]) * 60 + int(match[2])
        match = re.fullmatch(r'(\d{1,2}):(\d{2}) ([AaPp][Mm])', text)
        if match:
            hour = int(match[1]) % 12 + (12 if match[3].lower() == 'pm' else 0)
            return hour * 60 + int(match[2])
        word, clock = text.split(' ')
        hour, minute = (int(part) for part in clock.split(':'))
        if word == 'सुबह':
            hour %= 12
        elif not (word == 'दोपहर' and hour == 12):
            hour += 12
        return hour * 60 + minute


class DateTime(Kind):
    def render(self, value, lang, style):
        if value is None:
            return ''
        minutes = value.hour * 60 + value.minute
        return Date().render(value.date(), lang, style) + ' ' + Time().render(minutes, lang, style // 4)

    def parse(self, text, lang):
        text = text.strip()
        if not text:
            return None
        pieces = text.split(' ')
        # Date forms have one or three space-separated parts; the time form one to three.
        for split in (1, 3):
            try:
                day = Date().parse(' '.join(pieces[:split]), lang)
                minutes = Time().parse(' '.join(pieces[split:]), lang)
                return datetime(day.year, day.month, day.day) + timedelta(minutes=minutes)
            except (ValueError, AttributeError, IndexError, TypeError, KeyError):
                continue
        raise ValueError(f'Unparsed datetime {text!r}')


class Code(Kind):
    """Enumerated values with per-language surface variants."""

    def __init__(self, table):
        self.table = table
        self.reverse = {}
        for code, (en, hi) in table.items():
            for lang, forms in (('en', en), ('hi', hi)):
                for form in forms:
                    key = (lang, form.strip().casefold())
                    if self.reverse.get(key, code) != code:
                        raise ValueError(f'Ambiguous code form {form}')
                    self.reverse[key] = code

    def render(self, value, lang, style):
        if value is None:
            return ''
        forms = self.table[value][0 if lang == 'en' else 1]
        return pad(forms[style % len(forms)], style)

    def parse(self, text, lang):
        text = text.strip()
        return self.reverse[(lang, text.casefold())] if text else None


YES_NO = Code({True: (['yes', 'Yes', 'Y'], ['हाँ', 'हां']), False: (['no', 'No', 'N'], ['नहीं', 'ना'])})


class Qty(Kind):
    """(Decimal amount, unit code) with unit labels per language."""

    def __init__(self, units):
        self.units = units
        self.reverse = {}
        for code, (en, hi) in units.items():
            for lang, forms in (('en', en), ('hi', hi)):
                for form in forms:
                    self.reverse[(lang, form)] = code

    def render(self, value, lang, style):
        if value is None:
            return ''
        amount, unit = value
        forms = self.units[unit][0 if lang == 'en' else 1]
        number = plain(amount)
        if lang == 'hi' and style % 3 == 0:
            number = number.translate(TO_DEV)
        return f'{number} {forms[style % len(forms)]}'

    def parse(self, text, lang):
        text = text.strip()
        if not text:
            return None
        number, label = text.split(' ', 1)
        return D(ascii_digits(number)), self.reverse[(lang, label)]


# ------------------------------------------------------------------- tables

class Table:
    def __init__(self, name, columns, rows, seed):
        self.name = name
        self.columns = columns  # [(english header, hindi header, kind)]
        self.rows = rows
        rng = random.Random(f'{seed}:{name}')
        self.styles = [[rng.randrange(10 ** 6) for _ in columns] for _ in rows]

    def render(self, lang):
        header = [column[0 if lang == 'en' else 1] for column in self.columns]
        body = [[kind.render(value, lang, style) for (_, _, kind), value, style in
                 zip(self.columns, row, styles)] for row, styles in zip(self.rows, self.styles)]
        return header, body

    def check_round_trip(self):
        for lang in ('en', 'hi'):
            _, body = self.render(lang)
            for row, text_row in zip(self.rows, body):
                for (name, _, kind), value, text in zip(self.columns, row, text_row):
                    if isinstance(kind, Text):
                        continue
                    if '\n' in text or '"' in text:
                        raise ValueError(f'{self.name}.{name} contains a newline or quote')
                    parsed = kind.parse(text, lang)
                    if parsed != value:
                        raise ValueError(f'{self.name}.{name} {lang}: {text!r} parsed as {parsed!r}, expected {value!r}')


def materialize(spec):
    """Turn an authored task into the frozen JSON form read by phase2.suite."""
    files = []
    for table in spec['tables']:
        table.check_round_trip()
        rendered = {lang: table.render(lang) for lang in ('en', 'hi')}
        files.append({'name': f'in/{table.name}.csv',
                      'headers': {lang: rendered[lang][0] for lang in rendered},
                      'rows': {lang: rendered[lang][1] for lang in rendered}})
    notice = {lang: '\n\n'.join(part for part in (spec['notice'][lang].strip(), FORMAT_NOTE[lang],
                                                    glossary(spec, lang)) if part) for lang in ('en', 'hi')}
    return {key: spec[key] for key in ('id', 'title', 'goals', 'output', 'key_columns',
                                        'numeric', 'answer', 'forbidden_keys')} | {'notice': notice, 'files': files}


GLOSSARY_TEXT = {
    'en': ('Value glossary: in the input files, each line below lists different spellings of the same value.',
           'Output values: in out/result.csv, write {column} as one of these codes: {codes}.'),
    'hi': ('मान सूची: इनपुट फ़ाइलों में नीचे की हर पंक्ति एक ही मान के अलग-अलग रूप बताती है।',
           'आउटपुट मान: out/result.csv में {column} के लिए इनमें से कोई एक कोड लिखें: {codes}।'),
}


def glossary(spec, lang):
    """Spell out every coded value that the workspace writes in more than one form (suite v2.1).

    v2 rendered some coded values in several surface forms (for example WHEAT and Wheat HD-2967,
    or लघु किसान and छोटा किसान) without saying they were the same value, and did not say which
    form an output column needs. Both let a literal reading of the notice disagree with the key.
    """
    side = 0 if lang == 'en' else 1
    seen = {}
    code_columns = []
    for table in spec['tables']:
        for index, (en, hi, kind) in enumerate(table.columns):
            if not isinstance(kind, Code):
                continue
            code_columns.append(kind)
            entries = []
            for code in kind.table:
                if not any(row[index] == code for row in table.rows):
                    continue
                forms = []
                for form in kind.table[code][side]:
                    if form.strip().casefold() not in {f.casefold() for f in forms}:
                        forms.append(form.strip())
                if len(forms) > 1:
                    entries.append(' = '.join(forms))
            if entries:
                seen.setdefault((en if lang == 'en' else hi, tuple(entries)), []).append(f'{table.name}.csv')
    output_lines = []
    for position, column in enumerate(spec['output']):
        values = {row[position] for row in spec['answer']} - {''}
        if not values or column in spec['numeric']:
            continue
        for kind in code_columns:
            codes = {str(code): code for code in kind.table}
            if values <= set(codes):
                labels = []
                for name, code in codes.items():
                    form = kind.table[code][side][-1].strip()
                    labels.append(name if form == name else f'{name} ({form})')
                output_lines.append(GLOSSARY_TEXT[lang][1].format(column=column, codes=', '.join(labels)))
                break
    lines = [f"- {', '.join(files)}, {column}: " + '; '.join(entries) for (column, entries), files in seen.items()]
    parts = [GLOSSARY_TEXT[lang][0] + '\n' + '\n'.join(lines)] if lines else []
    return '\n'.join(parts + output_lines)


def task(**fields):
    fields.setdefault('key_columns', 1)
    fields.setdefault('numeric', [])
    fields.setdefault('forbidden_keys', [])
    return fields


# Format notes appended to every notice. They describe every format the generator emits.
FORMAT_NOTE = {
    'en': ('Format notes: dates appear as YYYY-MM-DD, as DD/MM/YYYY (day first), or with a month name. '
           'Times appear in 24-hour form or with AM/PM. Amounts may include ₹ or Rs, commas '
           '(including Indian lakh grouping such as 1,25,000) or a .00 suffix. Codes and IDs may carry '
           'stray spaces or different letter case. All values in a file are authoritative as written.'),
    'hi': ('प्रारूप संबंधी नोट: तारीखें YYYY-MM-DD, DD/MM/YYYY (पहले दिन) या महीने के नाम के साथ लिखी हो सकती हैं। '
           'अंक देवनागरी (०-९) या अंग्रेज़ी अंकों में हो सकते हैं। समय 24-घंटे के रूप में या सुबह (4-11 बजे), '
           'दोपहर (12-3 बजे), शाम (4-7 बजे) और रात (8-11 बजे) के साथ 12-घंटे के रूप में लिखा हो सकता है। '
           'राशि में ₹, रुपये या रु., कॉमा (जैसे 1,25,000) या .00 हो सकता है। कोड और आईडी में अतिरिक्त '
           'स्पेस या अलग अक्षर-रूप हो सकते हैं। फ़ाइलों में लिखे सभी मान प्रामाणिक हैं।'),
}
