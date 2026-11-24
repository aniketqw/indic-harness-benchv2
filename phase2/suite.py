"""Trusted task catalog and localized workspace materialization (suite v2).

Task sources are frozen JSON in phase2/tasks/, generated offline by phase2.authoring.build.
The previous 24-task suite is preserved unchanged in phase2/archive/v1-easy/.
"""

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
# v2.1: identical data, rules and answers to v2; every notice adds a value glossary (see DESIGN-v2.md).
SUITE_VERSION = 'v2.1'
PROMPT_LANGS = ('en', 'hi', 'hinglish')
FILE_LANGS = ('en', 'hi')
MODELS = ('glm', 'nemotron')
TASKS_PER_DOMAIN = 2
DOMAIN_COUNT = 8
PILOT = {
    '01-upi-settlement', '03-bus-roster', '05-grower-payout', '07-ui-strings',
    '09-water-schedule', '11-parcel-dispatch', '13-appointment-rebooking', '15-catalogue-merge',
}

INSTRUCTIONS = {
    'en': ('Read every input file in `in/`: {files}. Follow the rules in `in/notice.txt`. Save the result as a '
           'UTF-8 CSV at `out/result.csv` with exactly these columns, in this order: {columns}. Write dates as '
           'YYYY-MM-DD, times as 24-hour HH:MM, and numbers as plain digits without currency symbols or thousands '
           'separators. Use the output codes given in the notice. Leave a field blank only where the notice says so, '
           'and do not change the input files.'),
    'hi': ('`in/` की हर इनपुट फ़ाइल पढ़ें: {files}। `in/notice.txt` में दिए नियमों का पालन करें। नतीजा UTF-8 CSV में '
           '`out/result.csv` पर सहेजें, जिसमें ठीक यही कॉलम इसी क्रम में हों: {columns}। तारीखें YYYY-MM-DD रूप में, '
           'समय 24-घंटे के HH:MM रूप में, और संख्याएँ बिना मुद्रा चिह्न या हज़ार के कॉमा के सादे अंग्रेज़ी अंकों में लिखें। '
           'नोटिस में दिए आउटपुट कोड इस्तेमाल करें। कोई फ़ील्ड सिर्फ़ वहीं खाली छोड़ें जहाँ नोटिस में कहा गया है, और '
           'इनपुट फ़ाइलों में बदलाव न करें।'),
    'hinglish': ('`in/` ki har input file padho: {files}. `in/notice.txt` ke rules follow karo. Result ko UTF-8 CSV '
                 'mein `out/result.csv` par save karo, exactly in columns ke saath, isi order mein: {columns}. Dates '
                 'YYYY-MM-DD mein, time 24-hour HH:MM mein, aur numbers plain digits mein likho, bina currency symbol '
                 'ya thousands comma ke. Notice mein diye output codes use karo. Koi field sirf wahin blank chhodo '
                 'jahan notice kehta hai, aur input files ko change mat karo.'),
}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def csv_bytes(header, rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def check_table(header, rows):
    if not header or '' in header or len(header) != len(set(header)):
        raise ValueError('Invalid table header')
    if not rows or any(len(row) != len(header) for row in rows):
        raise ValueError('Invalid table dimensions')


def catalog():
    tasks = {}
    domains = sorted((HERE / 'tasks').glob('*.json'))
    if len(domains) != DOMAIN_COUNT:
        raise ValueError(f'Expected {DOMAIN_COUNT} task domains')
    for path in domains:
        entries = read_json(path)
        if len(entries) != TASKS_PER_DOMAIN:
            raise ValueError(f'{path.stem} must have {TASKS_PER_DOMAIN} tasks')
        for task in entries:
            task_id = task['id']
            if task_id in tasks or not re.fullmatch(r'\d{2}-[a-z0-9-]+', task_id):
                raise ValueError(f'Invalid or repeated task ID: {task_id}')
            if set(task['goals']) != set(PROMPT_LANGS) or set(task['notice']) != set(FILE_LANGS):
                raise ValueError(f'Missing language variant for {task_id}')
            if not all(task['goals'].values()) or not all(task['notice'].values()):
                raise ValueError(f'Empty language variant for {task_id}')
            if not re.search(r'[ऀ-ॿ]', task['goals']['hi'] + task['notice']['hi']):
                raise ValueError(f'Missing Devanagari for {task_id}')
            if re.search(r'[ऀ-ॿ]', task['goals']['hinglish']):
                raise ValueError(f'Hinglish instruction must use Roman script: {task_id}')
            names = [item['name'] for item in task['files']]
            if len(names) != len(set(names)) or not all(re.fullmatch(r'in/[a-z_]+\.csv', n) for n in names):
                raise ValueError(f'Invalid input file names for {task_id}')
            for item in task['files']:
                for lang in FILE_LANGS:
                    check_table(item['headers'][lang], item['rows'][lang])
                if len(item['rows']['en']) != len(item['rows']['hi']):
                    raise ValueError(f'Unmatched row count in {task_id} {item["name"]}')
            check_table(task['output'], task['answer'])
            keys = [tuple(row[:task['key_columns']]) for row in task['answer']]
            if any('' in key for key in keys) or len(keys) != len(set(keys)):
                raise ValueError(f'Expected rows need unique non-empty keys: {task_id}')
            if len(task['output']) <= task['key_columns'] or not set(task['numeric']) <= set(task['output']):
                raise ValueError(f'Invalid output contract: {task_id}')
            tasks[task_id] = {**task, 'domain': path.stem}
    return dict(sorted(tasks.items()))


def domain_order(tasks):
    groups = {}
    for task_id, task in tasks.items():
        groups.setdefault(task['domain'], []).append(task_id)
    return [task_id for group in zip(*groups.values(), strict=True) for task_id in group]


def file_names(task):
    return [item['name'] for item in task['files']] + ['in/notice.txt']


def prompt(task, language):
    files = ', '.join(f'`{name}`' for name in file_names(task))
    return task['goals'][language] + '\n\n' + INSTRUCTIONS[language].format(
        files=files, columns=', '.join(task['output']))


def inputs(task, language):
    files = {item['name']: csv_bytes(item['headers'][language], item['rows'][language]) for item in task['files']}
    files['in/notice.txt'] = (task['notice'][language] + '\n').encode('utf-8')
    return files


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
        'key_columns': task['key_columns'],
        'numeric': task['numeric'],
        'input_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        'forbidden_keys': task['forbidden_keys'],
    }


