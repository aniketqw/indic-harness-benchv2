"""Experiment 1 (see EXPERIMENT_PLAN.md): matched baseline / placebo / tips comparison, GLM, Phase 2, OpenClaw.

Stages (all resumable from runs/<run>/attempts.jsonl):
  1  practice (seeded variants, G attempts, temp 0.7)  +  arm A baseline  (run in one pool)
  2  reflect -> tips; then arm B placebo, arm C tips, noise re-run of A, transfer A and C
  3  analyze (pre-specified rule), saves summary.json

Usage: PYTHONPATH=. python3.13 -B -X utf8 -u -m rlharness.p2exp --run p2_exp1 --workers 5 [--stage all|practice|analyze]
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics as st
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from phase2.suite import FILE_LANGS, PROMPT_LANGS, inputs, prompt
from rlharness.core import chat
from rlharness.p2run import MODELS, attempt, get_task

MODEL = "glm"
PRIMARY = ["04-exam-seating", "07-ui-strings", "06-seed-allocation", "09-water-schedule",
           "10-grievance-dedup", "13-appointment-rebooking", "15-catalogue-merge", "16-digitization-audit"]
TRANSFER = ["01-upi-settlement", "02-gst-payables", "11-parcel-dispatch", "12-delivery-audit"]
G = 4
PRACTICE_TEMP = 0.7
MAX_TIPS = 8
NOISE_N = 12
REUSE = {  # earlier plain GLM runs of identical conditions (same harness settings); counted as transfer arm A items
    "A|01-upi-settlement|en|en|r0": "glm|01-upi-settlement|en|en|r0",
    "A|01-upi-settlement|en|hi|r0": "glm|01-upi-settlement|en|hi|r0",
}
PLACEBO_POOL = [
    "Work carefully and thoroughly.", "Read the task fully before you start.", "Be precise and professional.",
    "Double check your work before finishing.", "Think step by step and stay organised.",
    "Pay attention to every detail in the instructions.", "Take your time to produce a high quality result.",
    "Make sure the final answer is complete and well formed.", "Stay focused on the goal of the task.",
    "Follow the instructions exactly as written.",
]

lock = threading.Lock()
ART_DIR = None
REFLOG = None


def safe(key):
    return re.sub(r'[^A-Za-z0-9_.-]+', '__', key)


class Log:
    def __init__(self, path):
        self.path = path
        self.rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []
        self.keys = {r["key"] for r in self.rows}

    def add(self, row):
        with lock:
            self.rows.append(row); self.keys.add(row["key"])
            with self.path.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def get(self, key):
        return next(r for r in self.rows if r["key"] == key)


def pick_seed(task_id):
    for seed in range(101, 140):
        try:
            get_task(task_id, seed); return seed
        except ValueError:
            continue
    raise RuntimeError(f"no valid seed for {task_id}")


def run_item(log, key, task, plang, flang, lessons, seed=None, temp=0.0):
    if key in log.keys:
        return
    r = attempt(MODEL, task, plang, flang, seed=seed, lessons=lessons, temperature=temp)
    if r["error"] and ("harness_error" in r["error"] or "rc=" in r["error"]):
        r = attempt(MODEL, task, plang, flang, seed=seed, lessons=lessons, temperature=temp); r["retried"] = True
    r["key"] = key; r["arm"] = key.split("|")[0]; r["lessons_n"] = len(lessons or []); r["temperature"] = temp; r["seed_used"] = seed
    r["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if ART_DIR is not None:  # full evidence on disk: output file and agent transcript
        (ART_DIR / (safe(key) + ".result.csv")).write_text(r.pop("result_full", ""), encoding="utf-8")
        (ART_DIR / (safe(key) + ".openclaw.json")).write_text(r.pop("stdout_full", ""), encoding="utf-8")
        r["artifact"] = safe(key)
    r.pop("stdout_tail", None); r["result_head"] = r["result_head"][:300]
    log.add(r)
    print(f"  {key}: score={r['score']:.3f} full={r['full']} {r['elapsed']}s {r['reason'] or ''} {(r['error'] or '')[:50]}", flush=True)


def pool(workers, fns):
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(lambda f: f(), fns))


def primary_items():
    return [(t, pl, fl) for t in PRIMARY for pl in PROMPT_LANGS for fl in FILE_LANGS]


def transfer_items():
    return [(t, "en", fl) for t in TRANSFER for fl in FILE_LANGS]


# ---------------------------------------------------------------- reflection
def llm_json(prompt_text):
    r = chat(MODELS[MODEL], [{"role": "user", "content": prompt_text}], 0.2, None, tools=False, num_predict=12000)
    raw = r["message"].get("content", "")
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        parsed = json.loads(m.group(0)) if m else {}
    except Exception:
        parsed = {}
    if REFLOG is not None:  # keep every reflector prompt and raw response
        with lock, REFLOG.open("a") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "prompt": prompt_text, "raw": raw, "parsed": parsed}, ensure_ascii=False) + "\n")
    return parsed


def fmt_wrong(a):
    return "\n".join(f"  row {w['key']} column {w['column']}: expected {w['expected']!r}, got {w['actual']!r}" for w in a["wrong"][:8]) or "  (none listed)"


def reflect(task_id, seed, flang, best, worst, existing):
    task = get_task(task_id, seed)
    notice = inputs(task, flang)["in/notice.txt"].decode("utf-8")[:3500]
    text = f"""You improve an AI agent that does data-processing jobs on CSV files, graded field by field.
