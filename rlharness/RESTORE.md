# Restore points and how to go back

Everything about experiment 1 can be restored from three places.

## 1. Git (code, plans, reports, compact results)
Repository: <https://github.com/aniketqw/indic-harness-benchv2>, branch `rl-harness`. Tags mark milestones:

| Tag | Meaning |
|---|---|
| `exp1-launch` | code and plan exactly as the experiment was launched (before any results) |
| `exp1-final` | created when the final report is written (code, REPORT.md, DEEP_ANALYSIS.md, compact results) |

Go back to a milestone without losing anything: `git checkout exp1-launch` (look around), then `git checkout rl-harness` to return.
To restore a single file from a milestone: `git checkout exp1-launch -- rlharness/EXPERIMENT_PLAN.md`.
Nothing is ever force-deleted; every earlier version of every file is in `git log`.

## 2. Local archive (raw evidence; too large and too sensitive for Git)
`p0/rl-archive/p2_exp1_<timestamp>.tar.gz` plus a `.sha256` file, made by `rlharness/p2archive.py`. It contains every attempt record,
every output CSV, every OpenClaw transcript, the reflector's prompts and responses, the manifest and the summary.
Restore: `tar -xzf p0/rl-archive/<file>.tar.gz -C rlharness/runs/` and verify with `shasum -a 256 -c <file>.sha256`.

## 3. Compact results committed to Git
`rlharness/results/phase2-experiment-1/` (attempt table without transcripts, summary, tips, filler, practice report, manifest, ablation).

## Older artifacts kept on purpose
- `rlharness/archive_thin/`: the first, thinly-logged launch (2 reused rows only; superseded).
- `rlharness/results/phase1-openclaw-gptoss-baseline/`, `phase2-openclaw-baseline/`: partial self-run plain baselines, stopped on purpose.
