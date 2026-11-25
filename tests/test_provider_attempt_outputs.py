"""Offline provider results must not impersonate a deliberate manual response."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import storyforge  # noqa: E402


@pytest.fixture
def agent():
    spec = importlib.util.spec_from_file_location("isolated_agent", ROOT / "scripts/runners/agent-runner.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def setup_dispatch(tmp_path):
    story = tmp_path / "story"
    story.mkdir()
    (story / "source.md").write_text("SYNTHETIC OWNED SOURCE", encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    prompt = run / "prompt.md"
    prompt.write_text("SYNTHETIC PROMPT", encoding="utf-8")
    return story, run, prompt


def dispatch(agent, monkeypatch, story, run, prompt, providers):
    argv = ["agent-runner.py", "--story", str(story), "--phase", "1",
            "--prompt", str(prompt), "--run-dir", str(run), "--providers", providers]
    monkeypatch.setattr(sys, "argv", argv)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        rc = agent.main()
    return rc, json.loads(output.getvalue().strip().splitlines()[-1])


def fake_provider(agent, monkeypatch, provider, *, exit_code=1, text="FAILED AUTOMATIC RESPONSE"):
    real_run = agent.run
    calls = []
    monkeypatch.setattr(agent.shutil, "which", lambda name: "/synthetic/" + name if name == provider else None)

    def run(cmd, **kwargs):
        if cmd[0] == provider:
            calls.append((cmd, kwargs))
            return subprocess.CompletedProcess(cmd, exit_code, text, "synthetic provider result")
        assert Path(cmd[1]).name == "manual-prompt-pack-runner.py", cmd
        return real_run(cmd, **kwargs)  # Only the local, offline manual runner.

    monkeypatch.setattr(agent, "run", run)
    return calls


@pytest.mark.parametrize("provider", ["codex", "claude", "openclaw"])
@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("exit_code,text", [(1, "FAILED AUTOMATIC RESPONSE"), (0, "")])
def test_failed_response_cannot_supply_or_overwrite_manual_input(
        tmp_path, monkeypatch, agent, provider, manual, exit_code, text):
    story, run, prompt = setup_dispatch(tmp_path)
    canonical = run / "phase1.model.out"
    manual_text = "DELIBERATE MANUAL RESPONSE"
    if manual:
        canonical.write_text(manual_text, encoding="utf-8")
    fake_provider(agent, monkeypatch, provider, exit_code=exit_code, text=text)
    rc, data = dispatch(agent, monkeypatch, story, run, prompt, provider + ",manual-prompt-pack")
    assert data["attempts"][0]["status"] == "failed"
    attempt_output = Path(data["attempts"][0]["output_bundle"])
    assert attempt_output.parent.parent == run
    assert attempt_output != canonical
    assert attempt_output.read_text(encoding="utf-8") == text
    started = json.loads((run / f"phase1.{provider}.provider.sentinel.log").read_text().splitlines()[0])
    assert started["output_bundle"] == str(attempt_output)
    if manual:
        assert rc == 0 and data["status"] == "success"
        assert canonical.read_text(encoding="utf-8") == manual_text
        assert data["model_or_command"] == "manual-existing-output"
    else:
        assert rc == 24 and data["status"] == "failed"
        assert not canonical.exists()
        assert (run / "manual-prompt-pack/phase1.todo.md").is_file()


@pytest.mark.parametrize("provider", ["codex", "claude", "openclaw"])
def test_success_returns_its_own_output_without_changing_manual_input(tmp_path, monkeypatch, agent, provider):
    story, run, prompt = setup_dispatch(tmp_path)
    canonical = run / "phase1.model.out"
    canonical.write_text("MANUAL INPUT", encoding="utf-8")
    fake_provider(agent, monkeypatch, provider, exit_code=0, text="FRESH SUCCESS")
    rc, data = dispatch(agent, monkeypatch, story, run, prompt, provider + ",manual-prompt-pack")
    assert rc == 0 and data["provider"] == provider
    assert Path(data["output_bundle"]).read_text(encoding="utf-8") == "FRESH SUCCESS"
    assert canonical.read_text(encoding="utf-8") == "MANUAL INPUT"
    assert len(data["attempts"]) == 1
    started = json.loads((run / f"phase1.{provider}.provider.sentinel.log").read_text().splitlines()[0])
    assert started["output_bundle"] == data["output_bundle"]


def test_repeated_codex_attempt_cannot_reuse_failed_last_message(tmp_path, monkeypatch, agent):
    story, run, prompt = setup_dispatch(tmp_path)
    real_run = agent.run
    destinations = []
    monkeypatch.setattr(agent.shutil, "which", lambda name: "/synthetic/" + name)

    def run_provider(cmd, **kwargs):
        if cmd[0] == "codex":
            output = Path(cmd[cmd.index("--output-last-message") + 1])
            assert not output.exists()
            destinations.append(output)
            if len(destinations) == 1:
                output.write_text("FAILED OLD OUTPUT", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 1, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        assert Path(cmd[1]).name == "manual-prompt-pack-runner.py"
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(agent, "run", run_provider)
    rc, data = dispatch(agent, monkeypatch, story, run, prompt, "codex,codex,manual-prompt-pack")
    assert rc == 24
    assert len(set(destinations)) == 2
    assert destinations[0].read_text(encoding="utf-8") == "FAILED OLD OUTPUT"
    assert not destinations[1].exists()
    assert [attempt["status"] for attempt in data["attempts"]] == ["failed"] * 3


def test_denied_source_does_not_create_attempt_or_call_provider(tmp_path, monkeypatch, agent):
    story, run, prompt = setup_dispatch(tmp_path)
    (story / "story.yaml").write_text("source_policy:\n  access: denied\n", encoding="utf-8")
    monkeypatch.setattr(agent, "run", lambda *a, **k: pytest.fail("provider called"))
    rc, data = dispatch(agent, monkeypatch, story, run, prompt, "codex,manual-prompt-pack")
    assert rc == 30 and data["source_access_denied"] is True
    assert not list(run.glob("phase1.codex-*"))


@pytest.mark.parametrize("manual", [False, True])
def test_default_fallback_pipeline_preserves_live_or_publishes_deliberate_manual(
        tmp_path, monkeypatch, agent, manual):
    story = tmp_path / "story"
    story.mkdir()
    (story / "source.md").write_text("SYNTHETIC OWNED SOURCE", encoding="utf-8")
    live = story / "dissection.md"
    live.write_text("PREVIOUS_REVIEWED_DISSECTION", encoding="utf-8")
    fixture = (ROOT / "tests/fixtures/mock-runs/phase1.bundle.txt").read_text(encoding="utf-8")
    # Use the actual default provider chain, with only one simulated provider available.
    for name in ("STORYFORGE_AGENT_PROVIDER_PRIORITY", "STORYFORGE_AGENT_PROVIDER_PHASE_1",
                 "STORYFORGE_AGENT_ROLE_PROVIDER_MAP"):
        monkeypatch.delenv(name, raising=False)
    fake_provider(agent, monkeypatch, "codex", exit_code=1, text=fixture)

    def run_dispatch(cmd, *args, **kwargs):
        output = io.StringIO()
        with monkeypatch.context() as local:
            local.setattr(sys, "argv", cmd[1:])
            with contextlib.redirect_stdout(output):
                rc = agent.main()
        return subprocess.CompletedProcess(cmd, rc, output.getvalue(), ""), {}

    monkeypatch.setattr(storyforge, "run_command_with_heartbeat", run_dispatch)
    args = storyforge.build_parser().parse_args([
        "run", "--story", str(story), "--runner", "agent", "--mode", "v4",
        "--run-id", "probe", "--to-phase", "1", "--max-retries", "0", "--no-human-gates"])
    assert storyforge.run_pipeline(args) != 0
    assert live.read_text(encoding="utf-8") == "PREVIOUS_REVIEWED_DISSECTION"
    canonical = story / "runs/probe/phase1.model.out"
    assert not canonical.exists()
    if manual:
        manual_fixture = fixture.replace("规则压迫后同规则反杀。", "MANUAL_REVIEWED_RESPONSE")
        canonical.write_text(manual_fixture, encoding="utf-8")
        assert storyforge.run_pipeline(args) == 0
        assert "MANUAL_REVIEWED_RESPONSE" in live.read_text(encoding="utf-8")
        assert canonical.read_text(encoding="utf-8") == manual_fixture
    manifest = json.loads((story / "runs/probe/run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == ("completed" if manual else "paused")
    attempts = manifest["phase_1_audit"]["attempts"]
    assert [a["provider"] for a in attempts] == ["codex", "openclaw", "claude", "manual-prompt-pack"]
    assert [a["status"] for a in attempts[:3]] == ["failed"] * 3
    assert attempts[-1]["status"] == ("success" if manual else "failed")
