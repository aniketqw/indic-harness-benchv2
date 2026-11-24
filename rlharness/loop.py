"""Experience-GRPO pilot: group sampling -> reward -> best-vs-worst reflection -> lesson library.

Weights are frozen (Ollama Cloud). The "policy update" is an edit to a lesson library that is
prepended to later prompts. Stages: baseline | train | eval. Every attempt is appended to a JSONL log
so a stopped run resumes without repeating attempts.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rlharness.core import LANGS, chat, load_prompt
from rlharness.oc_runner import attempt
from rlharness.reward import group_advantages, reward

TRAIN = ["027-contract-summary-risk", "036-citation-consistency-audit", "063-alert-dedup-noise", "071-ecommerce-support-routing"]
TEST = ["033-offline-knowledge-qa", "035-conflicting-source-resolution", "034-evidence-matrix-claims", "062-k8s-config-audit"]
PLACEBO = ["Work carefully and thoroughly.", "Read the task fully before starting.", "Be precise and professional."]
MAX_LESSONS = 8
WORKERS = 2


class Log:
    def __init__(self, path: Path):
        self.path = path; self.rows = []
        if path.exists():
            self.rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def has(self, key): return any(r["key"] == key for r in self.rows)
    def get(self, key): return next(r for r in self.rows if r["key"] == key)

    def add(self, row):
        self.rows.append(row)
        with self.path.open("a") as f: f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_one(log: Log, model, key, task, lang, lessons, temp):
    if log.has(key): return log.get(key)
    a = attempt(model, task, lang, lessons, temp)
    a["key"] = key; a["reward"] = reward(a); a["lessons_n"] = len(lessons)
    log.add(a); print(f"  {key}: score={a['score']:.2f} reward={a['reward']} t={a['elapsed']}s err={(a['error'] or '')[:60]}", flush=True)
    return a


def parallel(fn_args):
    with ThreadPoolExecutor(WORKERS) as ex: return list(ex.map(lambda x: x[0](*x[1]), fn_args))


def llm_json(model, prompt):
    r = chat(model, [{"role": "user", "content": prompt}], 0.2, None, tools=False)
    txt = r["message"].get("content", "")
    m = re.search(r"\{.*\}", txt, re.S)
    try: return json.loads(m.group(0)) if m else {}
    except Exception: return {}


def fmt_checks(a): return "\n".join(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['label']}" for c in a["checks"])


def reflect(model, task, lang, best, worst, existing):
    prompt = f"""You improve an AI agent that completes file-based office/engineering tasks graded by deterministic checks.
Below are two attempts at the SAME task. Attempt A scored higher than attempt B.

TASK PROMPT ({lang}):
{load_prompt(task, lang)[:1800]}

ATTEMPT A (reward {best['reward']:.2f}) grader checks:
{fmt_checks(best)}
A output files (excerpt): {json.dumps(best['outputs'], ensure_ascii=False)[:900]}

ATTEMPT B (reward {worst['reward']:.2f}) grader checks:
{fmt_checks(worst)}
B output files (excerpt): {json.dumps(worst['outputs'], ensure_ascii=False)[:900]}

Existing lessons: {json.dumps(existing)}

Write at most 2 NEW lessons explaining what A did that B did not. Rules: each lesson is one imperative sentence under 30 words,
GENERAL (useful on other tasks), no task-specific values, filenames or data, and not a duplicate of an existing lesson.
Return ONLY JSON: {{"lessons": ["...", "..."]}}"""
    out = llm_json(model, prompt).get("lessons", [])
    return [l.strip() for l in out if isinstance(l, str) and 10 < len(l) < 260][:2]


def consolidate(model, lessons):
    if len(lessons) <= MAX_LESSONS: return lessons
    prompt = f"""Merge duplicates and drop vague or task-specific items from these agent lessons. Keep the {MAX_LESSONS} most broadly useful,
