"""Paper tables for a finished phase-two campaign. Read-only; never changes campaign records.

Infrastructure failures are replaced by their single recorded recovery attempt (if any), and both
records stay on disk. Run from the repository root:

    py -B -X utf8 -m phase2.analysis.summarize final-v21 [--compare final]

Writes <campaign>/analysis/{conditions.csv,summary.json} and prints the tables.
"""

import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / 'phase2/results'
# USD per million tokens (input, output), same table as phase2/dashboard. Approximate.
RATES = {'glm': (0.15, 0.50), 'nemotron': (0.015, 0.60)}


def read_runs(path):
    with sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute('SELECT * FROM runs ORDER BY rowid')]


OUTPUT_BUDGET = 65536


def outcome(status, result, output_tokens=0):
    """One label per condition. Only full_completion counts as success.

    The relay can end the final reply at the attempt output budget with a normal stop, so a run that
    used the whole output budget is labelled as budget-limited whatever the agent's exit status.
    """
    if status == 'infrastructure_failed':
        return 'infrastructure_failed'
    if result.get('full_completion') and status == 'completed':
        return 'full'
    reason = result.get('reason')
    budget = status == 'budget_exhausted' or output_tokens >= OUTPUT_BUDGET
    if reason == 'output_missing_or_oversized':
        return 'no_output_budget' if budget else 'no_output'
    if reason in ('incorrect_header', 'incorrect_row_width', 'duplicate_output_key', 'invalid_csv_or_encoding',
                  'restricted_row_in_output'):
        return 'format_error'
    if budget:
        return 'correct_over_budget' if (result.get('score') or 0) == 100 else 'partial_budget'
    return 'partial'


def conditions(campaign):
    folder = RESULTS / campaign
    retries_path = folder / 'infrastructure_retries.json'
    retries = {item['source_run_id']: item for item in json.loads(retries_path.read_text(encoding='utf-8'))} \
        if retries_path.exists() else {}
    rows = []
    for run in read_runs(folder / 'journal.sqlite3'):
        source = run
        recovered = run['id'] in retries
        if recovered:
            source = read_runs(ROOT / retries[run['id']]['journal'])[0]
        result = json.loads(source['result']) if source['result'] else {}
        instruction, files, model = run['language'].split('.')
        label = outcome(source['status'], result, source['output_actual'] or 0)
        rows.append({
            'task': run['task'], 'domain': result.get('domain', ''), 'instruction_language': instruction,
            'file_language': files, 'model': model, 'status': source['status'],
            'outcome': label, 'full_completion': int(label == 'full'),
            # Primary outcome: the saved file is fully correct when the attempt ends, however it ended.
            'correct_output': int(source['status'] != 'infrastructure_failed' and (result.get('score') or 0) == 100),
            'score': result.get('score', 0.0) or 0.0, 'requests': source['requests'] or 0,
            'input_tokens': source['input_actual'] or 0, 'output_tokens': source['output_actual'] or 0,
            'elapsed_sec': result.get('elapsed_sec') or 0, 'run_id': source['id'],
            'recovered_from': run['id'] if recovered else '',
        })
    return rows


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (round(100 * (centre - half), 1), round(100 * (centre + half), 1))


def group(rows, *keys):
    table = defaultdict(list)
    for row in rows:
        table[tuple(row[k] for k in keys)].append(row)
    out = []
    for key, items in sorted(table.items()):
        n = len(items)
        k = sum(r['correct_output'] for r in items)
        strict = sum(r['full_completion'] for r in items)
        counts = Counter(r['outcome'] for r in items)
        out.append({**dict(zip(keys, key)), 'n': n, 'correct': k, 'correct_pct': round(100 * k / n, 1),
                    'correct_ci95': wilson(k, n), 'within_budget': strict,
                    'within_budget_pct': round(100 * strict / n, 1), 'mean_score': round(sum(r['score'] for r in items) / n, 1),
                    'outcomes': dict(counts)})
    return out


