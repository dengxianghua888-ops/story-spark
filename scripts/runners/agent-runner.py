#!/usr/bin/env python3
"""Composite StoryForge runner for Codex/OpenClaw/Claude provider fallback."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from source_policy import SourceAccessDenied, require_source_access  # noqa: E402


def run(args: List[str], prompt: str | None = None, timeout: int = 1800, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd or Path.cwd(), input=prompt, text=True, capture_output=True, timeout=timeout)


def append_provider_sentinel(run_dir: Path, phase: int, provider: str, status: str, **extra: object) -> None:
    payload: Dict[str, object] = {
        "phase": phase,
        "provider": provider,
        "status": status,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    payload.update(extra)
    path = run_dir / f"phase{phase}.{provider}.provider.sentinel.log"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def result(
    phase: int,
    runner: str,
    provider: str,
    status: str,
    exit_code: int,
    command: str,
    started: float,
    output_bundle: Path,
    reason: str = "",
) -> Dict[str, object]:
    return {
        "phase": phase,
        "runner": runner,
        "provider": provider,
        "status": status,
        "exit_code": exit_code,
        "model_or_command": command,
        "duration_s": round(time.time() - started, 3),
        "output_bundle": str(output_bundle),
        "artifacts_written": [],
        "failure_reason": reason,
    }


def run_mock(args: argparse.Namespace, output_bundle: Path) -> Tuple[bool, Dict[str, object], str]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "runners" / "mock-runner.py"),
        "--story",
        args.story,
        "--phase",
        str(args.phase),
        "--prompt",
        args.prompt,
        "--run-dir",
        args.run_dir,
        "--mode",
        args.mode,
    ]
    completed = run(cmd)
    try:
        data = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        data = result(args.phase, "agent", "mock", "failed", completed.returncode, "mock-runner.py", time.time(), output_bundle, "mock runner returned invalid JSON")
    data["runner"] = "agent"
    return completed.returncode == 0 and data.get("status") == "success", data, completed.stdout + completed.stderr


def run_manual_pack(args: argparse.Namespace, output_bundle: Path) -> Tuple[bool, Dict[str, object], str]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "runners" / "manual-prompt-pack-runner.py"),
        "--story",
        args.story,
        "--phase",
        str(args.phase),
        "--prompt",
        args.prompt,
        "--run-dir",
        args.run_dir,
        "--mode",
        args.mode,
    ]
    completed = run(cmd)
    try:
        data = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        data = result(args.phase, "agent", "manual-prompt-pack", "failed", completed.returncode, "manual-prompt-pack", time.time(), output_bundle, "manual pack failed")
    data["runner"] = "agent"
    ok = completed.returncode == 0 and data.get("status") == "success"
    return ok, data, completed.stdout + completed.stderr


def run_codex(args: argparse.Namespace, prompt: str, output_bundle: Path) -> Tuple[bool, Dict[str, object], str]:
    started = time.time()
    if not shutil.which("codex"):
        data = result(args.phase, "agent", "codex", "failed", 127, "codex exec", started, output_bundle, "codex CLI not found")
        return False, data, ""
    last_message = Path(args.run_dir) / f"phase{args.phase}.codex.out"
    cmd = [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--ignore-user-config",
        "--cd",
        str(Path(args.run_dir).resolve()),
        "--skip-git-repo-check",
        "--output-last-message",
        str(last_message),
        "-",
    ]
    codex_options: List[str] = []
    if args.model:
        codex_options.extend(["--model", args.model])
    reasoning_effort = os.environ.get("STORYFORGE_CODEX_REASONING_EFFORT", "medium").strip()
    if reasoning_effort:
        codex_options.extend(["-c", f"model_reasoning_effort={json.dumps(reasoning_effort)}"])
    cmd[2:2] = codex_options
    completed = run(cmd, prompt=prompt, cwd=Path(args.run_dir).resolve())
    text = last_message.read_text(encoding="utf-8") if last_message.exists() else completed.stdout
    output_bundle.write_text(text, encoding="utf-8")
    ok = completed.returncode == 0 and output_bundle.read_text(encoding="utf-8").strip()
    data = result(
        args.phase,
        "agent",
        "codex",
        "success" if ok else "failed",
        completed.returncode,
        "codex exec",
        started,
        output_bundle,
        "" if ok else "codex returned no artifact bundle",
    )
    return ok, data, completed.stdout + completed.stderr


def run_claude(args: argparse.Namespace, prompt: str, output_bundle: Path) -> Tuple[bool, Dict[str, object], str]:
    started = time.time()
    if not shutil.which("claude"):
        data = result(args.phase, "agent", "claude", "failed", 127, "claude -p", started, output_bundle, "claude CLI not found")
        return False, data, ""
    cmd = ["claude", "--bare", "-p", "--output-format", "text",
           "--tools", "", "--disallowedTools", "mcp__*"]
    if args.model:
        cmd.extend(["--model", args.model])
    completed = run(cmd, prompt=prompt, cwd=Path(args.run_dir).resolve())
    output_bundle.write_text(completed.stdout, encoding="utf-8")
    ok = completed.returncode == 0 and completed.stdout.strip()
    data = result(
        args.phase,
        "agent",
        "claude",
        "success" if ok else "failed",
        completed.returncode,
        "claude -p",
        started,
        output_bundle,
        "" if ok else "claude returned no artifact bundle",
    )
    return ok, data, completed.stdout + completed.stderr


def run_openclaw(args: argparse.Namespace, prompt: str, output_bundle: Path) -> Tuple[bool, Dict[str, object], str]:
    started = time.time()
    if not shutil.which("openclaw"):
        data = result(args.phase, "agent", "openclaw", "failed", 127, "openclaw agent", started, output_bundle, "openclaw CLI not found")
        return False, data, ""
    cmd = ["openclaw", "agent", "--local", "--json", "--timeout", "1800", "--message", prompt]
    completed = run(cmd, cwd=Path(args.run_dir).resolve())
    text = completed.stdout
    try:
        payload = json.loads(completed.stdout)
        text = str(payload.get("reply") or payload.get("message") or payload.get("text") or completed.stdout)
    except json.JSONDecodeError:
        pass
    output_bundle.write_text(text, encoding="utf-8")
    ok = completed.returncode == 0 and text.strip()
    data = result(
        args.phase,
        "agent",
        "openclaw",
        "success" if ok else "failed",
        completed.returncode,
        "openclaw agent --local",
        started,
        output_bundle,
        "" if ok else "openclaw returned no artifact bundle",
    )
    return ok, data, completed.stdout + completed.stderr


PROVIDERS = {"codex": run_codex, "openclaw": run_openclaw, "claude": run_claude}

def provider_list(value: str, phase: int) -> List[str]:
    raw = value
    if not raw:
        raw = os.environ.get(f"STORYFORGE_AGENT_PROVIDER_PHASE_{phase}", "")
    if not raw:
        mapping_raw = os.environ.get("STORYFORGE_AGENT_ROLE_PROVIDER_MAP", "")
        if mapping_raw:
            try:
                mapping = json.loads(mapping_raw)
                raw = str(mapping.get(str(phase)) or mapping.get(phase) or "")
            except json.JSONDecodeError:
                raw = ""
    if not raw:
        raw = os.environ.get("STORYFORGE_AGENT_PROVIDER_PRIORITY", "codex,openclaw,claude,manual-prompt-pack")
    return [item.strip() for item in raw.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--story", required=True)
    parser.add_argument("--phase", required=True, type=int)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--providers", default="")
    parser.add_argument("--mode", default="v4")
    parser.add_argument("--source-story", default="", help="Live authorization path supplied by the trusted pipeline")
    args = parser.parse_args()

    prompt = Path(args.prompt).read_text(encoding="utf-8")
    run_dir = Path(args.run_dir)
    output_bundle = run_dir / f"phase{args.phase}.model.out"
    attempts = []
    last_data: Dict[str, object] | None = None
    selected_providers = provider_list(args.providers, args.phase)
    for provider in selected_providers:
        if provider in PROVIDERS:
            try:
                require_source_access(Path(args.story), provider)
                require_source_access(Path(args.source_story or args.story), provider)
            except SourceAccessDenied as exc:
                data = result(args.phase, "agent", provider, "failed", 30, provider,
                              time.time(), output_bundle, str(exc))
                data["source_access_denied"] = True
                attempts.append(data)
                append_provider_sentinel(run_dir, args.phase, provider, "blocked", reason=str(exc))
                last_data = data
                break
        provider_started = time.time()
        append_provider_sentinel(run_dir, args.phase, provider, "started", output_bundle=str(output_bundle))
        if provider == "mock":
            ok, data, log = run_mock(args, output_bundle)
        elif provider == "manual-prompt-pack":
            ok, data, log = run_manual_pack(args, output_bundle)
        else:
            runner = PROVIDERS.get(provider)
            if not runner:
                data = result(args.phase, "agent", provider, "failed", 10, provider, time.time(), output_bundle, "unknown provider")
                ok, log = False, ""
            else:
                ok, data, log = runner(args, prompt, output_bundle)
        attempts.append(data)
        (run_dir / f"phase{args.phase}.{provider}.provider.log").write_text(log, encoding="utf-8")
        append_provider_sentinel(
            run_dir,
            args.phase,
            provider,
            "ended",
            ok=ok,
            exit_code=data.get("exit_code"),
            duration_s=round(time.time() - provider_started, 3),
        )
        last_data = data
        if ok:
            output = dict(data)
            output["attempts"] = [dict(item) for item in attempts]
            output["selected_providers"] = selected_providers
            print(json.dumps(output, ensure_ascii=False))
            return 0

    if last_data is None:
        last_data = result(args.phase, "agent", "", "failed", 20, "agent", time.time(), output_bundle, "no providers configured")
    output = dict(last_data)
    output["attempts"] = [dict(item) for item in attempts]
    output["selected_providers"] = selected_providers
    print(json.dumps(output, ensure_ascii=False))
    return int(output.get("exit_code") or 20)


if __name__ == "__main__":
    sys.exit(main())
