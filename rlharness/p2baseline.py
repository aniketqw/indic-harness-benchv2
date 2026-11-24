"""Phase 2 no-lessons baseline (condition C0) on OpenClaw. Resumable: finished attempts are skipped.

Usage: PYTHONPATH=. python3.13 -B -X utf8 -u -m rlharness.p2baseline --run p2_base1 --reps 1 [--tasks pilot|all]
"""
import argparse
import json
import statistics as st
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from phase2.suite import FILE_LANGS, PILOT, PROMPT_LANGS
from rlharness.p2run import MODELS, attempt, get_task

ap = argparse.ArgumentParser()
ap.add_argument("--run", default="p2_base1"); ap.add_argument("--reps", type=int, default=1)
ap.add_argument("--tasks", default="pilot"); ap.add_argument("--workers", type=int, default=2)
ap.add_argument("--models", default="glm,nemotron")
a = ap.parse_args()

out = Path(__file__).parent / "runs" / a.run; out.mkdir(parents=True, exist_ok=True)
path = out / "attempts.jsonl"; lock = threading.Lock()
rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []
done = {r["key"] for r in rows}

tasks = sorted(PILOT) if a.tasks == "pilot" else sorted(get_task.__globals__["catalog"]().keys())
jobs = []
for rep in range(a.reps):
    for t in tasks:
        for pl in PROMPT_LANGS:
            for fl in FILE_LANGS:
                for m in a.models.split(","):
                    key = f"{m}|{t}|{pl}|{fl}|r{rep}"
                    if key not in done:
                        jobs.append((key, m, t, pl, fl))
print(f"{len(jobs)} attempts to run ({len(done)} already done)", flush=True)


def run(job):
    key, m, t, pl, fl = job
    r = attempt(m, t, pl, fl)
    r["key"] = key; r["stdout_tail"] = r["stdout_tail"][-600:]
    with lock:
        rows.append(r)
        with path.open("a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  {key}: score={r['score']:.3f} full={r['full']} {r['elapsed']}s reason={r['reason']} err={(r['error'] or '')[:50]}", flush=True)


with ThreadPoolExecutor(a.workers) as ex:
    list(ex.map(run, jobs))

ok = [r for r in rows if not ("harness_error" in (r["error"] or ""))]
summ = {"n": len(rows), "infra_excluded": len(rows) - len(ok)}
def agg(sel):
    return {"n": len(sel), "mean": round(st.mean(r["score"] for r in sel), 4) if sel else None,
            "full": sum(1 for r in sel if r["full"]), "no_file": sum(1 for r in sel if r["reason"] == "output_missing_or_oversized")}
for dim in ("model", "plang", "flang", "task"):
    summ[dim] = {v: agg([r for r in ok if r[dim] == v]) for v in sorted({r[dim] for r in ok})}
(out / "summary.json").write_text(json.dumps(summ, indent=1)); print(json.dumps(summ, indent=1))
