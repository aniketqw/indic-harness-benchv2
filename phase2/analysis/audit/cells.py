import re,sys
from collections import Counter,defaultdict
for f in sys.argv[1:]:
    c=Counter(); runs=defaultdict(int); task=None
    for line in open(f,encoding='utf-8'):
        m=re.match(r'## (\S+) (\S+) status=(\S+) score=(\S+)',line)
        if m: task=m.group(1); fl='header=' in line; runs[task]+=fl; continue
        m=re.match(r'  (\S+) (\S+): exp=(.*) got=',line)
        if m and task: c[(task,m.group(1),m.group(2),m.group(3))]+=1
    print('=====',f.split('/')[-1],'outputs with file per task',dict(runs))
    for k,v in c.most_common(30):
        if v>=2: print(v,k)
