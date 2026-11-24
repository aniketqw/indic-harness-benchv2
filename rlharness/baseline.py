"""No-lessons baseline repeats on OpenClaw (noise floor). Resumable via JSONL log.
Usage: PYTHONPATH=. python3.13 -u -m rlharness.baseline --run oc_base1 --reps 3
"""
import argparse, json, statistics as st
from pathlib import Path
from rlharness.core import LANGS
from rlharness.loop import Log, TRAIN, TEST, parallel, run_one

ap = argparse.ArgumentParser()
ap.add_argument("--model", default="gpt-oss:20b-cloud"); ap.add_argument("--run", default="oc_base1")
ap.add_argument("--reps", type=int, default=3); ap.add_argument("--cond", default="base")
a = ap.parse_args()
out = Path(__file__).parent / "runs" / a.run; out.mkdir(parents=True, exist_ok=True)
log = Log(out / "attempts.jsonl")
tasks = TRAIN + TEST
jobs = [(run_one, (log, a.model, f"{a.cond}|{t}|{l}|{r}", t, l, [], 0.0)) for r in range(a.reps) for t in tasks for l in LANGS]
print(f"{len(jobs)} attempts", flush=True)
parallel(jobs)
rows = [r for r in log.rows if r["key"].startswith(a.cond + "|")]
summ = {"n": len(rows), "mean": round(st.mean(r["score"] for r in rows), 4), "by_lang": {}, "by_task": {}, "rep_spread": {}}
for l in LANGS: summ["by_lang"][l] = round(st.mean(r["score"] for r in rows if r["lang"] == l), 4)
for t in tasks:
    summ["by_task"][t] = round(st.mean(r["score"] for r in rows if r["task"] == t), 4)
    reps = [[r["score"] for r in rows if r["task"] == t and r["key"].endswith("|%d" % k)] for k in range(a.reps)]
    means = [st.mean(x) for x in reps if x]
    summ["rep_spread"][t] = round(max(means) - min(means), 4) if len(means) > 1 else None
(out / "summary.json").write_text(json.dumps(summ, indent=1)); print(json.dumps(summ, indent=1))