def paired(rows, factor, base, other):
    """Discordant pairs for matched conditions that differ only in one factor."""
    keys = [k for k in ('task', 'instruction_language', 'file_language', 'model') if k != factor]
    index = {tuple(r[k] for k in keys) + (r[factor],): r['correct_output'] for r in rows}
    counts = Counter()
    for key, value in index.items():
        if key[-1] == base and key[:-1] + (other,) in index:
            counts[(value, index[key[:-1] + (other,)])] += 1
    return {'factor': factor, 'base': base, 'other': other, 'pairs': sum(counts.values()),
            'both_correct': counts[(1, 1)], 'neither': counts[(0, 0)],
            f'only_{base}': counts[(1, 0)], f'only_{other}': counts[(0, 1)]}


def cost(rows):
    total = 0.0
    per = {}
    for model, (rate_in, rate_out) in RATES.items():
        items = [r for r in rows if r['model'] == model]
        value = sum(r['input_tokens'] for r in items) / 1e6 * rate_in + sum(r['output_tokens'] for r in items) / 1e6 * rate_out
        per[model] = round(value, 2)
        total += value
    return {'per_model_usd': per, 'total_usd': round(total, 2)}


def summary(rows):
    return {
        'conditions': len(rows),
        'overall': group([{**r, 'all': 'all'} for r in rows], 'all')[0],
        'by_model': group(rows, 'model'),
        'by_instruction': group(rows, 'instruction_language'),
        'by_workspace': group(rows, 'file_language'),
        'by_model_instruction': group(rows, 'model', 'instruction_language'),
        'by_model_workspace': group(rows, 'model', 'file_language'),
        'by_instruction_workspace': group(rows, 'instruction_language', 'file_language'),
        'by_task': group(rows, 'task'),
        'by_task_model': group(rows, 'task', 'model'),
        'paired': [paired(rows, 'file_language', 'en', 'hi'),
                   paired(rows, 'instruction_language', 'en', 'hi'),
                   paired(rows, 'instruction_language', 'en', 'hinglish'),
                   paired(rows, 'model', 'glm', 'nemotron')],
        'outcomes': dict(Counter(r['outcome'] for r in rows)),
        'outcomes_by_model': {m: dict(Counter(r['outcome'] for r in rows if r['model'] == m)) for m in RATES},
        'tokens': {m: {'input': sum(r['input_tokens'] for r in rows if r['model'] == m),
                       'output': sum(r['output_tokens'] for r in rows if r['model'] == m)} for m in RATES},
        'tokens_by_workspace': {f'{m}.{w}': {
            'mean_input': round(sum(r['input_tokens'] for r in rows if r['model'] == m and r['file_language'] == w)
                                / max(1, sum(1 for r in rows if r['model'] == m and r['file_language'] == w))),
            'mean_output': round(sum(r['output_tokens'] for r in rows if r['model'] == m and r['file_language'] == w)
                                 / max(1, sum(1 for r in rows if r['model'] == m and r['file_language'] == w)))}
            for m in RATES for w in ('en', 'hi')},
        'cost': cost(rows),
        'recovered_conditions': [r['recovered_from'] for r in rows if r['recovered_from']],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('campaign')
    parser.add_argument('--compare')
    args = parser.parse_args()
    rows = conditions(args.campaign)
    out = RESULTS / args.campaign / 'analysis'
    out.mkdir(exist_ok=True)
    with (out / 'conditions.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    data = summary(rows)
    if args.compare:
        before = conditions(args.compare)
        data['compare'] = {'campaign': args.compare, 'by_task': group(before, 'task'),
                           'by_model': group(before, 'model'), 'outcomes': dict(Counter(r['outcome'] for r in before))}
    (out / 'summary.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k: data[k] for k in ('conditions', 'overall', 'by_model', 'by_instruction', 'by_workspace',
                                            'outcomes', 'paired', 'cost')}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