Below are two attempts at the SAME job. Attempt A scored higher than attempt B.

JOB REQUEST:
{prompt(task, 'en')[:900]}

RULES NOTICE GIVEN TO THE AGENT:
{notice}

ATTEMPT A: score {best['score']:.2f}, wrong fields {best['wrong_total']}, no file: {best['reason']}
ATTEMPT B: score {worst['score']:.2f}, wrong fields {worst['wrong_total']}, no file: {worst['reason']}
Some of B's wrong fields (expected vs actual):
{fmt_wrong(worst)}

Existing tips: {json.dumps(existing)}

Write at most 2 NEW tips about HOW to do this kind of job reliably (for example how to apply rules, order amendments,
round, handle boundaries, convert units, check output). Each tip: one imperative sentence under 30 words, general enough to
help on other jobs of this kind, no specific data values, not a duplicate. Return ONLY JSON: {{"tips": ["...", "..."]}}"""
    tips = llm_json(text).get("tips", [])
    return [t.strip() for t in tips if isinstance(t, str) and 10 < len(t) < 260][:2]


def consolidate(tips):
    if len(tips) <= MAX_TIPS:
        return tips
    text = f"""Merge duplicates and drop vague or overly specific items. Keep the {MAX_TIPS} most broadly useful tips for an AI agent
