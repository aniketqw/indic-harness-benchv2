"""Export compact, committable copies of run results from the git-ignored runs/ folder to results/.

Usage (re-run any time; it overwrites the exports for the runs listed):
  PYTHONPATH=. python3.13 -B -X utf8 -m rlharness.export_results
Keeps only analysis fields (no transcripts, no model output). Writes per run: attempts.csv, attempts.jsonl, summary.json.
"""
import csv
import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).parent
RUNS = HERE / "runs"
OUT = HERE / "results"

# run folder -> (label, kind)
RUNS_TO_EXPORT = {
    "oc_base1": ("phase1-openclaw-gptoss-baseline", "p1"),
    "p2_base1": ("phase2-openclaw-baseline", "p2"),
}
P1_FIELDS = ["key", "task", "lang", "score", "elapsed", "error", "integrity_violation"]
P2_FIELDS = ["key", "model", "task", "plang", "flang", "score", "full", "reason", "input_intact",
             "extra_keys", "elapsed", "error"]


def load(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def agg(sel):
    if not sel:
        return {"n": 0}
    return {"n": len(sel), "mean_score": round(st.mean(r["score"] for r in sel), 4),
            "full": sum(1 for r in sel if r.get("full")),
            "no_file": sum(1 for r in sel if r.get("reason") == "output_missing_or_oversized")}


def export_experiment(run="p2_exp1", label="phase2-experiment-1"):
    """Compact committed copy of the experiment: attempts (no transcripts), summary, tips, manifest, ablation."""
    src = RUNS / run
    rows = load(src / "attempts.jsonl")
    if not rows:
        print(f"{run}: no attempts yet, skipped"); return
    d = OUT / label; d.mkdir(parents=True, exist_ok=True)
    fields = ["key", "arm", "task", "plang", "flang", "score", "full", "reason", "wrong_total", "extra_keys", "elapsed",
              "input_intact", "lessons_n", "temperature", "error", "reused_from", "retried", "ts"]
    compact = []
    for r in rows:
        c = {k: r.get(k) for k in fields}
        c["tool_calls"] = (r.get("stats") or {}).get("tool_calls"); c["tool_failures"] = (r.get("stats") or {}).get("tool_failures")
        c["stop_reason"] = (r.get("stats") or {}).get("stop_reason")
        compact.append(c)
    cols = list(compact[0].keys())
    with (d / "attempts.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(compact)
    (d / "attempts.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in compact) + "\n")
    for name in ("summary.json", "tips.json", "placebo.json", "practice_report.json", "ablation.json", "run_manifest.json", "seeds.json"):
        if (src / name).exists():
            (d / name).write_text((src / name).read_text())
    print(f"{run}: exported {len(rows)} attempts -> results/{label}/")


def main():
    for run, (label, kind) in RUNS_TO_EXPORT.items():
        rows = load(RUNS / run / "attempts.jsonl")
        if not rows:
            print(f"{run}: no attempts yet, skipped"); continue
        fields = P1_FIELDS if kind == "p1" else P2_FIELDS
        d = OUT / label; d.mkdir(parents=True, exist_ok=True)
        compact = [{k: r.get(k) for k in fields} for r in rows]
        with (d / "attempts.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(compact)
        (d / "attempts.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in compact) + "\n")
        dims = ("task", "lang") if kind == "p1" else ("model", "plang", "flang", "task")
        summ = {"run": run, "attempts": len(rows), "overall": agg(rows)}
        for dim in dims:
            summ[dim] = {v: agg([r for r in rows if r[dim] == v]) for v in sorted({r[dim] for r in rows})}
        if kind == "p2":
            summ["model_x_flang"] = {f"{m}|{fl}": agg([r for r in rows if r["model"] == m and r["flang"] == fl])
                                     for m in sorted({r["model"] for r in rows}) for fl in ("en", "hi")}
        (d / "summary.json").write_text(json.dumps(summ, indent=1, ensure_ascii=False))
        print(f"{run}: exported {len(rows)} attempts -> results/{label}/")
    export_experiment()


if __name__ == "__main__":
    main()
