"""Run one Phase 2 attempt through OpenClaw in Docker, graded with upstream's own grade_rows.

Settings mirror the Phase 2 study: high thinking, temperature 0, 32,768-token responses, 131,072-token
agent context, 1,200 s, read/write/edit/exec/process tools. Differences (documented): local signed-in Ollama via an
allow-list proxy instead of the Windows relay/key store; no durable accounting; grading on the host.
Tasks come from frozen upstream JSON (seed=None) or rlharness.p2gen (seed=int).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from phase2.grader import grade_rows
from phase2.suite import catalog, inputs, prompt

from rlharness.oc_runner import IMAGE, NET, _extract_safe, _sh, _tar_dir

PROXY2 = "rlh-proxy2"
MODELS = {"glm": "glm-5.3-flash:cloud", "nemotron": "nemotron-3-super:cloud"}
TIMEOUT = 1200
MAX_OUT = 512 * 1024
_lock = threading.Lock()
_ready = False
_frozen = None
_seeded = {}


def get_task(task_id: str, seed=None) -> dict:
    global _frozen
    if seed is None:
        if _frozen is None:
            _frozen = catalog()
        return _frozen[task_id]
    from rlharness.p2gen import generate
    with _lock:
        if (task_id, seed) not in _seeded:
            tasks, errors = generate(seed, [d for d in __import__('phase2.authoring.build', fromlist=['DOMAINS']).DOMAINS])
            for tid, item in tasks.items():
                _seeded[(tid, seed)] = item
            if task_id not in tasks:
                raise ValueError(f"{task_id} invalid for seed {seed}: {errors}")
        return _seeded[(task_id, seed)]


def parse_stats(stdout: str) -> dict:
    """Pull tool-call statistics and the final reply out of OpenClaw's --json output (best effort)."""
    import re
    stats = {}
    try:
        data = json.loads(stdout)
        stats["json_ok"] = True
        blob = json.dumps(data)
    except Exception:
        stats["json_ok"] = False
        blob = stdout
    for key, pat in (("tool_calls", r'"calls":\s*(\d+)'), ("tool_failures", r'"failures":\s*(\d+)')):
        m = re.search(pat, blob)
        if m:
            stats[key] = int(m.group(1))
    for key, pat in (("stop_reason", r'"stopReason":\s*"([^"]+)"'), ("finish_reason", r'"finishReason":\s*"([^"]+)"'),
                     ("disposition", r'"disposition":\s*"([^"]+)"')):
        m = re.search(pat, blob)
        if m:
            stats[key] = m.group(1)
    tools = re.search(r'"tools":\s*\[([^\]]*)\]', blob)
    if tools:
        stats["tools_used"] = sorted(set(re.findall(r'"([^"]+)"', tools.group(1))))
    texts = re.findall(r'"text":\s*"((?:[^"\\]|\\.){0,600})', blob)
    if texts:
        stats["final_reply"] = texts[-1][:600]
    for key in ("input", "output", "total", "inputTokens", "outputTokens", "totalTokens", "promptTokens", "completionTokens"):
        m = re.search(r'"%s":\s*(\d+)' % key, blob)
        if m:
            stats.setdefault("usage", {})[key] = int(m.group(1))
    return stats


def ensure_proxy2() -> None:
    global _ready
    with _lock:
        if _ready:
            return
        if subprocess.run(["docker", "network", "inspect", NET], capture_output=True).returncode != 0:
            _sh(["docker", "network", "create", "--internal", "--label", "rlharness=1", NET])
        up = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", PROXY2], capture_output=True)
        if up.stdout.strip() != b"true":
            subprocess.run(["docker", "rm", "-f", PROXY2], capture_output=True)
            code = (Path(__file__).parent / "proxy.py").read_text()
            _sh(["docker", "run", "-d", "--name", PROXY2, "--label", "rlharness=1", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "--memory", "256m",
                 "--add-host", "host.docker.internal:host-gateway", "--entrypoint", "python", IMAGE, "-c", code])
            _sh(["docker", "network", "connect", NET, PROXY2])
            time.sleep(1.5)
        _ready = True