def review(destination, tasks):
    destination.mkdir(parents=True, exist_ok=True)
    plan = ['# Phase-two task review (suite v2)', '', 'Each task folder contains both workspaces and all prompts.', '']
    for task_id, task in tasks.items():
        plan.append(f"- [{task['title']}]({task_id}/README.md) ({task['domain']})")
        folder = destination / task_id
        folder.mkdir(exist_ok=True)
        notes = [f"# {task['title']}", '', f"Domain {task['domain']}", '']
        for lang in PROMPT_LANGS:
            (folder / f'prompt-{lang}.txt').write_text(prompt(task, lang) + '\n', encoding='utf-8')
            notes.append(f'- [Prompt {lang}](prompt-{lang}.txt)')
        for lang in FILE_LANGS:
            links = []
            for name, contents in inputs(task, lang).items():
                path = folder / lang / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
                links.append(f'[{Path(name).name}]({lang}/{name})')
            notes.append(f'- {lang} workspace: ' + ', '.join(links))
        (folder / 'expected.csv').write_bytes(csv_bytes(task['output'], task['answer']))
        notes.append('- [Expected result](expected.csv)')
        (folder / 'README.md').write_text('\n'.join(notes) + '\n', encoding='utf-8')
    (destination / 'README.md').write_text('\n'.join(plan) + '\n', encoding='utf-8')
