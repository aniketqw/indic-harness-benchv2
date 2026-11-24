import importlib, json, csv, os, sqlite3, sys
from collections import defaultdict
from phase2.authoring.build import DOMAINS
camp = sys.argv[1]
makers = {}
for dom in DOMAINS:
    mod = importlib.import_module(f'phase2.authoring.{dom}')
    for fn in mod.TASKS: makers[fn()['id']] = fn
db = sqlite3.connect(f'file:phase2/results/{camp}/journal.sqlite3?mode=ro', uri=True)
out = []
for rid, task, lang, status, res in db.execute('select id,task,language,status,result from runs order by task,language'):
    r = json.loads(res or '{}')
    if status == 'infrastructure_failed' or (r.get('score') or 0) == 100: continue
    spec = makers[task]()
    p = f'phase2/results/{camp}/runs/{rid}/artifacts/out/result.csv'
    head = f"## {task} {lang} status={status} score={r.get('score')} reason={r.get('reason')}"
    if not os.path.exists(p): out.append(head + ' NO FILE'); continue
    rows = list(csv.reader(open(p, encoding='utf-8-sig')))
    if not rows: out.append(head + ' EMPTY'); continue
    h, body = rows[0], [x for x in rows[1:] if x]
    out.append(head + f' header={h}' + ('' if h == spec['output'] else f' EXPECTED={spec["output"]}'))
    from phase2.grader import normalize, same_value
    kc = spec['key_columns']; cols = spec['output']; num = set(spec['numeric'])
    expd = {tuple(normalize(v) for v in e[:kc]): [normalize(v) for v in e[kc:]] for e in spec['answer']}
    got = {tuple(normalize(v) for v in b[:kc]): [normalize(v) for v in b[kc:]] for b in body if len(b) == len(cols)}
    miss = [k for k in expd if k not in got]; extra = [k for k in got if k not in expd]
    if miss: out.append(f'  missing keys ({len(miss)}): {miss[:6]}')
    if extra: out.append(f'  extra keys ({len(extra)}): {extra[:6]}')
    n = 0
    for k, e in expd.items():
        g = got.get(k)
        if not g: continue
        for c, a, b in zip(cols[kc:], g, e):
            if not same_value(num, c, a, b):
                n += 1
                if n <= 8: out.append(f'  {":".join(k)} {c}: exp={b!r} got={a!r}')
    if n > 8: out.append(f'  ... {n} mismatched cells total')
print('\n'.join(out))