def config(model: str, temperature: float = 0.0) -> dict:
    return {
        "models": {"mode": "replace", "providers": {"ollama": {
            "baseUrl": f"http://{PROXY2}:11434/v1", "apiKey": "ollama", "api": "openai-completions",
            "timeoutSeconds": TIMEOUT, "models": [{"id": model, "name": model, "reasoning": True, "input": ["text"],
                "contextWindow": 131072, "maxTokens": 32768,
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}]}}},
        "agents": {"defaults": {"workspace": "/workspace", "model": {"primary": "ollama/" + model, "fallbacks": []},
                                "models": {"ollama/" + model: {"params": {"temperature": temperature}}},
                                "thinkingDefault": "high", "timeoutSeconds": TIMEOUT, "skipBootstrap": True,
                                "compaction": {"memoryFlush": {"enabled": False}}, "sandbox": {"mode": "off"}}},
        "tools": {"allow": ["read", "write", "edit", "exec", "process"], "elevated": {"enabled": False},
                  "exec": {"host": "gateway", "security": "full", "ask": "off"}},
        "channels": {}, "plugins": {"enabled": False}, "browser": {"enabled": False},
        "update": {"checkOnStart": False}, "gateway": {"mode": "local", "bind": "loopback"},
    }


def grade_workspace(task: dict, files: dict, ws: Path) -> dict:
    """Host-side copy of phase2.grader.score (same logic, workspace path passed explicitly)."""
    contract = {"columns": task["output"], "expected": task["answer"], "key_columns": task["key_columns"],
                "numeric": task["numeric"], "forbidden_keys": task["forbidden_keys"]}
    sha = {n: hashlib.sha256(d).hexdigest() for n, d in files.items()}
    intact = all((ws / n).is_file() and hashlib.sha256((ws / n).read_bytes()).hexdigest() == h for n, h in sha.items())
    res = {"score": 0.0, "full_completion": False, "input_intact": intact}
    sub = ws / "out/result.csv"
    if not sub.is_file() or sub.stat().st_size > MAX_OUT:
        return {**res, "reason": "output_missing_or_oversized"}
    try:
        reader = csv.reader(io.StringIO(sub.read_text(encoding="utf-8-sig"), newline=""), strict=True)
        header = [v.strip() for v in next(reader, [])]
        rows = [r for r in reader if r]
    except (UnicodeError, csv.Error):
        return {**res, "reason": "invalid_csv_or_encoding"}
    g = grade_rows(contract, header, rows)
    wrong, wrong_total = [], 0
    missing_rows = []
    if not g.get("full_completion") and "row_checks" in g:
        kc, cols = task["key_columns"], task["output"]
        exp = {":".join(str(v).strip() for v in r[:kc]): r for r in task["answer"]}
        act = {":".join(v.strip() for v in r[:kc]): r for r in rows}
        missing_rows = [k for k in exp if k not in act][:100]
        for key, cc in g["row_checks"].items():
            for col, ok in cc.items():
                if not ok:
                    wrong_total += 1
                    if len(wrong) < 300:
                        i = cols.index(col)
                        wrong.append({"key": key, "column": col, "expected": str(exp[key][i])[:40] if key in exp else None,
                                      "actual": act[key][i][:40] if key in act and i < len(act[key]) else None})
    return {**res, **g, "wrong": wrong, "wrong_total": wrong_total, "missing_rows": missing_rows, "score": g["score"] if intact else 0.0, "full_completion": intact and g["full_completion"]}


