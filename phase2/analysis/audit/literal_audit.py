"""For each failing run, test whether reading an undocumented surface variant literally explains the output."""
import importlib, json, csv, os, re, itertools, copy
from phase2.authoring.core import Code
from phase2.authoring.build import DOMAINS
from phase2.grader import grade_rows
SCR = os.environ['SCR']
runs = json.load(open(SCR + '/analysis.json', encoding='utf-8'))['runs']
def norm(s): return re.sub(r'\s+', ' ', s.strip().casefold())
makers = {}
for dom in DOMAINS:
    mod = importlib.import_module(f'phase2.authoring.{dom}')
    for fn in mod.TASKS:
        makers[fn()['id']] = fn
def variants(tid, lang):
    spec = makers[tid](); note = norm(spec['notice'][lang])
    out = []
    for ti, t in enumerate(spec['tables']):
        for ci, (en, hi, kind) in enumerate(t.columns):
            if not isinstance(kind, Code): continue
            for code, (ef, hf) in kind.table.items():
                forms = ef if lang == 'en' else hf
                for form in set(f.strip() for f in forms):
                    if norm(form) == norm(str(code)) or norm(form) in note: continue
                    out.append((ti, ci, code, form, f'{t.name}.{en}={form!r}'))
    return out
def solve_literal(tid, lang, chosen, abl=frozenset()):
    spec = makers[tid]()
    for ti, ci, code, form, _ in chosen:
        t = spec['tables'][ti]; _, body = t.render(lang)
        for row, b in zip(t.rows, body):
            if b[ci].strip() == form and row[ci] == code: row[ci] = f'{code}~{form}'
    return spec, spec['solve'](abl)
results = []
for x in runs:
    if x['full'] or x['retry']: continue
    p = f"phase2/results/final/runs/{x['id']}/artifacts/out/result.csv"
    if not os.path.exists(p): continue
    rows = list(csv.reader(open(p, encoding='utf-8-sig')))
    if not rows: continue
    h, b = rows[0], [r for r in rows[1:] if r]
    spec = makers[x['task']]()
    C = lambda ans: {'columns': spec['output'], 'expected': ans, 'key_columns': spec['key_columns'], 'numeric': spec['numeric'], 'forbidden_keys': spec['forbidden_keys']}
    base = grade_rows(C(spec['answer']), h, b)['score']
    V = variants(x['task'], x['ws'])
    best = (base, 'official')
    tried = [[v] for v in V] + ([V] if len(V) > 1 else [])
    for ch in tried:
        try:
            _, ans = solve_literal(x['task'], x['ws'], ch)
        except Exception:
            continue
        s = grade_rows(C(ans), h, b)['score']
        if s > best[0] + 1e-6: best = (s, ' & '.join(v[4] for v in ch) if len(ch) < 4 else f'all {len(ch)} undocumented variants')
    results.append(dict(task=x['task'], instr=x['instr'], ws=x['ws'], model=x['model'], status=x['status'], official=round(base, 2), literal_best=round(best[0], 2), explained_by=best[1]))
    print(results[-1], flush=True)
json.dump(results, open(SCR + '/literal_audit.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
