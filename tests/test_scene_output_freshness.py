"""Synthetic runner output must belong to this invocation, not a reused run ID."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_scene_batch_safety import artifacts, invoke, make_story, model, PROSE, report
from storyforge_lib import write_text

ROOT = Path(__file__).resolve().parents[1]


def bundle(sid="scene-02", prose=PROSE):
    return f"<<<FILE: draft-scenes/{sid}.md>>>\n{prose}\n<<<END FILE>>>\n"


def seed_old_outputs(story, *, repair=False):
    suffix = ".repair1" if repair else ""
    path = story / "runs/test" / f"batch01{suffix}.codex.out"
    write_text(path, bundle())
    return path, path.read_bytes()


@pytest.mark.parametrize("old", [False, True])
@pytest.mark.parametrize("stdout", ["", "not an artifact bundle"])
def test_silent_or_invalid_invocation_never_uses_previous_output(tmp_path, monkeypatch, old, stdout):
    story = make_story(tmp_path)
    prior = seed_old_outputs(story) if old else None
    before = artifacts(story)
    seen = []

    def silent(prompt, output, *args):
        seen.append(output)
        return subprocess.CompletedProcess([], 0, stdout, "")

    with pytest.raises(SystemExit, match="failed validation"):
        invoke(monkeypatch, story, silent, "--start-at", "2")
    assert artifacts(story) == before
    assert report(story)["status"] == "failed"
    assert len(seen) == 1 and not seen[0].exists()
    if prior:
        assert prior[0].read_bytes() == prior[1]
        assert seen[0] != prior[0]


@pytest.mark.parametrize("old", [False, True])
@pytest.mark.parametrize("channel", ["file", "stdout"])
def test_current_response_publishes_and_retains_prior_bytes(tmp_path, monkeypatch, old, channel):
    story = make_story(tmp_path)
    prior = seed_old_outputs(story) if old else None
    # Same bytes remain legitimate when freshly returned; no mtime/digest heuristic.
    payload = bundle()
    seen = []

    def fresh(prompt, output, *args):
        seen.append(output)
        if channel == "file":
            write_text(output, payload)
        return subprocess.CompletedProcess([], 0, payload if channel == "stdout" else "", "")

    assert invoke(monkeypatch, story, fresh, "--start-at", "2") == 0
    assert report(story)["status"] == "success"
    recorded = ROOT / report(story)["batches"][0]["attempts"][0]["output_path"]
    assert recorded.resolve() == seen[0].resolve()
    if channel == "file":
        assert recorded.read_text() == payload
    if prior:
        assert prior[0].read_bytes() == prior[1]
        assert seen[0] != prior[0]


def test_previous_repair_response_cannot_rescue_silent_retry(tmp_path, monkeypatch):
    story = make_story(tmp_path)
    prior, prior_bytes = seed_old_outputs(story, repair=True)
    before = artifacts(story)
    seen = []

    def retry(prompt, output, *args):
        seen.append(output)
        if len(seen) == 1:
            write_text(output, "invalid first attempt")
        return subprocess.CompletedProcess([], 0, "", "")

    with pytest.raises(SystemExit, match="failed validation"):
        invoke(monkeypatch, story, retry, "--start-at", "2", "--retries", "1")
    assert len(seen) == 2 and len(set(seen)) == 2
    assert artifacts(story) == before
    assert prior.read_bytes() == prior_bytes
    attempts = report(story)["batches"][0]["attempts"]
    assert [item["status"] for item in attempts] == ["fail", "fail"]


def test_reused_successful_run_gets_distinct_output_destinations(tmp_path, monkeypatch):
    story = make_story(tmp_path)
    seen = []

    def fresh(prompt, output, *args):
        seen.append(output)
        return model()(prompt, output, *args)

    assert invoke(monkeypatch, story, fresh, "--start-at", "2") == 0
    first_bytes = seen[0].read_bytes()
    assert invoke(monkeypatch, story, fresh, "--start-at", "2") == 0
    assert len(set(seen)) == 2
    assert seen[0].read_bytes() == first_bytes
    assert seen[1].read_bytes() == first_bytes


def test_silent_rerun_after_real_success_fails_without_republishing(tmp_path, monkeypatch):
    story = make_story(tmp_path)
    assert invoke(monkeypatch, story, model(), "--start-at", "2") == 0
    before = artifacts(story)
    previous_report = report(story)
    previous_output = ROOT / previous_report["batches"][0]["attempts"][0]["output_path"]
    response_bytes = previous_output.read_bytes()

    def silent(*args):
        return subprocess.CompletedProcess([], 0, "", "")

    with pytest.raises(SystemExit, match="failed validation"):
        invoke(monkeypatch, story, silent, "--start-at", "2")
    assert artifacts(story) == before
    assert report(story)["status"] == "failed"
    assert previous_output.read_bytes() == response_bytes


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "empty_file"])
def test_failure_keeps_prior_output_and_live_story(tmp_path, monkeypatch, failure):
    story = make_story(tmp_path)
    prior, prior_bytes = seed_old_outputs(story)
    before = artifacts(story)

    def fail(prompt, output, *args):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("synthetic runner", 1)
        write_text(output, "" if failure == "empty_file" else bundle())
        return subprocess.CompletedProcess([], 3 if failure == "nonzero" else 0, bundle(), "")

    with pytest.raises((SystemExit, subprocess.TimeoutExpired)):
        invoke(monkeypatch, story, fail, "--start-at", "2")
    assert artifacts(story) == before
    assert prior.read_bytes() == prior_bytes
    assert report(story)["status"] == "failed"


@pytest.mark.parametrize("channel", ["silent", "file", "stdout"])
def test_actual_split_cli_uses_only_current_synthetic_provider_output(tmp_path, channel):
    story = make_story(tmp_path)
    prior, prior_bytes = seed_old_outputs(story)
    before = artifacts(story)
    provider = tmp_path / "bin/codex"
    payload = bundle()
    write_text(provider, f"#!{sys.executable}\n"
        "import sys\nfrom pathlib import Path\n"
        "output = Path(sys.argv[sys.argv.index('--output-last-message') + 1])\n"
        f"Path({str(tmp_path / 'invocation.json')!r}).write_text(__import__('json').dumps({{'output':str(output)}}))\n"
        + (f"output.write_text({payload!r})\n" if channel == "file" else
           f"sys.stdout.write({payload!r})\n" if channel == "stdout" else ""))
    provider.chmod(0o700)
    result = subprocess.run([sys.executable, str(ROOT / "scripts/generate_scene_batches.py"),
        "--story", str(story), "--run-id", "test", "--retries", "0", "--start-at", "2",
        "--no-human-gates"], capture_output=True, text=True,
        env={**os.environ, "PATH": str(provider.parent) + os.pathsep + os.environ.get("PATH", "")})
    assert (result.returncode == 0) is (channel != "silent"), result.stdout + result.stderr
    assert report(story)["status"] == ("failed" if channel == "silent" else "success")
    if channel == "silent":
        assert artifacts(story) == before
    assert prior.read_bytes() == prior_bytes
    invocation = json.loads((tmp_path / "invocation.json").read_text())
    assert Path(invocation["output"]) != prior