doing CSV data-processing jobs with written rules. Each: one imperative sentence under 30 words.
{json.dumps(tips)}
Return ONLY JSON: {{"tips": [...]}}"""
    out = [t for t in llm_json(text).get("tips", []) if isinstance(t, str)]
    return out[:MAX_TIPS] or tips[:MAX_TIPS]


def make_placebo(tips):
    target = sum(len(t) + 1 for t in tips)
    out, total, i = [], 0, 0
    while total < target and i < 200:
        s = PLACEBO_POOL[i % len(PLACEBO_POOL)]
        if out and abs(total + len(s) + 1 - target) > abs(total - target):
            break
        out.append(s); total += len(s) + 1; i += 1
    return out


def learn_tips(log, outdir, seeds):
    path = outdir / "tips.json"
    if path.exists():
        return json.loads(path.read_text())
    tips, report = [], []
    for task in PRIMARY:
        for fl in FILE_LANGS:
            grp = [log.get(f"prac|{task}|en|{fl}|g{g}") for g in range(G)]
            valid = [a for a in grp if not (a["error"] and "harness_error" in a["error"])]
            if len(valid) < 2:
                continue
            # "badness" = wrong fields (a missing file counts as worst). Practice variants are often nearly perfect, so a
            # score-gap threshold would learn nothing; any difference in wrong fields is a usable signal.
            bad = lambda a: 10 ** 6 if a.get("reason") else a.get("wrong_total", 0)
            best = min(valid, key=lambda a: (bad(a), -a["score"])); worst = max(valid, key=lambda a: (bad(a), -a["score"]))
            scores = [round(a["score"], 3) for a in grp]
            if bad(best) == bad(worst):
                report.append({"task": task, "flang": fl, "scores": scores, "tips": [], "note": "no difference in wrong fields"}); continue
            new = reflect(task, seeds[task], fl, best, worst, tips)
            tips += [t for t in new if t not in tips]
            report.append({"task": task, "flang": fl, "scores": scores, "tips": new})
            print(f"  practice {task}/{fl}: scores {scores} -> {len(new)} tips", flush=True)
    tips = consolidate(tips)
    path.write_text(json.dumps(tips, indent=1, ensure_ascii=False))
    (outdir / "practice_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    return tips


# ---------------------------------------------------------------- analysis
def analyze(log, outdir, tips, placebo):
    def full(a): return bool(a["full"])
    rows = {r["key"]: r for r in log.rows}
    ok = lambda r: not (r["error"] and ("harness_error" in r["error"] or "rc=" in r["error"]))
    prim = primary_items()
    pairs = []
    for t, pl, fl in prim:
        ks = {arm: f"{arm}|{t}|{pl}|{fl}|r0" for arm in "ABC"}
        if all(k in rows and ok(rows[k]) for k in ks.values()):
            pairs.append((t, pl, fl, {arm: rows[k] for arm, k in ks.items()}))
    n = len(pairs)
    res = {"n_matched_items": n, "n_primary_items": len(prim), "tips": tips, "placebo": placebo}
    if n == 0:
        (outdir / "summary.json").write_text(json.dumps(res, indent=1, ensure_ascii=False)); return res
    for arm in "ABC":
        res[arm] = {"fully_correct": sum(full(p[3][arm]) for p in pairs),
                    "mean_score": round(st.mean(p[3][arm]["score"] for p in pairs), 4)}
    def flips(x, y):
        better = sum(1 for p in pairs if full(p[3][y]) and not full(p[3][x]))
        worse = sum(1 for p in pairs if full(p[3][x]) and not full(p[3][y]))
        return {"better": better, "worse": worse, "same": n - better - worse}
    res["C_vs_A"] = flips("A", "C"); res["C_vs_B"] = flips("B", "C"); res["B_vs_A"] = flips("A", "B")
    res["by_file_language"] = {fl: {arm: sum(full(p[3][arm]) for p in pairs if p[2] == fl) for arm in "ABC"} | {"n": sum(1 for p in pairs if p[2] == fl)} for fl in FILE_LANGS}
    res["by_prompt_language"] = {pl: {arm: sum(full(p[3][arm]) for p in pairs if p[1] == pl) for arm in "ABC"} | {"n": sum(1 for p in pairs if p[1] == pl)} for pl in PROMPT_LANGS}
    res["by_task"] = {t: {arm: sum(full(p[3][arm]) for p in pairs if p[0] == t) for arm in "ABC"} | {"n": sum(1 for p in pairs if p[0] == t)} for t in PRIMARY}
    # task-clustered bootstrap of (C - A) fully-correct rate
    per_task = [(sum(full(p[3]["C"]) for p in pairs if p[0] == t) - sum(full(p[3]["A"]) for p in pairs if p[0] == t)) / max(1, sum(1 for p in pairs if p[0] == t)) for t in PRIMARY]
    rng = random.Random(20261125)
    boots = sorted(st.mean(rng.choice(per_task) for _ in per_task) for _ in range(10000))
    res["C_minus_A_rate_task_bootstrap_95"] = [round(boots[250], 3), round(boots[9750], 3)]
    # noise: A re-run
    nz = [(rows[f"A|{t}|{pl}|{fl}|r0"], rows[k]) for t, pl, fl in prim for k in [f"A|{t}|{pl}|{fl}|r1"] if k in rows and ok(rows[k]) and f"A|{t}|{pl}|{fl}|r0" in rows]
    res["noise_rerun"] = {"n": len(nz), "full_status_changed": sum(1 for a, b in nz if full(a) != full(b)),
                          "mean_abs_score_change": round(st.mean(abs(a["score"] - b["score"]) for a, b in nz), 4) if nz else None}
    # transfer check
    tr = [(rows.get(f"A|{t}|{pl}|{fl}|r0"), rows.get(f"C|{t}|{pl}|{fl}|r0")) for t, pl, fl in transfer_items()]
    tr = [(a, c) for a, c in tr if a and c and ok(a) and ok(c)]
    res["transfer"] = {"n": len(tr), "A_full": sum(full(a) for a, c in tr), "C_full": sum(full(c) for a, c in tr)}
    # pre-specified rule
    c_a = res["C"]["fully_correct"] - res["A"]["fully_correct"]; c_b = res["C"]["fully_correct"] - res["B"]["fully_correct"]
    f = res["C_vs_A"]; noise_flip = res["noise_rerun"]["full_status_changed"]
    rule = {"1_C_beats_A_by_6": c_a >= 6, "2_C_beats_B_by_3": c_b >= 3,
            "3_worse_at_most_half_of_better": f["worse"] * 2 <= f["better"],
            "4_noise_change_smaller_than_A_vs_C_change": noise_flip < (f["better"] + f["worse"])}
    res["rule"] = rule; res["tips_helped_by_prespecified_rule"] = all(rule.values())
    # ---- evidence for "why" ----
    def category(r):
        if r["full"]: return "fully_correct"
        if r["reason"] == "output_missing_or_oversized": return "no_file"
        if r["reason"]: return "invalid_output:" + r["reason"]
        if not r.get("input_intact", True): return "inputs_changed"
        return "wrong_values"
    res["failure_taxonomy"] = {arm: {} for arm in "ABC"}
    for p in pairs:
        for arm in "ABC":
            c = category(p[3][arm]); res["failure_taxonomy"][arm][c] = res["failure_taxonomy"][arm].get(c, 0) + 1
    res["mean_wrong_fields"] = {arm: round(st.mean(p[3][arm].get("wrong_total", 0) for p in pairs), 2) for arm in "ABC"}
    res["agent_effort"] = {arm: {"mean_elapsed_s": round(st.mean(p[3][arm]["elapsed"] for p in pairs), 1),
                                 "mean_tool_calls": round(st.mean((p[3][arm].get("stats") or {}).get("tool_calls", 0) for p in pairs), 1),
                                 "mean_tool_failures": round(st.mean((p[3][arm].get("stats") or {}).get("tool_failures", 0) for p in pairs), 2)} for arm in "ABC"}
    def wrongset(r): return {(w["key"], w["column"]) for w in r.get("wrong", [])}
    fixed, broken, col_fixed, col_broken = 0, 0, {}, {}
    for t, pl, fl, d in pairs:
        wa, wc = wrongset(d["A"]), wrongset(d["C"])
        for key, col in wa - wc:
            fixed += 1; col_fixed[f"{t}:{col}"] = col_fixed.get(f"{t}:{col}", 0) + 1
        for key, col in wc - wa:
            broken += 1; col_broken[f"{t}:{col}"] = col_broken.get(f"{t}:{col}", 0) + 1
    res["field_delta_C_vs_A"] = {"fields_fixed": fixed, "fields_broken": broken,
                                 "columns_most_fixed": dict(sorted(col_fixed.items(), key=lambda x: -x[1])[:10]),
                                 "columns_most_broken": dict(sorted(col_broken.items(), key=lambda x: -x[1])[:10])}
    res["flipped_items"] = [{"task": t, "plang": pl, "flang": fl, "A_score": round(d["A"]["score"], 3), "B_score": round(d["B"]["score"], 3),
                             "C_score": round(d["C"]["score"], 3), "A_full": d["A"]["full"], "C_full": d["C"]["full"]}
                            for t, pl, fl, d in pairs if d["A"]["full"] != d["C"]["full"]]
    res["note"] = "Matched on the same frozen items. If fewer than 48 items are matched, infrastructure failures were excluded."
    (outdir / "summary.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return res


def ablate(log, outdir, tips, workers, max_items=6):
    """Leave-one-tip-out on items that the full tip list fixed (A not fully correct, C fully correct)."""
    rows = {r["key"]: r for r in log.rows}
    flips = [(t, pl, fl) for t, pl, fl in primary_items()
             if f"A|{t}|{pl}|{fl}|r0" in rows and f"C|{t}|{pl}|{fl}|r0" in rows
             and not rows[f"A|{t}|{pl}|{fl}|r0"]["full"] and rows[f"C|{t}|{pl}|{fl}|r0"]["full"]][:max_items]
    fns = [lambda t=t, pl=pl, fl=fl, i=i: run_item(log, f"D{i}|{t}|{pl}|{fl}|r0", t, pl, fl, tips[:i] + tips[i + 1:])
           for (t, pl, fl) in flips for i in range(len(tips))]
    pool(workers, fns)
    rows = {r["key"]: r for r in log.rows}
    out = {"items": [list(f) for f in flips], "per_tip": []}
    for i, tip in enumerate(tips):
        done = [rows[f"D{i}|{t}|{pl}|{fl}|r0"] for t, pl, fl in flips if f"D{i}|{t}|{pl}|{fl}|r0" in rows]
        out["per_tip"].append({"tip": tip, "n": len(done), "lost_full_when_removed": sum(1 for r in done if not r["full"])})
    (outdir / "ablation.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="p2_exp1"); ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--stage", default="all")
    a = ap.parse_args()
    outdir = Path(__file__).parent / "runs" / a.run; outdir.mkdir(parents=True, exist_ok=True)
    global ART_DIR, REFLOG
    ART_DIR = outdir / "artifacts"; ART_DIR.mkdir(exist_ok=True); REFLOG = outdir / "reflection_log.jsonl"
    log = Log(outdir / "attempts.jsonl")
    # reuse earlier identical plain runs as transfer arm A items
    old = Path(__file__).parent / "runs" / "p2_base1" / "attempts.jsonl"
    if old.exists():
        prev = {json.loads(l)["key"]: json.loads(l) for l in old.read_text().splitlines() if l.strip()}
        for newk, oldk in REUSE.items():
            if newk not in log.keys and oldk in prev:
                r = dict(prev[oldk]); r["key"] = newk; r["reused_from"] = "p2_base1:" + oldk; log.add(r)
    seeds = {t: pick_seed(t) for t in PRIMARY}
    (outdir / "seeds.json").write_text(json.dumps(seeds))
    print("seeds:", seeds, flush=True)
    import subprocess, sys
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=Path(__file__).parent).stdout.strip()
    manifest = {"run": a.run, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "git_commit": commit, "python": sys.version,
                "model": MODELS[MODEL], "openclaw_image": "ihb-agent:2026.9.7", "workers": a.workers, "thinking": "high",
                "eval_temperature": 0.0, "practice_temperature": PRACTICE_TEMP, "group_size": G, "max_tips": MAX_TIPS,
                "primary_tasks": PRIMARY, "transfer_tasks": TRANSFER, "seeds": seeds, "noise_items": NOISE_N,
                "prompt_languages": list(PROMPT_LANGS), "file_languages": list(FILE_LANGS), "reused": REUSE,
                "plan": "rlharness/EXPERIMENT_PLAN.md", "proxy_allow_list": "rlharness/proxy.py"}
    (outdir / "run_manifest.json").write_text(json.dumps(manifest, indent=1))
    t0 = time.time()

    if a.stage in ("all", "practice"):
        print("== stage 1: practice + arm A", flush=True)
        fns = [lambda t=t, fl=fl, g=g: run_item(log, f"prac|{t}|en|{fl}|g{g}", t, "en", fl, [], seeds[t], PRACTICE_TEMP)
               for t in PRIMARY for fl in FILE_LANGS for g in range(G)]
        fns += [lambda t=t, pl=pl, fl=fl: run_item(log, f"A|{t}|{pl}|{fl}|r0", t, pl, fl, [])
                for t, pl, fl in primary_items()]
        pool(a.workers, fns)
        print(f"stage 1 done in {(time.time()-t0)/60:.1f} min", flush=True)
    if a.stage in ("all", "arms"):
        tips = learn_tips(log, outdir, seeds)
        placebo = make_placebo(tips)
        (outdir / "placebo.json").write_text(json.dumps(placebo, indent=1))
        print("== tips:", json.dumps(tips, ensure_ascii=False), "\n== placebo:", placebo, flush=True)
        rng = random.Random(7)
        noise = rng.sample(primary_items(), NOISE_N)
        fns = [lambda t=t, pl=pl, fl=fl: run_item(log, f"B|{t}|{pl}|{fl}|r0", t, pl, fl, placebo) for t, pl, fl in primary_items()]
        fns += [lambda t=t, pl=pl, fl=fl: run_item(log, f"C|{t}|{pl}|{fl}|r0", t, pl, fl, tips) for t, pl, fl in primary_items()]
        fns += [lambda t=t, pl=pl, fl=fl: run_item(log, f"A|{t}|{pl}|{fl}|r1", t, pl, fl, []) for t, pl, fl in noise]
        fns += [lambda t=t, pl=pl, fl=fl: run_item(log, f"A|{t}|{pl}|{fl}|r0", t, pl, fl, []) for t, pl, fl in transfer_items()]
        fns += [lambda t=t, pl=pl, fl=fl: run_item(log, f"C|{t}|{pl}|{fl}|r0", t, pl, fl, tips) for t, pl, fl in transfer_items()]
        random.Random(11).shuffle(fns)  # mix arms so any drift in the service hits all arms equally
        pool(a.workers, fns)
        print(f"all arms done in {(time.time()-t0)/60:.1f} min", flush=True)
    if a.stage == "ablate":
        tips = json.loads((outdir / "tips.json").read_text())
        print(json.dumps(ablate(log, outdir, tips, a.workers), indent=1, ensure_ascii=False), flush=True)
    if a.stage in ("all", "arms", "analyze"):
        tips = json.loads((outdir / "tips.json").read_text()); placebo = json.loads((outdir / "placebo.json").read_text())
        print(json.dumps(analyze(log, outdir, tips, placebo), indent=1, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
