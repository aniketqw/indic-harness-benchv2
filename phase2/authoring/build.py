"""Materialize the v2 suite and measure how much each rule matters.

Run from the repository root:  py -B -X utf8 -m phase2.authoring.build
"""

import importlib
import json
import sys

from ..grader import grade_rows
from ..suite import HERE, csv_bytes

DOMAINS = ['finance', 'schools', 'agriculture', 'localization', 'municipal', 'logistics', 'clinic', 'archives']


def contract(spec):
    return {'columns': spec['output'], 'expected': spec['answer'], 'key_columns': spec['key_columns'],
            'numeric': spec['numeric'], 'forbidden_keys': spec['forbidden_keys']}


def check(spec):
    keys = [tuple(row[:spec['key_columns']]) for row in spec['answer']]
    if len(keys) != len(set(keys)) or any('' in key for key in keys):
        raise ValueError(f"{spec['id']}: answer keys must be unique and non-empty")
    if any(len(row) != len(spec['output']) for row in spec['answer']):
        raise ValueError(f"{spec['id']}: answer width")
    if spec['solve']() != spec['answer']:
        raise ValueError(f"{spec['id']}: solver is not deterministic")
    report = []
    weak = []
    for name in spec['ablations']:
        result = grade_rows(contract(spec), spec['output'], spec['solve'](frozenset({name})))
        report.append({'rule_ignored': name, 'score': result['score']})
        if result['score'] >= 100:
            weak.append(name)
    if weak:
        raise ValueError(f"{spec['id']}: these rule ablations do not change the answer: {weak}")
    return report


def main(selected=None):
    summary = {}
    for domain in DOMAINS:
        if selected and domain not in selected:
            continue
        module = importlib.import_module(f'phase2.authoring.{domain}')
        frozen = []
        for build in module.TASKS:
            spec = build()
            from .core import materialize
            item = materialize(spec)
            ablations = check(spec)
            sizes = {lang: sum(len(csv_bytes(f['headers'][lang], f['rows'][lang])) for f in item['files'])
                     for lang in ('en', 'hi')}
            rows = {f['name']: len(f['rows']['en']) for f in item['files']}
            summary[spec['id']] = {'domain': domain, 'title': spec['title'], 'input_rows': rows,
                                   'output_rows': len(spec['answer']), 'scored_fields':
                                   len(spec['answer']) * (len(spec['output']) - spec['key_columns']),
                                   'input_bytes': sizes, 'ablations': ablations,
                                   'mean_ablation_score': round(sum(a['score'] for a in ablations) / len(ablations), 1),
                                   'max_ablation_score': max(a['score'] for a in ablations)}
            frozen.append(item)
            print(f"{spec['id']:26} out={len(spec['answer']):3} bytes(en/hi)={sizes['en']}/{sizes['hi']} "
                  + ' '.join(f"{a['rule_ignored']}={a['score']:.0f}" for a in ablations), flush=True)
        (HERE / 'tasks' / f'{domain}.json').write_text(
            json.dumps(frozen, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    if not selected:
        (HERE / 'difficulty.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1) + '\n',
                                              encoding='utf-8')
    return summary


if __name__ == '__main__':
    main(sys.argv[1:] or None)
