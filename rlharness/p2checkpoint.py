"""Periodic checkpointing for a running experiment (local, unattended-safe: it never pushes or deletes anything of yours).

Every INTERVAL seconds, if the attempt log has grown, it writes
  <repo parent>/rl-archive/checkpoints/<run>_<timestamp>.tar.gz  (+ .sha256)   a full snapshot of runs/<run>/
  runs/<run>/checkpoint_status.json                              counts by stage, last attempt time, errors
and keeps only the newest KEEP snapshots (it only ever deletes its own old checkpoint files in that folder).

Usage: PYTHONPATH=. python3.13 -B -X utf8 -u -m rlharness.p2checkpoint --run p2_exp1 --interval 1200 --keep 8
"""
import argparse
import collections
import hashlib
import json
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent


def status(run_dir):
    rows = [json.loads(l) for l in (run_dir / "attempts.jsonl").read_text().splitlines() if l.strip()] if (run_dir / "attempts.jsonl").exists() else []
    stages = collections.Counter(("practice" if r["key"].startswith("prac|") else r["key"].split("|")[0]) for r in rows)
    return {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "attempts_recorded": len(rows), "by_stage": dict(stages),
            "errors": sum(1 for r in rows if r.get("error")), "fully_correct": sum(1 for r in rows if r.get("full")),
            "last_attempt_ts": max((r.get("ts", "") for r in rows), default=""),
            "tips_written": (run_dir / "tips.json").exists(), "ablation_done": (run_dir / "ablation.json").exists()}


def snapshot(run, run_dir, dest, keep):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tarpath = dest / f"{run}_{stamp}.tar.gz"
    with tarfile.open(tarpath, "w:gz") as t:
        t.add(run_dir, arcname=run)
    h = hashlib.sha256(tarpath.read_bytes()).hexdigest()
    (dest / f"{run}_{stamp}.sha256").write_text(f"{h}  {tarpath.name}\n")
    mine = sorted(dest.glob(f"{run}_*.tar.gz"))
    for old in mine[:-keep]:  # only this script's own old checkpoints
        old.unlink(missing_ok=True); old.with_suffix("").with_suffix(".sha256").unlink(missing_ok=True)
    return tarpath


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run", default="p2_exp1"); ap.add_argument("--interval", type=int, default=1200)
    ap.add_argument("--keep", type=int, default=8); a = ap.parse_args()
    run_dir = HERE / "runs" / a.run
    dest = REPO.parent / "rl-archive" / "checkpoints"; dest.mkdir(parents=True, exist_ok=True)
    last = -1
    while True:
        try:
            st = status(run_dir)
            (run_dir / "checkpoint_status.json").write_text(json.dumps(st, indent=1))
            if st["attempts_recorded"] != last or st["tips_written"]:
                p = snapshot(a.run, run_dir, dest, a.keep); last = st["attempts_recorded"]
                print(f"[{st['time']}] checkpoint {p.name} ({p.stat().st_size / 1e6:.1f} MB), attempts={last}, errors={st['errors']}", flush=True)
        except Exception as e:  # never let the checkpointer die quietly
            print("checkpoint error:", e, flush=True)
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
