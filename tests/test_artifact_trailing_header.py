"""A response interrupted inside its next FILE opener must not replace a bundle."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from storyforge_lib import apply_artifact_bundle, parse_artifact_bundle  # noqa: E402


def block(path, content, newline="\n"):
    return newline.join([f"<<<FILE: {path}>>>", content, "<<<END FILE>>>", ""])


@pytest.mark.parametrize("fragment", [
    "<<<F",
    "<<<FI",
    "<<<FIL",
    "<<<FILE",
    "<<<FILE:",
    "<<<FILE: draft-scenes/scene-03.md",
    "<<<FILE: draft-scenes/scene-03.md>",
    "<<<FILE: draft-scenes/scene-03.md>>",
])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_partial_opener_is_not_ignored_after_a_complete_block(fragment, newline):
    payload = block("draft.md", "synthetic draft", newline) + newline + fragment + newline
    with pytest.raises(ValueError, match="FILE header truncated"):
        parse_artifact_bundle(payload)


def test_partial_opener_does_not_publish_wildcard_outputs(tmp_path):
    story = tmp_path / "story"
    scenes = story / "draft-scenes"
    scenes.mkdir(parents=True)
    before = {f"draft-scenes/scene-0{i}.md": f"saved synthetic scene {i}\n".encode() for i in (1, 2, 3)}
    before["draft.md"] = b"saved synthetic draft\n"
    for rel, content in before.items():
        (story / rel).write_bytes(content)
    payload = (
        block("draft-scenes/scene-01.md", "replacement one")
        + block("draft-scenes/scene-02.md", "replacement two")
        + block("draft.md", "replacement draft")
        + "<<<FILE: draft-scenes/scene-03.md>>"
    )
    with pytest.raises(ValueError, match="FILE header truncated"):
        apply_artifact_bundle(story, 5, payload, story / "runs" / "synthetic", root=ROOT, mode="production")
    assert {path.relative_to(story).as_posix(): path.read_bytes()
            for path in [*scenes.glob("*.md"), story / "draft.md"]} == before


def test_fragment_like_text_inside_a_closed_multiline_body_is_literal():
    text = "A synthetic explanation.\n<<<FILE: illustrative fragment>>\n\nParagraph two."
    payload = block("draft.md", text) + block("draft-scenes/scene-01.md", "another complete block")
    assert parse_artifact_bundle(payload) == {
        "draft.md": text + "\n",
        "draft-scenes/scene-01.md": "another complete block\n",
    }


def test_single_legacy_unclosed_output_preserves_multiline_body():
    text = "A synthetic explanation.\n\nParagraph two.\n<<<FILE: illustrative fragment>>"
    assert parse_artifact_bundle("<<<FILE: story/draft.md>>>\n" + text) == {"story/draft.md": text + "\n"}


def test_unreserved_trailing_prose_keeps_existing_compatibility():
    payload = block("draft.md", "synthetic draft") + "Example: <<<FILE: part of an explanation\n<<<"
    assert parse_artifact_bundle(payload) == {"draft.md": "synthetic draft\n"}