each one imperative sentence under 30 words.
{json.dumps(lessons)}
Return ONLY JSON: {{"lessons": [...]}}"""
    out = [l for l in llm_json(model, prompt).get("lessons", []) if isinstance(l, str)]
    return out[:MAX_LESSONS] or lessons[:MAX_LESSONS]


def train(model, log, outdir, epochs, G, temp):
    lib_path = outdir / "lessons.json"
    lessons = json.loads(lib_path.read_text()) if lib_path.exists() else []
    for ep in range(1, epochs + 1):
        print(f"== epoch {ep}: {len(lessons)} lessons in context", flush=True)
        jobs = [(run_one, (log, model, f"train|e{ep}|{t}|{l}|{g}", t, l, lessons, temp))
                for t in TRAIN for l in LANGS for g in range(G)]
        parallel(jobs)
        added = 0
        for t in TRAIN:
            for l in LANGS:
                grp = [log.get(f"train|e{ep}|{t}|{l}|{g}") for g in range(G)]
                rs = [a["reward"] for a in grp]
                adv = group_advantages(rs)
                valid = [(a, r) for a, r in zip(grp, rs) if r is not None]
                if len(valid) < 2: continue
                best = max(valid, key=lambda x: x[1]); worst = min(valid, key=lambda x: x[1])
                if best[1] - worst[1] < 0.1:
                    print(f"  no spread {t}/{l}: skip (no spread, no learning)", flush=True); continue
                new = reflect(model, t, l, best[0], worst[0], lessons)
                for n in new:
                    if n not in lessons: lessons.append(n); added += 1
                print(f"  {t}/{l}: rewards={[round(r,2) if r is not None else None for r in rs]} -> +{len(new)} lessons", flush=True)
        lessons = consolidate(model, lessons)
        lib_path.write_text(json.dumps(lessons, indent=1, ensure_ascii=False))
        ep_scores = [a["reward"] for a in log.rows if a["key"].startswith(f"train|e{ep}|") and a["reward"] is not None]
        print(f"== epoch {ep} done: mean train reward {statistics.mean(ep_scores):.3f}, library={len(lessons)}", flush=True)
    return lessons


def evaluate(model, log, cond, lessons, reps, tasks=TEST):
    jobs = [(run_one, (log, model, f"eval|{cond}|{t}|{l}|{r}", t, l, lessons, 0.0))
            for t in tasks for l in LANGS for r in range(reps)]
    parallel(jobs)


def summarize(log, outdir, model):
    rows = [r for r in log.rows if r["key"].startswith("eval|") and r["reward"] is not None]
    out = {}
    for cond in sorted({r["key"].split("|")[1] for r in rows}):
        c = [r for r in rows if r["key"].split("|")[1] == cond]
        out[cond] = {"n": len(c), "mean_score": round(statistics.mean(r["score"] for r in c), 4),
                     "by_lang": {l: round(statistics.mean(r["score"] for r in c if r["lang"] == l), 4) for l in LANGS if any(r["lang"] == l for r in c)},
                     "by_task": {t: round(statistics.mean(r["score"] for r in c if r["task"] == t), 4) for t in TEST if any(r["task"] == t for r in c)},
                     "integrity_violations": sum(1 for r in c if r.get("integrity_violation"))}
    (outdir / f"summary_{model.replace(':','_')}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gpt-oss:20b-cloud"); ap.add_argument("--run", default="pilot1")
    ap.add_argument("--stages", default="baseline,train,eval"); ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--G", type=int, default=4); ap.add_argument("--reps", type=int, default=2)
    a = ap.parse_args()
    outdir = Path(__file__).parent / "runs" / a.run; outdir.mkdir(parents=True, exist_ok=True)
    log = Log(outdir / "attempts.jsonl"); random.seed(0)
    st = a.stages.split(",")
    if "baseline" in st: print("== baseline"); evaluate(a.model, log, "baseline", [], a.reps)
    lessons = []
    if "train" in st: lessons = train(a.model, log, outdir, a.epochs, a.G, 0.7)
    elif (outdir / "lessons.json").exists(): lessons = json.loads((outdir / "lessons.json").read_text())
    if "eval" in st:
        print("== eval placebo"); evaluate(a.model, log, "placebo", PLACEBO, a.reps)
        print("== eval lessons"); evaluate(a.model, log, "lessons", lessons, a.reps)
        summarize(log, outdir, a.model)


if __name__ == "__main__":
    main()
