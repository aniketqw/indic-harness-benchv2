"""Minimal tool-loop agent + task loader + oracle grading for the RL-harness pilot.

Deliberately NOT OpenClaw: a 3-tool loop (read_file / write_file / list_dir) against
Ollama Cloud models via the local Ollama daemon. Baseline and lesson-augmented runs
use this same loop, so comparisons inside the pilot are fair; absolute numbers are
NOT comparable with the published 300-condition OpenClaw results.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "harnessbench" / "tasks"
PROMPTS = ROOT / "tasks"
OLLAMA = "http://localhost:11434/api/chat"
MAX_TURNS = 20  # study protocol allows 30 requests; keep headroom for the pilot
LANGS = ("en", "hi", "hinglish")

TOOLS = [
    {"type": "function", "function": {"name": "read_file", "description": "Read a UTF-8 text file in the workspace.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Create or overwrite a UTF-8 file in the workspace (parent dirs are created).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "list_dir", "description": "List files under a workspace directory (recursive).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]

SYSTEM = ("You are a careful office/engineering agent working in a sandbox workspace. "
          "Use the tools to read inputs and write the required output files. "
          "Paths are relative to the workspace root (e.g. in/data.json, out/report.md). "
          "When all required files are written, reply with a short final message.")


def load_prompt(task: str, lang: str) -> str:
    text = (PROMPTS / task / "prompts" / lang / "prompt.txt").read_text(encoding="utf-8")
    return text.replace("$WORKSPACE/", "").replace("$WORKSPACE", ".")


def make_workspace(task: str) -> Path:
    w = Path(tempfile.mkdtemp(prefix=f"rlh_{task[:3]}_"))
    fx = VENDOR / task / "fixtures"
    if fx.is_dir():
        shutil.copytree(fx, w, dirs_exist_ok=True)
    (w / "in").mkdir(exist_ok=True)
    (w / "out").mkdir(exist_ok=True)
    return w


def _safe(w: Path, rel: str) -> Path:
    p = (w / rel).resolve()
    if w.resolve() not in p.parents and p != w.resolve():
        raise ValueError("path escapes workspace")
    return p


def run_tool(w: Path, name: str, args: dict) -> str:
    try:
        if name == "read_file":
            return _safe(w, args["path"]).read_text(encoding="utf-8", errors="replace")[:60000]
        if name == "write_file":
            p = _safe(w, args["path"]); p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"], encoding="utf-8"); return f"wrote {len(args['content'])} chars to {args['path']}"
        if name == "list_dir":
            base = _safe(w, args.get("path", "."))
            return "\n".join(str(p.relative_to(w)) for p in sorted(base.rglob("*")) if p.is_file()) or "(empty)"
        return f"unknown tool {name}"
    except Exception as e:  # tool errors are observations, not crashes
        return f"ERROR: {e}"


def chat(model: str, messages: list, temperature: float, seed: int | None, tools=True, retries=4, num_predict=4096) -> dict:
    body = {"model": model, "messages": messages, "stream": False,
            "options": {"temperature": temperature, "num_predict": num_predict}}
    if seed is not None:
        body["options"]["seed"] = seed
    if tools:
        body["tools"] = TOOLS
    if model.startswith("gpt-oss"):
        body["think"] = "medium"  # matches the study's reasoning_effort
    delay = 3
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == retries:
                raise RuntimeError(f"ollama call failed: {e}")
            time.sleep(delay); delay *= 2


def grade(task: str, w: Path) -> dict:
    d = VENDOR / task
    sys.path.insert(0, str(d))
    try:
        spec = importlib.util.spec_from_file_location(f"oracle_{task.replace('-', '_')}", d / "oracle_grade.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        res = mod.score_workspace(w)
    finally:
        sys.path.remove(str(d))
    checks = [{"id": c.get("id"), "label": c.get("label"), "pass": bool(c.get("pass")), "weight": c.get("weight")}
              for c in res.get("checks", [])]
    return {"score": float(res.get("outcome_score", 0.0)), "checks": checks}


def rollout(model: str, task: str, lang: str, lessons: list[str], temperature: float, seed: int | None) -> dict:
    w = make_workspace(task)
    sys_msg = SYSTEM
    if lessons:
        sys_msg += "\n\nLessons learned from earlier practice (apply them):\n" + "\n".join(f"- {l}" for l in lessons)
    messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": load_prompt(task, lang)}]
    trace, tin, tout, err = [], 0, 0, None
    try:
        for _ in range(MAX_TURNS):
            r = chat(model, messages, temperature, seed)
            m = r["message"]; tin += r.get("prompt_eval_count", 0); tout += r.get("eval_count", 0)
            messages.append({k: v for k, v in m.items() if k in ("role", "content", "tool_calls", "thinking")})
            calls = m.get("tool_calls") or []
            if not calls:
                break
            for c in calls:
                fn = c["function"]; args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except Exception: args = {}
                out = run_tool(w, fn["name"], args)
                trace.append({"tool": fn["name"], "args": {k: (str(v)[:80]) for k, v in args.items()}, "err": out.startswith("ERROR")})
                messages.append({"role": "tool", "tool_name": fn["name"], "content": out})
        else:
            err = "turn_limit"
    except Exception as e:
        err = str(e)
    g = grade(task, w)
    files = {str(p.relative_to(w)): p.read_text(encoding="utf-8", errors="replace")[:1500]
             for p in sorted((w / "out").rglob("*")) if p.is_file()}
    shutil.rmtree(w, ignore_errors=True)
    return {"task": task, "lang": lang, "score": g["score"], "checks": g["checks"], "turns": len(trace),
            "tokens_in": tin, "tokens_out": tout, "error": err, "trace": trace, "outputs": files,
            "final": messages[-1].get("content", "")[:400]}
