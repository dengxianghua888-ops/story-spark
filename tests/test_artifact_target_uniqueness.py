"""One bundle must not silently choose between declarations for one output."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import storyforge_lib as lib
from generate_scene_batches import write_batch_outputs
from test_repair_failure_gates import prepare_final
from test_stage_safety import tree_bytes
from test_storyforge_runner import run_storyforge


def block(path, content, *, closed=True):
    return f"<<<FILE: {path}>>>\n{content}\n" + ("<<<END FILE>>>\n" if closed else "")


@pytest.mark.parametrize("paths", [
    ("draft.md", "draft.md"),
    ("./draft.md", "draft.md"),
    ("story/draft.md", "draft.md"),
    ("draft.md", "story/draft.md"),
    ("story/./draft.md", "./draft.md"),
    ("draft-scenes//scene-01.md", "draft-scenes/scene-01.md"),
    ("story/draft-scenes/./scene-01.md", "draft-scenes/scene-01.md"),
    ("story//draft.md", "story/draft.md"),
])
@pytest.mark.parametrize("second", ["keep the negation: no", "drop the negation: yes"])
def test_duplicate_declared_targets_are_rejected(paths, second):
    payload = block(paths[0], "keep the negation: no") + block(paths[1], second)
    with pytest.raises(ValueError, match="duplicate artifact target"):
        lib.parse_artifact_bundle(payload)


@pytest.mark.parametrize("closed", [(True, False), (False, True), (False, False)])
def test_incomplete_duplicate_headers_cannot_hide_ambiguity(closed):
    payload = block("draft.md", "first", closed=closed[0]) + block("story/draft.md", "second", closed=closed[1])
    with pytest.raises(ValueError, match="duplicate artifact target"):
        lib.parse_artifact_bundle(payload)


@pytest.mark.parametrize("paths", [
    ("a/draft.md", "b/draft.md"),
    ("draft.md", "Draft.md"),
    ("é.md", "e\u0301.md"),
])
def test_distinct_targets_keep_existing_identity_rules(paths):
    assert lib.parse_artifact_bundle(block(paths[0], "first") + block(paths[1], "second")) == {
        paths[0]: "first\n", paths[1]: "second\n"}


@pytest.mark.parametrize("closed", [True, False])
def test_single_prefixed_output_keeps_legacy_return_shape(closed):
    assert lib.parse_artifact_bundle(block("story/./draft.md", "正文。", closed=closed)) == {
        "story/draft.md": "正文。\n"}


@pytest.mark.parametrize("mode", ["v4", "production", "ultra_short", "production_v6"])
@pytest.mark.parametrize("alias", ["draft.md", "story/./draft.md"])
def test_standalone_apply_rejects_before_replacing_live_artifacts(tmp_path, mode, alias):
    story = tmp_path / "story"
    story.mkdir()
    (story / "source.md").write_text("synthetic source")
    (story / "draft.md").write_text("original draft")
    (story / "draft-scenes").mkdir()
    (story / "draft-scenes/old.md").write_text("original scene")
    before = tree_bytes(story)
    payload = block(alias, "first candidate") + block("draft.md", "second candidate")
    if mode != "v4":
        payload += block("draft-scenes/new.md", "new scene")
    bundle = tmp_path / "response.txt"
    bundle.write_text(payload)
    phase = lib.phase_for_role(mode, "scene")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/apply-artifact-bundle.py"),
        "--story", str(story), "--phase", str(phase), "--mode", mode,
        "--bundle", str(bundle), "--run-dir", str(story / "runs/apply")],
        capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "duplicate artifact target" in result.stderr
    assert tree_bytes(story) == before
    assert bundle.read_text() == payload
    report = json.loads((story / f"runs/apply/phase{phase}.parse-report.json").read_text())
    assert report["status"] == "failed"
    assert "duplicate artifact target" in report["error"]


@pytest.mark.parametrize("mode", ["production", "ultra_short", "production_v6"])
@pytest.mark.parametrize("alias", ["final.md", "story/./final.md"])
def test_mock_pipeline_rejects_ambiguity_and_retains_prior_snapshot(tmp_path, mode, alias):
    story, phase, fixtures, args = prepare_final(tmp_path, mode)
    env = {"STORYFORGE_MOCK_FIXTURE_DIR": str(fixtures)}
    good = run_storyforge(*args, env=env)
    assert good.returncode == 0, good.stdout + good.stderr
    before = tree_bytes(story)
    snapshot = story / f"runs/repair/phase{phase}.completed-snapshot.json"
    original_snapshot = snapshot.read_bytes()
    bundle = fixtures / f"phase{phase}.bundle.txt"
    ambiguous = block(alias, "Rejected alternative manuscript.") + bundle.read_text()
    bundle.write_text(ambiguous)
    result = run_storyforge(*args, env=env)
    assert result.returncode == 23, result.stdout + result.stderr
    assert tree_bytes(story) == before
    assert snapshot.read_bytes() == original_snapshot
    assert bundle.read_text() == ambiguous
    report = json.loads((story / f"runs/repair/phase{phase}.parse-report.json").read_text())
    assert report["status"] == "failed"
    assert "duplicate artifact target" in report["error"]
    manifest = json.loads((story / "runs/repair/run-manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert "duplicate artifact target" in manifest["last_failure"]


@pytest.mark.parametrize("alias", ["draft-scenes/scene-01.md", "./draft-scenes/scene-01.md",
                                    "story/draft-scenes/scene-01.md"])
def test_scene_writer_must_not_retry_duplicate_bundle_as_another_format(tmp_path, alias):
    story = tmp_path / "story"
    target = story / "draft-scenes/scene-01.md"
    target.parent.mkdir(parents=True)
    target.write_text("original scene")
    payload = block(alias, "first") + block("draft-scenes/scene-01.md", "second")
    with pytest.raises(ValueError, match="duplicate artifact target"):
        write_batch_outputs(story, ["draft-scenes/scene-01.md"], payload)
    assert target.read_text() == "original scene"


def test_scene_writer_keeps_unique_markdown_fallback(tmp_path):
    story = tmp_path / "story"
    story.mkdir()
    rel = "draft-scenes/scene-01.md"
    assert write_batch_outputs(story, [rel], f"[{rel}]\n```markdown\nunique prose\n```\n") == [rel]
    assert (story / rel).read_text() == "unique prose\n"


@pytest.mark.parametrize("invalid", ["../bad.md", "/bad.md"])
@pytest.mark.parametrize("position", [0, 1, 2])
def test_invalid_structured_path_cannot_hide_later_duplicates(tmp_path, invalid, position):
    story = tmp_path / "story"
    rel = "draft-scenes/scene-01.md"
    target = story / rel
    target.parent.mkdir(parents=True)
    target.write_text("original scene")
    pieces = [block(rel, "keep no"), block(rel, "drop yes")]
    pieces.insert(position, block(invalid, "invalid"))
    with pytest.raises(ValueError):
        write_batch_outputs(story, [rel], "".join(pieces))
    assert target.read_text() == "original scene"
    assert not (tmp_path / "bad.md").exists()


@pytest.mark.parametrize("alternate", [False, True])
def test_empty_structured_scene_is_not_rescued_by_fallback(tmp_path, alternate):
    story = tmp_path / "story"
    rel = "draft-scenes/scene-01.md"
    target = story / rel
    target.parent.mkdir(parents=True)
    target.write_text("original scene")
    payload = block(rel, "")
    if alternate:
        payload += f"[{rel}]\n```markdown\nalternate prose\n```\n"
    with pytest.raises(ValueError, match="artifact block is empty"):
        write_batch_outputs(story, [rel], payload)
    assert target.read_text() == "original scene"


@pytest.mark.parametrize("format", ["xml", "unclosed"])
def test_scene_writer_keeps_unique_xml_and_unclosed_inputs(tmp_path, format):
    story = tmp_path / "story"
    story.mkdir()
    rel = "draft-scenes/scene-01.md"
    payload = (f'<artifact path="{rel}">unique prose</artifact>' if format == "xml"
               else block(rel, "unique prose", closed=False))
    assert write_batch_outputs(story, [rel], payload) == [rel]
    assert (story / rel).read_text() == "unique prose\n"
