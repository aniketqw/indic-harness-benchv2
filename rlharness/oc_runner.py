"""Run one task attempt through OpenClaw in Docker, pointed at the host's Ollama daemon.

Differences from the frozen study controller (documented, deliberate):
  - no relay / DPAPI keys: OpenClaw talks to the signed-in local Ollama (cloud model names);
  - tools limited to read/write/edit (no exec/process) because the container has host access;
  - workspace moved in/out as tar streams (no host bind mounts), grading done on the host.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from pathlib import Path

from rlharness.core import ROOT, grade, make_workspace

IMAGE = "ihb-agent:2026.9.7"
HOME_CFG = "/home/bench/.openclaw"


def config(model: str, temperature: float) -> dict:
    return {
        "models": {"mode": "replace", "providers": {"ollama": {
            "baseUrl": "http://rlh-proxy:11434/v1", "apiKey": "ollama", "api": "openai-completions",
            "models": [{"id": model, "name": model, "reasoning": True, "input": ["text"],
                        "contextWindow": 65536, "maxTokens": 4096,
                        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}]}}},
        "agents": {"defaults": {"workspace": "/workspace", "model": {"primary": "ollama/" + model, "fallbacks": []},
                                "models": {"ollama/" + model: {"params": {"temperature": temperature}}},
                                "thinkingDefault": "medium", "timeoutSeconds": 600, "skipBootstrap": True,
                                "compaction": {"memoryFlush": {"enabled": False}}, "sandbox": {"mode": "off"}}},
        "tools": {"allow": ["read", "write", "edit", "exec", "process"], "elevated": {"enabled": False},
                  "exec": {"host": "gateway", "security": "full", "ask": "off"}},
        "channels": {}, "plugins": {"enabled": False}, "browser": {"enabled": False},
        "update": {"checkOnStart": False}, "gateway": {"mode": "local", "bind": "loopback"},
    }


NET = "rlh-net"
PROXY = "rlh-proxy"
_infra_lock = threading.Lock()
_infra_ready = False


def ensure_infra() -> None:
    """Internal network (no internet) + allow-list proxy container bridging it to the host's Ollama."""
    global _infra_ready
    with _infra_lock:
        if _infra_ready:
            return
        if subprocess.run(["docker", "network", "inspect", NET], capture_output=True).returncode != 0:
            _sh(["docker", "network", "create", "--internal", "--label", "rlharness=1", NET])
        running = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", PROXY], capture_output=True)
        if running.stdout.strip() != b"true":
            subprocess.run(["docker", "rm", "-f", PROXY], capture_output=True)
            code = (Path(__file__).parent / "proxy.py").read_text()
            _sh(["docker", "run", "-d", "--name", PROXY, "--label", "rlharness=1", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "--memory", "256m", "--add-host", "host.docker.internal:host-gateway",
                 "--entrypoint", "python", IMAGE, "-c", code])
            _sh(["docker", "network", "connect", NET, PROXY])
            time.sleep(1.5)
        _infra_ready = True


def _sh(args, input_bytes=None, timeout=900) -> bytes:
    r = subprocess.run(args, input=input_bytes, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{args[:3]} failed: {r.stderr.decode('utf-8', 'replace')[-500:]}")
    return r.stdout


def _tar_dir(path: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for p in sorted(path.rglob("*")):
            t.add(p, arcname=str(p.relative_to(path)), recursive=False)
    return buf.getvalue()


def _hash_in(ws: Path):
    """Hash of everything under in/ (fixtures). None if in/ is missing (treated as no-signal)."""
    import hashlib
    d = ws / "in"
    if not d.exists():
        return None
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(d)).encode()); h.update(p.read_bytes())
    return h.hexdigest()


def _extract_safe(data: bytes, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for m in t.getmembers():
            name = Path(m.name)
            if name.is_absolute() or ".." in name.parts or not (m.isfile() or m.isdir()):
                continue  # drop links, devices, escapes
            t.extract(m, dest, filter="data")


def attempt(model: str, task: str, lang: str, lessons: list[str], temperature: float = 0.0, timeout: int = 600) -> dict:
    ensure_infra()
    ws = make_workspace(task)
    before = _hash_in(ws)
    name = "rlh-" + uuid.uuid4().hex[:10]
    prompt = (ROOT / "tasks" / task / "prompts" / lang / "prompt.txt").read_text(encoding="utf-8")
    if lessons:
        prompt = ("Lessons learned from earlier practice (apply them):\n" + "\n".join(f"- {l}" for l in lessons)
                  + "\n\n---\n\n" + prompt)
    t0 = time.time(); err = None; stdout = ""
    try:
        _sh(["docker", "create", "--name", name, "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
             "--memory", "3g", "--cpus", "2", "--pids-limit", "256",
             "--tmpfs", "/workspace:rw,uid=10001,gid=10001,mode=0770,size=512m", "--network", NET,
             "--label", "rlharness=1", IMAGE, "sleep", "1200"])
        _sh(["docker", "start", name])
        _sh(["docker", "exec", "-i", name, "tar", "-xf", "-", "-C", "/workspace", "--no-same-owner"], _tar_dir(ws))
        cfg_dir = Path(tempfile.mkdtemp()); (cfg_dir / "openclaw.json").write_text(json.dumps(config(model, temperature)))
        _sh(["docker", "exec", "-i", name, "sh", "-c", f"mkdir -p {HOME_CFG} && tar -xf - -C {HOME_CFG} --no-same-owner"],
            _tar_dir(cfg_dir)); shutil.rmtree(cfg_dir, ignore_errors=True)
        env = ["-e", f"OPENCLAW_CONFIG_PATH={HOME_CFG}/openclaw.json", "-e", f"OPENCLAW_STATE_DIR={HOME_CFG}",
               "-e", f"OPENCLAW_HOME={HOME_CFG}", "-e", "WORKSPACE=/workspace", "-e", "OPENCLAW_NO_AUTO_UPDATE=1"]
        try:
            out = subprocess.run(["docker", "exec", "-w", "/workspace", *env, name, "openclaw", "agent", "--local",
                                  "--session-id", "s-" + uuid.uuid4().hex[:8], "--timeout", str(timeout),
                                  "--thinking", "medium", "--json", "--message", prompt.replace("$WORKSPACE", "/workspace")],
                                 capture_output=True, timeout=timeout + 15)
            stdout = out.stdout.decode("utf-8", "replace")[-4000:]
            if out.returncode != 0:
                err = f"openclaw rc={out.returncode}: " + out.stderr.decode("utf-8", "replace")[-400:]
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
    after = _hash_in(ws)
    g = grade(task, ws)
    outs = {str(p.relative_to(ws)): p.read_text(encoding="utf-8", errors="replace")[:1500]
            for p in sorted((ws / "out").rglob("*")) if p.is_file()} if (ws / "out").exists() else {}
    shutil.rmtree(ws, ignore_errors=True)
    return {"task": task, "lang": lang, "score": g["score"], "checks": g["checks"], "elapsed": round(time.time() - t0, 1),
            "integrity_violation": before != after and after is not None,
            "error": err, "outputs": outs, "stdout_tail": stdout}
