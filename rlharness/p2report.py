"""Build rlharness/REPORT.md from the recorded experiment data (no hand-typed numbers).

Usage: PYTHONPATH=. python3.13 -B -X utf8 -m rlharness.p2report --run p2_exp1 [--out rlharness/REPORT.md]
Reads runs/<run>/{summary.json, tips.json, placebo.json, practice_report.json, ablation.json?, run_manifest.json}.
The section marked INTERPRETATION is written by hand after the numbers are seen.
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).parent

ARCHITECTURE = (
    "We improve the harness around a frozen model, not the model. GLM-5.3-Flash runs each Phase 2 job in OpenClaw "
    "inside a network-isolated Docker box, and the upstream grader scores every output cell. Best-versus-worst "
    "practice attempts on seeded task variants yield at most eight tips, which are prepended to prompts and "
    "tested against plain and filler baselines."
)


def load(p, default=None):
    return json.loads(p.read_text()) if p.exists() else default


def pct(a, n):
    return f"{a} of {n} ({100 * a / n:.0f}%)" if n else "n/a"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run", default="p2_exp1"); ap.add_argument("--out", default=str(HERE / "REPORT.md"))
    a = ap.parse_args(); d = HERE / "runs" / a.run
    S = load(d / "summary.json"); M = load(d / "run_manifest.json", {}); P = load(d / "practice_report.json", [])
    ABL = load(d / "ablation.json"); tips = load(d / "tips.json", []); placebo = load(d / "placebo.json", [])
    if not S or not S.get("n_matched_items"):
        raise SystemExit("summary.json missing or empty: run the analysis first")
    n = S["n_matched_items"]
    L = []
    w = L.append
    w("# Report: runtime tips for a frozen agent harness (Phase 2, GLM-5.3-Flash)\n")
    w(f"Generated from `rlharness/runs/{a.run}` (commit `{M.get('git_commit', '?')[:7]}`, started {M.get('started', '?')}). "
      "Plan: [`EXPERIMENT_PLAN.md`](EXPERIMENT_PLAN.md).\n")
    w("## 1. Architecture (in brief)\n")
    w(ARCHITECTURE + f"  ({len(ARCHITECTURE.split())} words)\n")
    w("## 2. Results\n")
    w(f"Primary test: {n} matched items of {S['n_primary_items']} (8 headroom tasks x 3 prompt languages x 2 file languages, "
      "frozen upstream instances, never used in practice). Fully correct = every field right.\n")
    w("| Arm | Prompt gets | Fully correct | Mean field score |\n|---|---|---|---|")
    for arm, name in (("A", "task only (baseline)"), ("B", "task + filler of equal length"), ("C", "task + learned tips")):
        w(f"| {arm} | {name} | {pct(S[arm]['fully_correct'], n)} | {S[arm]['mean_score']:.3f} |")
    ca, cb, ba = S["C_vs_A"], S["C_vs_B"], S["B_vs_A"]
    w(f"\nPaired changes in fully-correct status (items that became right / became wrong / unchanged): "
      f"C vs A **{ca['better']} / {ca['worse']} / {ca['same']}**; C vs B {cb['better']} / {cb['worse']} / {cb['same']}; "
      f"B vs A {ba['better']} / {ba['worse']} / {ba['same']}.\n")
    lo, hi = S["C_minus_A_rate_task_bootstrap_95"]
    w(f"Task-clustered bootstrap, 95% interval for the change in fully-correct rate, C minus A: **{lo:+.2f} to {hi:+.2f}** "
      "(8 tasks, so wide).\n")
    nz = S["noise_rerun"]
    w(f"Run-to-run noise: re-running the baseline on {nz['n']} items changed fully-correct status on "
      f"{nz['full_status_changed']} of them (mean absolute score change {nz['mean_abs_score_change']}).\n")
    tr = S["transfer"]
    w(f"Safety check on 4 tasks never practiced ({tr['n']} items): baseline fully correct {tr['A_full']}, with tips {tr['C_full']}.\n")
    w("By file language (fully correct, A / B / C):\n")
    w("| File language | n | A | B | C |\n|---|---|---|---|---|")
    for fl, v in S["by_file_language"].items():
        w(f"| {fl} | {v['n']} | {v['A']} | {v['B']} | {v['C']} |")
    w("\nBy task (fully correct out of 6, A / B / C):\n")
    w("| Task | A | B | C |\n|---|---|---|---|")
    for t, v in S["by_task"].items():
        w(f"| {t} | {v['A']} | {v['B']} | {v['C']} |")
    w("\n### Pre-specified decision rule\n")
    for k, v in S["rule"].items():
        w(f"- {'PASS' if v else 'FAIL'}: {k.replace('_', ' ')}")
    w(f"\n**Verdict by the rule fixed in advance: {'tips helped' if S['tips_helped_by_prespecified_rule'] else 'tips did NOT clear the bar (null result)'}.**\n")
    w("## 3. Why we got these results (evidence)\n")
    w("**Controls.** The filler arm (B) shows what extra prompt text alone does; the noise re-run shows what chance alone does. "
      f"Filler changed {ba['better'] + ba['worse']} items; the tips changed {ca['better'] + ca['worse']}; chance changed {nz['full_status_changed']} of {nz['n']}.\n")
    w("**Failure types (items per arm):**\n")
    cats = sorted({c for arm in "ABC" for c in S["failure_taxonomy"][arm]})
    w("| Type | A | B | C |\n|---|---|---|---|")
    for c in cats:
        w(f"| {c} | " + " | ".join(str(S["failure_taxonomy"][arm].get(c, 0)) for arm in "ABC") + " |")
    mw = S["mean_wrong_fields"]
    w(f"\nMean wrong fields per item: A {mw['A']}, B {mw['B']}, C {mw['C']}.\n")
    ae = S["agent_effort"]
    w("Agent effort (mean per item): " + "; ".join(f"{arm}: {v['mean_elapsed_s']} s, {v['mean_tool_calls']} tool calls, {v['mean_tool_failures']} tool failures" for arm, v in ae.items()) + ".\n")
    fd = S["field_delta_C_vs_A"]
    w(f"**Field level.** With tips, {fd['fields_fixed']} fields went from wrong to right and {fd['fields_broken']} from right to wrong. "
      f"Columns most often fixed: {fd['columns_most_fixed'] or 'none'}. Columns most often broken: {fd['columns_most_broken'] or 'none'}.\n")
    if S["flipped_items"]:
        w("**Items whose status flipped:**\n")
        w("| Task | Prompt | Files | A score | B score | C score | A full | C full |\n|---|---|---|---|---|---|---|---|")
        for f in S["flipped_items"]:
            w(f"| {f['task']} | {f['plang']} | {f['flang']} | {f['A_score']} | {f['B_score']} | {f['C_score']} | {f['A_full']} | {f['C_full']} |")
        w("")
    w("**The tips** (learned by practice only; never shown the test instances):\n")
    for i, t in enumerate(tips):
        w(f"{i + 1}. {t}")
    w(f"\n**The filler** (same length): {' '.join(placebo)}\n")
    if P:
        w("**Where the tips came from** (practice groups, scores of the 4 attempts each; empty = no spread, nothing learned):\n")
        w("| Task | Files | Practice scores | Tips written |\n|---|---|---|---|")
        for g in P:
            w(f"| {g['task']} | {g['flang']} | {g['scores']} | {len(g.get('tips', []))} |")
        w("")
    if ABL:
        w("**Causal check, leave-one-tip-out** (items the tips fixed, re-run with one tip removed):\n")
        w("| Tip | Items | Lost full marks when removed |\n|---|---|---|")
        for r in ABL["per_tip"]:
            w(f"| {r['tip'][:90]} | {r['n']} | {r['lost_full_when_removed']} |")
        w("")
    w("## 4. Interpretation (written after the numbers)\n")
    w("<!-- INTERPRETATION -->\n")
    w("## 5. Limits\n")
    w("- 8 headroom tasks, one model, one practice pass: a small, pre-specified test, not a general claim.\n"
      "- Tips were learned on seeded variants of the same tasks, so the main test measures in-task generalization; the 8-item transfer check is only a safety check.\n"
      "- Our harness differs from the published relay and accounting stack; all comparisons are within our own harness.\n"
      "- Temperature 0 on a cloud model is not fully deterministic; the noise re-run measures this.\n"
      "- Tasks and translations are AI-authored (upstream caveat); no claim about Indian languages in general.\n")
    w("## 6. Where the evidence is\n")
    w(f"Raw attempts, every output CSV, every OpenClaw transcript, reflector prompts and responses, and the run manifest are in "
      f"`rlharness/runs/{a.run}/` (local). Compact committed copies: `rlharness/results/phase2-experiment-1/`.\n")
    Path(a.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", a.out, "words in architecture:", len(ARCHITECTURE.split()))


if __name__ == "__main__":
    main()
