import json,sys,glob
tid=sys.argv[1]; pats=sys.argv[2:]
for f in glob.glob('phase2/tasks/*.json'):
    for t in json.load(open(f,encoding='utf-8')):
        if not t['id'].startswith(tid): continue
        print(t['notice']['en'])
        for fl in t['files']:
            print('---',fl['name'],fl['headers']['en'])
            for r in fl['rows']['en']:
                s=' | '.join(r)
                if not pats or any(p in s for p in pats): print('  ',s)
        print('ANSWER:',[a for a in t['answer'] if not pats or any(p in ' '.join(a) for p in pats)])
