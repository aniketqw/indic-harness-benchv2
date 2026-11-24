
"""Trusted task catalog and localized workspace materialization."""

import csv
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LEGACY_CONFIG = ROOT / 'campaigns/shared/extension-to50-20261002/config'
PROMPT_LANGS = ('en', 'hi', 'hinglish')
FILE_LANGS = ('en', 'hi')
MODELS = ('oss', 'nemotron')
PILOT = {
    '01-upi-close', '04-bus-roster', '07-grower-payout', '10-ui-placeholders',
    '13-water-register', '16-depot-cutoff', '19-appointment-moves', '22-catalogue-merge',
}

INSTRUCTIONS = {
    'en': ('Read `in/records.csv`, `in/amendments.csv`, and `in/notice.txt`. Save the result as UTF-8 CSV at '
           '`out/result.csv` with these exact column names: {columns}. Use the values or codes '
           'specified in the files. Leave missing values blank and keep the input files intact.'),
    'hi': ('`in/records.csv`, `in/amendments.csv` और `in/notice.txt` पढ़ें। नतीजा UTF-8 CSV में '
           '`out/result.csv` पर सहेजें। कॉलम के नाम ठीक ये हों: {columns}। फ़ाइलों में बताए '
           'गए मान या कोड इस्तेमाल करें। गायब मान खाली छोड़ें और इनपुट फ़ाइलों में बदलाव न करें।'),
    'hinglish': ('`in/records.csv`, `in/amendments.csv` aur `in/notice.txt` padho. Result ko UTF-8 CSV mein '
                 '`out/result.csv` par save karo. Column names exactly ye rakho: {columns}. '
                 'Files mein diye gaye values ya codes use karo. Missing values blank chhodo '
                 'aur input files ko change mat karo.'),
}
AMENDMENT_GUIDE = {
    'en': ('These are independent batches. IDs can recur across batches. The amendment register contains '
           'complete replacement rows, keyed by batch and source_row, and takes precedence over the '
           'original records. Apply the rules below only after making those replacements. Keep the batch '
           'code on each output row. Where source order matters, use source_row order within the batch.'),
    'hi': ('हर बैच अलग है और अलग बैचों में एक ही आईडी फिर आ सकती है। संशोधन रजिस्टर में पूरी बदली हुई '
           'पंक्तियाँ हैं। batch और source_row दोनों मिलाकर मूल पंक्ति की जगह संशोधित पंक्ति लें। फिर नीचे '
           'के नियम लागू करें। आउटपुट की हर पंक्ति में बैच कोड रखें। जहाँ क्रम मायने रखता है, उस बैच के '
           'अंदर source_row के क्रम में पंक्तियाँ लें।'),
}
BATCHES = ((), (0,), (1,), (0, 1), (1,), (0,))


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def csv_bytes(header, rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def catalog():
    tasks = {}
    variants = read_json(HERE / 'variants.json')
    domains = sorted((HERE / 'tasks').glob('*.json'))
    if len(domains) != 8:
        raise ValueError('Expected eight task domains')
    for path in domains:
        entries = read_json(path)
        if len(entries) != 3:
            raise ValueError(f'{path.stem} must have three tasks')
        for task in entries:
            task_id = task['id']
            if task_id in tasks or not re.fullmatch(r'\d{2}-[a-z0-9-]+', task_id):
                raise ValueError(f'Invalid or repeated task ID: {task_id}')
            if set(task['goals']) != set(PROMPT_LANGS) or set(task['notice']) != set(FILE_LANGS):
                raise ValueError(f'Missing language variant for {task_id}')
            if not all(task['goals'].values()) or not all(task['notice'].values()):
                raise ValueError(f'Empty language variant for {task_id}')
            if not re.search(r'[\u0900-\u097f]', task['goals']['hi'] + task['notice']['hi']):
                raise ValueError(f'Missing Devanagari for {task_id}')
            if re.search(r'[\u0900-\u097f]', task['goals']['hinglish']):
                raise ValueError(f'Hinglish instruction must use Roman script: {task_id}')
            for lang in FILE_LANGS:
                rows = task.get('hi_records', task['records']) if lang == 'hi' else task['records']
                check_table(task['headers'][lang], rows)
                if len(rows) != len(task['records']):
                    raise ValueError(f'Unmatched record count for {task_id}')
            check_table(task['output'], task['answer'])
            if len(task['output']) < 2:
                raise ValueError(f'Output requires an ID and at least one scored field: {task_id}')
            keys = [row[0] for row in task['answer']]
            if '' in keys or len(keys) != len(set(keys)):
                raise ValueError(f'Expected rows need unique first-column IDs: {task_id}')
            tasks[task_id] = expand({**task, 'domain': path.stem}, variants[task_id])
    if set(variants) != set(tasks):
        raise ValueError('Amendment catalog must contain exactly the suite tasks')
    return dict(sorted(tasks.items()))


def expand(task, variants):
    """Construct independent batches with an authoritative, separate amendment feed."""
    datasets = {lang: {'records': [], 'amendments': []} for lang in FILE_LANGS}
    answer = []
    for number, cases in enumerate(BATCHES, 1):
        batch = f'B{number:02d}'
        expected = {row[0]: row.copy() for row in task['answer']}
        for variant in cases:
            for key, column, value in variants[2 * variant + 1]:
                expected[key][column] = value
        answer.extend([batch, *row] for row in expected.values())
        for lang, data in datasets.items():
            original = task.get('hi_records', task['records']) if lang == 'hi' else task['records']
            revised = {}
            for variant in cases:
                for row, column, en, *localized in variants[2 * variant]:
                    if localized and lang == 'hi':
                        value = localized[0]
                    else:
                        value = en
                    revised.setdefault(row, original[row].copy())[column] = value
            data['records'].extend([batch, f'{row + 1:03d}', *values] for row, values in enumerate(original))
            data['amendments'].extend([batch, f'{row + 1:03d}', *values] for row, values in sorted(revised.items()))
    # The feed arrives newest-batch first, unlike the records export.
    for data in datasets.values():
        data['amendments'].reverse()
    return {**task, 'datasets': datasets, 'output': ['batch', *task['output']], 'answer': answer}


def domain_order(tasks):
    groups = {}
    for task_id, task in tasks.items():
        groups.setdefault(task['domain'], []).append(task_id)
    return [task_id for group in zip(*groups.values(), strict=True) for task_id in group]


def check_table(header, rows):
    if not header or '' in header or len(header) != len(set(header)):
        raise ValueError('Invalid table header')
    if not rows or any(len(row) != len(header) for row in rows):
        raise ValueError('Invalid table dimensions')


def prompt(task, language):
    return task['goals'][language] + '\n\n' + INSTRUCTIONS[language].format(
        columns=', '.join(task['output']))


def inputs(task, language):
    header = ['batch', 'source_row', *task['headers'][language]]
    data = task['datasets'][language]
    return {
        'in/records.csv': csv_bytes(header, data['records']),
        'in/amendments.csv': csv_bytes(header, data['amendments']),
        'in/notice.txt': (AMENDMENT_GUIDE[language] + '\n\n' + task['notice'][language] + '\n').encode('utf-8'),
    }


def archive(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as bundle:
        for folder in ('in', 'out'):
            item = tarfile.TarInfo(folder)
            item.type = tarfile.DIRTYPE
            bundle.addfile(item)
        for name, content in files.items():
            item = tarfile.TarInfo(name)
            item.size = len(content)
            bundle.addfile(item, io.BytesIO(content))
    return output.getvalue()


def rubric(task, files):
    return {
        'columns': task['output'],
        'expected': task['answer'],
        'key_columns': 2,
        'input_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        'forbidden_keys': [[f'B{index:02d}', key] for key in task.get('forbidden_ids', [])
                           for index in range(1, len(BATCHES) + 1)],
    }


def review(destination, tasks):
    destination.mkdir(parents=True, exist_ok=True)
    plan = ['# Phase-two task review', '', 'Each task folder contains both workspaces and all prompts.', '']
    for task_id, task in tasks.items():
        plan.append(f"- [{task['title']}]({task_id}/README.md) ({task['domain']})")
        folder = destination / task_id
        folder.mkdir(exist_ok=True)
        notes = [f"# {task['title']}", '', f"Domain {task['domain']}", '']
        for lang in PROMPT_LANGS:
            (folder / f'prompt-{lang}.txt').write_text(prompt(task, lang) + '\n', encoding='utf-8')
            notes.append(f'- [Prompt {lang}](prompt-{lang}.txt)')
        for lang in FILE_LANGS:
            for name, contents in inputs(task, lang).items():
                path = folder / lang / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            notes.append(f'- [{lang} records]({lang}/in/records.csv), '
                         f'[{lang} amendments]({lang}/in/amendments.csv), [{lang} notice]({lang}/in/notice.txt)')
        (folder / 'expected.csv').write_bytes(csv_bytes(task['output'], task['answer']))
        notes.append('- [Expected result](expected.csv)')
        (folder / 'README.md').write_text('\n'.join(notes) + '\n', encoding='utf-8')
    (destination / 'README.md').write_text('\n'.join(plan) + '\n', encoding='utf-8')
