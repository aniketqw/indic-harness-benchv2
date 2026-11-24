"""Build rlharness/DEEP_ANALYSIS.md: every table and the evidence behind REPORT.md, from the recorded data only.

Usage: PYTHONPATH=. python3.13 -B -X utf8 -m rlharness.p2deep --run p2_exp1 [--out rlharness/DEEP_ANALYSIS.md]
"""
import argparse
import collections
import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).parent
PRIMARY = ["04-exam-seating", "07-ui-strings", "06-seed-allocation", "09-water-schedule",
           "10-grievance-dedup", "13-appointment-rebooking", "15-catalogue-merge", "16-digitization-audit"]
TRANSFER = ["01-upi-settlement", "02-gst-payables", "11-parcel-dispatch", "12-delivery-audit"]


def load(p, default=None):
    return json.loads(p.read_text()) if p.exists() else default


def jl(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def category(r):
    if r.get("full"): return "fully_correct"
    if r.get("reason") == "output_missing_or_oversized": return "no_file"
    if r.get("reason"): return "invalid_output:" + r["reason"]
    if not r.get("input_intact", True): return "inputs_changed"
    return "wrong_values"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run", default="p2_exp1"); ap.add_argument("--out", default=str(HERE / "DEEP_ANALYSIS.md"))
    a = ap.parse_args(); d = HERE / "runs" / a.run
    rows = jl(d / "attempts.jsonl"); M = load(d / "run_manifest.json", {}); S = load(d / "summary.json", {}); P = load(d / "practice_report.json", [])
    ABL = load(d / "ablation.json"); tips = load(d / "tips.json", []); placebo = load(d / "placebo.json", []); refl = jl(d / "reflection_log.jsonl")
    R = {r["key"]: r for r in rows}
    ok = lambda r: not (r.get("error") and ("harness_error" in r["error"] or "rc=" in r["error"]))
    L = []; w = L.append
    w(f"# Deep analysis of experiment `{a.run}`\n")
    w("Generated from the recorded data only. Short version: [`REPORT.md`](REPORT.md). Plan: [`EXPERIMENT_PLAN.md`](EXPERIMENT_PLAN.md).\n")

    w("## 1. Provenance\n")
    w(table(["Field", "Value"], [(k, M.get(k)) for k in ("started", "git_commit", "code_note", "model", "openclaw_image", "workers", "thinking",
                                                       "eval_temperature", "practice_temperature", "group_size", "max_tips", "noise_items")]))
    w(f"Seeds used for practice: `{M.get('seeds')}`. Attempts recorded: {len(rows)} "
      f"({sum(1 for r in rows if r.get('reused_from'))} reused from earlier identical plain runs, "
      f"{sum(1 for r in rows if r.get('retried'))} auto-retried after an infrastructure error, "
      f"{sum(1 for r in rows if not ok(r))} infrastructure failures excluded).\n")

    w("## 2. Every primary item (baseline A / filler B / tips C)\n")
    items = [(t, pl, fl) for t in PRIMARY for pl in ("en", "hi", "hinglish") for fl in ("en", "hi")]
    tr = []
    for t, pl, fl in items:
        def cell(arm):
            r = R.get(f"{arm}|{t}|{pl}|{fl}|r0")
            return "-" if not r else f"{r['score']:.3f}{'*' if r.get('full') else ''}"
        tr.append((t, pl, fl, cell("A"), cell("B"), cell("C")))
    w("`*` = fully correct.\n"); w(table(["Task", "Prompt", "Files", "A", "B", "C"], tr))

    w("## 3. Failure types per arm (primary items)\n")
    cats = collections.defaultdict(lambda: collections.Counter())
    for arm in "ABC":
        for t, pl, fl in items:
            r = R.get(f"{arm}|{t}|{pl}|{fl}|r0")
            if r and ok(r): cats[category(r)][arm] += 1
    w(table(["Type", "A", "B", "C"], [(c, cats[c]["A"], cats[c]["B"], cats[c]["C"]) for c in sorted(cats)]))

    w("## 4. Which fields are wrong (primary items), by task and column\n")
    colerr = collections.defaultdict(lambda: collections.Counter())
    for arm in "ABC":
        for t, pl, fl in items:
            r = R.get(f"{arm}|{t}|{pl}|{fl}|r0")
            if r and ok(r):
                for x in r.get("wrong", []): colerr[(t, x["column"])][arm] += 1
    w("Counts of wrong fields (each field counted once per item; lists are capped at 300 per attempt).\n")
    w(table(["Task", "Column", "A", "B", "C"], [(k[0], k[1], v["A"], v["B"], v["C"]) for k, v in sorted(colerr.items(), key=lambda kv: -(kv[1]["A"] + kv[1]["B"]))[:40]]))

    w("## 5. Items whose status flipped between baseline and tips (evidence per item)\n")
    n_flip = 0
    for t, pl, fl in items:
        A, C = R.get(f"A|{t}|{pl}|{fl}|r0"), R.get(f"C|{t}|{pl}|{fl}|r0")
        if A and C and ok(A) and ok(C) and bool(A.get("full")) != bool(C.get("full")):
            n_flip += 1
            w(f"### {t} ({pl} prompt, {fl} files): baseline {A['score']:.3f} -> tips {C['score']:.3f}\n")
            for lab, r in (("Baseline wrong fields", A), ("Tips wrong fields", C)):
                ww = r.get("wrong", [])[:6]
                w(f"- {lab} ({r.get('wrong_total', 0)} total): " + ("; ".join(f"{x['key']}.{x['column']}: expected {x['expected']!r}, got {x['actual']!r}" for x in ww) or "none") +
                  f". Transcript: `artifacts/{r.get('artifact', '?')}.openclaw.json`, output: `artifacts/{r.get('artifact', '?')}.result.csv`.")
            w("")
    if not n_flip: w("No item flipped.\n")

    w("## 6. Agent behavior per arm\n")
    beh = []
    for arm in "ABC":
        rs = [R[f"{arm}|{t}|{pl}|{fl}|r0"] for t, pl, fl in items if f"{arm}|{t}|{pl}|{fl}|r0" in R and ok(R[f"{arm}|{t}|{pl}|{fl}|r0"])]
        if not rs: continue
        el = sorted(r["elapsed"] for r in rs); tc = [(r.get("stats") or {}).get("tool_calls", 0) for r in rs]; tf = [(r.get("stats") or {}).get("tool_failures", 0) for r in rs]
        beh.append((arm, len(rs), round(st.mean(el)), round(st.median(el)), round(el[int(0.9 * (len(el) - 1))]), round(st.mean(tc), 1), round(st.mean(tf), 2),
                    dict(collections.Counter((r.get("stats") or {}).get("stop_reason", "?") for r in rs))))
    w(table(["Arm", "Items", "Mean s", "Median s", "p90 s", "Mean tool calls", "Mean tool failures", "Stop reasons"], beh))
    tools = collections.Counter(t for r in rows for t in (r.get("stats") or {}).get("tools_used", []))
    w(f"Tools used across all attempts (attempts using each): {dict(tools)}.\n")

    w("## 7. Practice and tip learning\n")
    if P:
        w(table(["Task", "Files", "Scores of the 4 attempts", "Spread", "Tips written"],
                [(g["task"], g["flang"], g["scores"], round(max(g["scores"]) - min(g["scores"]), 3), len(g.get("tips", []))) for g in P]))
    w(f"Reflector calls recorded: {len(refl)}; responses that failed to parse: {sum(1 for r in refl if not r.get('parsed'))}. "
      "Full prompts and raw responses: `reflection_log.jsonl`.\n")
    w("Final tips (after consolidation to at most eight):\n")
    for i, t in enumerate(tips): w(f"{i + 1}. {t}")
    w(f"\nFiller used for arm B (same length): {' '.join(placebo)}\n")
    if ABL:
        w("### Leave-one-tip-out (causal check)\n")
        w(f"Items re-run: {ABL['items']}.\n")
        w(table(["Tip", "Items", "Lost full marks when removed"], [(r["tip"][:100], r["n"], r["lost_full_when_removed"]) for r in ABL["per_tip"]]))

    w("## 8. Noise re-run of the baseline\n")
    nzr = []
    for t, pl, fl in items:
        r0, r1 = R.get(f"A|{t}|{pl}|{fl}|r0"), R.get(f"A|{t}|{pl}|{fl}|r1")
        if r0 and r1: nzr.append((t, pl, fl, f"{r0['score']:.3f}", f"{r1['score']:.3f}", "changed" if bool(r0.get("full")) != bool(r1.get("full")) else "same"))
    w(table(["Task", "Prompt", "Files", "Run 1", "Run 2", "Full status"], nzr) if nzr else "Not run yet.\n")

    w("## 9. Transfer check (tasks never practiced)\n")
    trr = []
    for t in TRANSFER:
        for fl in ("en", "hi"):
            A, C = R.get(f"A|{t}|en|{fl}|r0"), R.get(f"C|{t}|en|{fl}|r0")
            if A or C: trr.append((t, fl, f"{A['score']:.3f}" if A else "-", f"{C['score']:.3f}" if C else "-", "yes" if A and A.get("reused_from") else "no"))
    w(table(["Task", "Files", "Baseline", "Tips", "Baseline reused from earlier run"], trr))

    w("## 10. Summary numbers from the analysis step\n")
    w("```json\n" + json.dumps({k: S.get(k) for k in ("n_matched_items", "A", "B", "C", "C_vs_A", "C_vs_B", "B_vs_A", "C_minus_A_rate_task_bootstrap_95",
                                                       "noise_rerun", "transfer", "rule", "tips_helped_by_prespecified_rule")}, indent=1) + "\n```\n")
    w("## 11. Where the raw evidence is\n")
    w(f"`rlharness/runs/{a.run}/`: `attempts.jsonl` (one record per attempt), `artifacts/<key>.result.csv` (the agent's output file), "
      "`artifacts/<key>.openclaw.json` (full OpenClaw transcript and tool log), `reflection_log.jsonl`, `tips.json`, `placebo.json`, "
      "`practice_report.json`, `run_manifest.json`, `summary.json`. Restore points: `rlharness/RESTORE.md`.\n")
    Path(a.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", a.out, f"({len(L)} blocks)")


if __name__ == "__main__":
    main()
