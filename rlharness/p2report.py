"""Build the SHORT final rlharness/REPORT.md from the recorded experiment (no hand-typed numbers).

Usage: PYTHONPATH=. python3.13 -B -X utf8 -m rlharness.p2report --run p2_exp1 [--out rlharness/REPORT.md]
Heavy tables and full evidence go to DEEP_ANALYSIS.md (see p2deep.py). The INTERPRETATION block is written by hand.
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
    S = load(d / "summary.json"); M = load(d / "run_manifest.json", {}); ABL = load(d / "ablation.json"); tips = load(d / "tips.json", [])
    if not S or not S.get("n_matched_items"):
        raise SystemExit("summary.json missing or empty: run the analysis first")
    n = S["n_matched_items"]; ca, cb, ba = S["C_vs_A"], S["C_vs_B"], S["B_vs_A"]; nz = S["noise_rerun"]; tr = S["transfer"]
    L = []; w = L.append
    w("# Report: runtime tips for a frozen agent harness (Phase 2, GLM-5.3-Flash)\n")
    w(f"Run `{a.run}`, code commit `{M.get('git_commit', '?')[:7]}`, started {M.get('started', '?')}. "
      "Full evidence: [`DEEP_ANALYSIS.md`](DEEP_ANALYSIS.md). Plan: [`EXPERIMENT_PLAN.md`](EXPERIMENT_PLAN.md).\n")
    w("## 1. Architecture\n")
    w(ARCHITECTURE + f"  *({len(ARCHITECTURE.split())} words)*\n")
    w("## 2. Results\n")
    w(f"{n} matched items ({S['n_primary_items']} planned): 8 tasks where GLM had room to improve x 3 prompt languages x 2 file languages, "
      "real benchmark instances never used in practice. \"Fully correct\" means every field is right.\n")
    w("| Arm | Prompt contains | Fully correct | Mean field score |\n|---|---|---|---|")
    for arm, name in (("A", "task only (baseline)"), ("B", "task + filler text of equal length"), ("C", "task + learned tips")):
        w(f"| {arm} | {name} | {pct(S[arm]['fully_correct'], n)} | {S[arm]['mean_score']:.3f} |")
    lo, hi = S["C_minus_A_rate_task_bootstrap_95"]
    w(f"\n- Items that became right / became wrong / unchanged, tips vs baseline: **{ca['better']} / {ca['worse']} / {ca['same']}**.")
    w(f"- Tips vs filler: {cb['better']} / {cb['worse']} / {cb['same']}. Filler vs baseline: {ba['better']} / {ba['worse']} / {ba['same']}.")
    w(f"- 95% interval for the change in fully-correct rate (tips minus baseline, resampling the 8 tasks): {lo:+.2f} to {hi:+.2f}.")
    w(f"- Chance: re-running the baseline on {nz['n']} items changed {nz['full_status_changed']} of them.")
    w(f"- Never-practiced tasks ({tr['n']} items): baseline {tr['A_full']} fully correct, with tips {tr['C_full']}.\n")
    w("| File language | Items | Baseline | Filler | Tips |\n|---|---|---|---|---|")
    for fl, v in S["by_file_language"].items():
        w(f"| {fl} | {v['n']} | {v['A']} | {v['B']} | {v['C']} |")
    w("\n**Verdict by the rule fixed before the run:** " + ("tips helped.\n" if S["tips_helped_by_prespecified_rule"] else "tips did NOT clear the bar (null result).\n"))
    for k, v in S["rule"].items():
        w(f"- {'PASS' if v else 'FAIL'}: {k.replace('_', ' ')}")
    w("\n## 3. Why (key evidence; details in the deep analysis)\n")
    w(f"- **Not just extra text:** filler changed {ba['better'] + ba['worse']} items, tips changed {ca['better'] + ca['worse']}.")
    w(f"- **Not just chance:** {nz['full_status_changed']} of {nz['n']} baseline items changed on a plain re-run.")
    mw = S["mean_wrong_fields"]
    w(f"- **Fewer wrong fields:** mean wrong fields per item: baseline {mw['A']}, filler {mw['B']}, tips {mw['C']}.")
    fd = S["field_delta_C_vs_A"]
    w(f"- **Which fields:** {fd['fields_fixed']} fields went wrong to right, {fd['fields_broken']} right to wrong; most-fixed columns: {fd['columns_most_fixed'] or 'none'}.")
    if ABL:
        nec = [r for r in ABL["per_tip"] if r["lost_full_when_removed"] > 0]
        w(f"- **Causal check:** removing a single tip cost full marks on some fixed item for {len(nec)} of {len(ABL['per_tip'])} tips "
          f"({'; '.join(f'tip {i + 1}: {r['lost_full_when_removed']}/{r['n']}' for i, r in enumerate(ABL['per_tip']))}).")
    w("- **The tips:**")
    for i, t in enumerate(tips):
        w(f"  {i + 1}. {t}")
    w("\n## 4. Interpretation\n")
    w("<!-- INTERPRETATION -->\n")
    w("## 5. Limits\n")
    w("Small, pre-specified test: 8 tasks, one model, one practice pass. Tips were learned on variants of the same tasks, so the main "
      "test measures in-task generalization (the 8-item transfer check is only a safety check). Our harness differs from the published "
      "relay stack, so all comparisons are within our own harness. Cloud models at temperature 0 are not fully deterministic. "
      "Tasks and translations are AI-authored (upstream caveat).\n")
    w("## 6. Where everything is\n")
    w("- This file: the final result. [`DEEP_ANALYSIS.md`](DEEP_ANALYSIS.md): every table and the evidence behind section 3.\n"
      f"- Raw evidence, local: `rlharness/runs/{a.run}/` (every output CSV, every transcript, reflector prompts and responses, manifest).\n"
      "- Compact committed copy: `rlharness/results/phase2-experiment-1/`. Archive and restore points: see `rlharness/RESTORE.md`.\n")
    Path(a.out).write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", a.out, "| architecture words:", len(ARCHITECTURE.split()))


if __name__ == "__main__":
    main()