def attempt(model_key: str, task_id: str, plang: str, flang: str, seed=None, lessons=None, temperature: float = 0.0) -> dict:
    ensure_proxy2()
    model = MODELS[model_key]
    task = get_task(task_id, seed)
    files = inputs(task, flang)
    text = prompt(task, plang)
    if lessons:
        text = ("Lessons learned from earlier practice (apply them):\n" + "\n".join(f"- {l}" for l in lessons)
                + "\n\n---\n\n" + text)
    ws = Path(tempfile.mkdtemp(prefix="p2ws_"))
    for name, data in files.items():
        (ws / name).parent.mkdir(parents=True, exist_ok=True); (ws / name).write_bytes(data)
    (ws / "out").mkdir(exist_ok=True)
    name = "rlh2-" + uuid.uuid4().hex[:10]
    t0 = time.time(); err = None; tail = ""; full_out = ""
    try:
        _sh(["docker", "create", "--name", name, "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
             "--memory", "3g", "--cpus", "2", "--pids-limit", "256",
             "--tmpfs", "/workspace:rw,uid=10001,gid=10001,mode=0770,size=512m", "--network", NET,
             "--label", "rlharness=1", IMAGE, "sleep", str(TIMEOUT + 300)])
        _sh(["docker", "start", name])
        _sh(["docker", "exec", "-i", name, "tar", "-xf", "-", "-C", "/workspace", "--no-same-owner"], _tar_dir(ws))
        cfg = Path(tempfile.mkdtemp()); (cfg / "openclaw.json").write_text(json.dumps(config(model, temperature)))
        home = "/home/bench/.openclaw"
        _sh(["docker", "exec", "-i", name, "sh", "-c", f"mkdir -p {home} && tar -xf - -C {home} --no-same-owner"],
            _tar_dir(cfg)); shutil.rmtree(cfg, ignore_errors=True)
        env = ["-e", f"OPENCLAW_CONFIG_PATH={home}/openclaw.json", "-e", f"OPENCLAW_STATE_DIR={home}",
               "-e", f"OPENCLAW_HOME={home}", "-e", "WORKSPACE=/workspace", "-e", "OPENCLAW_NO_AUTO_UPDATE=1"]
        try:
            out = subprocess.run(["docker", "exec", "-w", "/workspace", *env, name, "openclaw", "agent", "--local",
                                  "--session-id", "s-" + uuid.uuid4().hex[:8], "--timeout", str(TIMEOUT),
                                  "--thinking", "high", "--json", "--message", text],
                                 capture_output=True, timeout=TIMEOUT + 30)
            full_out = out.stdout.decode("utf-8", "replace")[-300000:]
            tail = full_out[-3000:]
            if out.returncode != 0:
                err = f"openclaw rc={out.returncode}: " + out.stderr.decode("utf-8", "replace")[-300:]
        except subprocess.TimeoutExpired:
            err = "timeout"
        data = _sh(["docker", "exec", name, "tar", "-c", "-C", "/workspace", "."])
        shutil.rmtree(ws, ignore_errors=True); ws.mkdir(parents=True)
        _extract_safe(data, ws)
    except Exception as e:
        err = (err or "") + f" harness_error: {e}"
    finally:
        if os.environ.get("RLH_KEEP"):
            print("kept container", name)
        else:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    g = grade_workspace(task, files, ws)
    res_full = (ws / "out/result.csv").read_text(encoding="utf-8", errors="replace")[:MAX_OUT] if (ws / "out/result.csv").is_file() else ""
    res = res_full[:1500]
    shutil.rmtree(ws, ignore_errors=True)
    return {"model": model_key, "task": task_id, "seed": seed, "plang": plang, "flang": flang,
            "score": g["score"] / 100.0, "full": g["full_completion"], "reason": g.get("reason"),
            "input_intact": g["input_intact"], "wrong": g.get("wrong", []), "wrong_total": g.get("wrong_total", 0), "missing_rows": g.get("missing_rows", []),
            "extra_keys_list": g.get("extra_keys", [])[:100], "prompt_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "stats": parse_stats(full_out), "stdout_full": full_out, "result_full": res_full, "extra_keys": len(g.get("extra_keys", [])),
            "integrity_violation": not g["input_intact"], "elapsed": round(time.time() - t0, 1),
            "error": err, "result_head": res, "stdout_tail": tail}
