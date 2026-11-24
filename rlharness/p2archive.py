"""Create a restore point for an experiment: tarball of the local run folder (with checksums) outside the repo,
plus a git tag on the current commit.

Usage: PYTHONPATH=. python3.13 -B -X utf8 -m rlharness.p2archive --run p2_exp1 --tag exp1-final
The tarball goes to <repo parent>/rl-archive/ (outside Git: it holds full transcripts). Nothing is deleted or overwritten:
the archive name contains the timestamp, and an existing tag is never moved unless --move-tag is given.
"""
import argparse
import hashlib
import subprocess
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent


def sha256(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run", default="p2_exp1"); ap.add_argument("--tag", default="")
    ap.add_argument("--move-tag", action="store_true"); a = ap.parse_args()
    src = HERE / "runs" / a.run
    if not src.exists():
        raise SystemExit(f"no such run folder: {src}")
    dest = REPO.parent / "rl-archive"; dest.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tarpath = dest / f"{a.run}_{stamp}.tar.gz"
    with tarfile.open(tarpath, "w:gz") as t:
        t.add(src, arcname=a.run)
    (dest / f"{a.run}_{stamp}.sha256").write_text(f"{sha256(tarpath)}  {tarpath.name}\n")
    print("archived:", tarpath, f"({tarpath.stat().st_size / 1e6:.1f} MB)")
    if a.tag:
        exists = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{a.tag}"], cwd=REPO, capture_output=True).returncode == 0
        if exists and not a.move_tag:
            print(f"tag {a.tag} already exists; not moved (use --move-tag)")
        else:
            subprocess.run(["git", "tag", "-f", a.tag], cwd=REPO, check=True)
            print(f"tag {a.tag} -> {subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=REPO, capture_output=True, text=True).stdout.strip()}")
            print("push it with: git push origin refs/tags/" + a.tag)


if __name__ == "__main__":
    main()
