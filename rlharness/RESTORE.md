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

## If something goes down mid-run (resume recipe)
Every finished attempt is appended to `rlharness/runs/p2_exp1/attempts.jsonl` immediately (with its output file and transcript in
`artifacts/`). A restart **skips finished attempts**; only attempts that were in flight are lost.
1. Make sure Docker Desktop is running (`docker info`) and Ollama is running (`curl localhost:11434/api/version`).
   The allow-list proxy container is recreated automatically.
2. Re-run the stage that was running (from the repo root):
   - practice stage: `PYTHONPATH=. python3.13 -B -X utf8 -u -m rlharness.p2exp --run p2_exp1 --workers 7 --stage practice`
   - arms stage:     `PYTHONPATH=. python3.13 -B -X utf8 -u -m rlharness.p2exp --run p2_exp1 --workers 7 --stage arms`
3. If the run folder itself was damaged, restore the newest checkpoint (see below), verify it, and run step 2:
   `ls -t p0/rl-archive/checkpoints/` then `tar -xzf p0/rl-archive/checkpoints/<file>.tar.gz -C rlharness/runs/` and
   `shasum -a 256 -c p0/rl-archive/checkpoints/<file>.sha256`.
4. Optional afterwards: `python3.13 -m rlharness.p2exp --run p2_exp1 --stage ablate` (leave-one-tip-out), then
   `python3.13 -m rlharness.p2report` and `python3.13 -m rlharness.p2deep` (run with `PYTHONPATH=.`).

Automatic checkpoints: `rlharness/p2checkpoint.py` snapshots `runs/p2_exp1/` every 20 minutes when the log has grown, into
`p0/rl-archive/checkpoints/` (newest 8 kept; it only deletes its own old checkpoints). Status: `runs/p2_exp1/checkpoint_status.json`.
It never pushes to Git; I commit compact results to the branch at milestones.
