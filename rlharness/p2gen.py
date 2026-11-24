"""Seeded Phase 2 task generation WITHOUT touching upstream files.

Upstream authoring seeds every task with random.Random(<task id>), so each task has exactly one dataset.
Here random.Random is wrapped for the duration of a build so the seed string becomes '<task id>:<seed>'.
seed=None reproduces the frozen upstream tasks byte for byte (checked by `verify_identity`).
Every generated instance is re-validated with upstream's own build.check(): the solver must be
deterministic and ignoring ANY single rule must change the answer (so every rule stays necessary).
"""
from __future__ import annotations

import importlib
import json
import random
import threading
from contextlib import contextmanager
from pathlib import Path

from phase2.authoring.build import DOMAINS, check
from phase2.authoring.core import materialize

ROOT = Path(__file__).resolve().parent.parent
_RealRandom = random.Random
_GEN_LOCK = threading.Lock()  # seeded() patches a global; serialize all generation


@contextmanager
def seeded(seed):
    if seed is None:
        yield
        return

    class SeededRandom(_RealRandom):
        def __init__(self, x=None):
            super().__init__(f"{x}:{seed}")

    random.Random = SeededRandom
    try:
        yield
    finally:
        random.Random = _RealRandom


def generate(seed, domains=None):
    with _GEN_LOCK:
        return _generate(seed, domains)


def _generate(seed, domains=None):
    """Return ({task_id: frozen_task}, {task_id: error}) for one seed."""
    tasks, errors = {}, {}
    for domain in domains or DOMAINS:
        module = importlib.import_module(f"phase2.authoring.{domain}")
        for build in module.TASKS:
            with seeded(seed):
                try:
                    spec = build()
                    item = materialize(spec)
                    ablations = check(spec)
                    item["ablations"] = ablations
                    item["domain"] = domain
                    tasks[item["id"]] = item
                except Exception as e:  # a seed can make a rule vacuous; report, do not hide
                    errors[f"{domain}:{build.__name__}"] = f"{type(e).__name__}: {e}"[:200]
    return tasks, errors


def verify_identity():
    """seed=None must equal the frozen upstream JSON exactly (proves the patch is faithful)."""
    tasks, errors = generate(None)
    bad = []
    for domain in DOMAINS:
        frozen = json.loads((ROOT / "phase2" / "tasks" / f"{domain}.json").read_text(encoding="utf-8"))
        for f in frozen:
            g = tasks.get(f["id"])
            if g is None or any(g[k] != f[k] for k in ("answer", "files", "notice", "output", "goals")):
                bad.append(f["id"])
    return bad, errors


if __name__ == "__main__":
    bad, errs = verify_identity()
    print("identity mismatches:", bad, "| errors:", errs)
