"""Six-scene synthetic counterexamples; no claims about literary quality."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_scene_batches import prompt_for_batch, repair_prompt_for_batch
from scene_context import (
    ContextError,
    build_context,
    encoded,
    scene_order,
    source_evidence,
)
from storyforge_lib import render_phase_prompt


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value, encoding="utf-8")


@pytest.fixture
def story(tmp_path):
    texts = ["阿青拿着钥匙，答应归还信件。", "阿青把钥匙交给阿白。", "众人误以为阿青是内鬼。", "阿白离开城镇，钥匙已销毁。", "内鬼真实身份是老周。", "阿青归还了信件。"]
    for i, text in enumerate(texts, 1):
        sid = f"scene-{i:02d}"
        write(tmp_path / "scene-cards" / f"{sid}.json", {"scene_id": sid, "plan": f"第{i}场计划", "target_chars_min": 100, "target_chars_max": 200})
        write(tmp_path / "draft-scenes" / f"{sid}.md", text)
    write(tmp_path / "source.md", "用于离线测试的合成原文。")
    write(tmp_path / "analysis/style-dna.md", "短句")
    write(tmp_path / "beat-bible.json", {"chapters": [{"twist": "GLOBAL_FUTURE_SECRET"}], "mechanisms": ["GLOBAL_FUTURE_SECRET"]})
    entries = []

    def add(i, entity, field, value, kind="state"):
        sid = f"scene-{i:02d}"
        source = source_evidence(tmp_path, sid)
        source["quote"] = texts[i - 1]
        entries.append({"id": f"entry-{len(entries)}", "status": "accepted", "reviewed_by": "synthetic-editor", "entity_id": entity, "field": field, "value": value, "kind": kind, "valid_from_scene": sid, "source": source})
    add(1, "key", "holder", "阿青")
    add(1, "letter", "promise", {"status": "open", "text": "归还信件"}, "debt")
    add(2, "key", "holder", "阿白")
    add(3, "crowd", "belief", "阿青是内鬼（未经证实）")
    add(4, "white", "location", "已离城")
    add(4, "key", "holder", "已销毁")
    add(5, "traitor", "identity", "老周")
    add(6, "letter", "promise", {"status": "resolved", "text": "已归还信件"}, "debt")
    entries.extend([{"status": "candidate", "value": "CANDIDATE_SECRET"}, {"status": "rejected", "value": "REJECTED_SECRET"}])
    write(tmp_path / "continuity-ledger.json", {"schema_version": 1, "entries": entries})
    return tmp_path


def ledger(story):
    return json.loads((story / "continuity-ledger.json").read_text())


def state(context, entity, field):
    return next(f["value"] for f in context["accepted_facts"] if f["entity_id"] == entity and f["field"] == field)


def test_six_scene_position_and_reveal(story):
    second = build_context(story, "scene-02")
    assert state(second, "key", "holder") == "阿青"
    assert "老周" not in encoded(second)
    assert state(build_context(story, "scene-03"), "key", "holder") == "阿白"
    fifth = build_context(story, "scene-05")
    assert state(fifth, "key", "holder") == "已销毁"
    assert state(fifth, "white", "location") == "已离城"
    assert "老周" not in encoded(fifth)
    sixth = build_context(story, "scene-06")
    assert state(sixth, "traitor", "identity") == "老周"
    assert len(sixth["open_debts"]) == 1  # Scene 6 hasn't happened at its start.
    assert "CANDIDATE_SECRET" not in encoded(sixth)
    assert "REJECTED_SECRET" not in encoded(sixth)
    # A seventh position lets the six-scene completed promise become visible.
    write(story / "scene-cards/scene-07.json", {"scene_id": "scene-07"})
    assert build_context(story, "scene-07")["open_debts"] == []


def test_previous_edit_invalidates_later_evidence_without_state_resurrection(story):
    before = build_context(story, "scene-05")
    assert state(before, "key", "holder") == "已销毁"
    write(story / "draft-scenes/scene-02.md", "钥匙转交事件已改稿。")
    with pytest.raises(ContextError, match="stale"):
        build_context(story, "scene-05")
    assert state(build_context(story, "scene-02"), "key", "holder") == "阿青"


def test_prefix_detects_unreferenced_previous_scene_edit(story):
    data = ledger(story)
    data["entries"] = [e for e in data["entries"] if e.get("source", {}).get("scene_id") != "scene-02"]
    write(story / "continuity-ledger.json", data)
    write(story / "draft-scenes/scene-02.md", "未被单条事实引用的前场也已改变")
    with pytest.raises(ContextError, match="stale"):
        build_context(story, "scene-05")


def test_future_edit_does_not_change_earlier_context(story):
    before = build_context(story, "scene-02")
    write(story / "draft-scenes/scene-05.md", "新反转")
    assert build_context(story, "scene-02") == before


def test_prompt_and_repair_use_projection_and_omit_global_future(story):
    batch = [story / "scene-cards/scene-02.json"]
    initial = prompt_for_batch(story, batch, 2, 6)
    repaired = repair_prompt_for_batch(story, batch, ["draft-scenes/scene-02.md"], ["too short"], "failed draft", 1)
    for prompt in (initial, repaired):
        assert "accepted_facts" in prompt and "prefix_sha256" in prompt
        assert "老周" not in prompt and "GLOBAL_FUTURE_SECRET" not in prompt
        assert "CANDIDATE_SECRET" not in prompt
    with pytest.raises(ContextError, match="one scene"):
        prompt_for_batch(story, batch + [story / "scene-cards/scene-05.json"], 1, 1)


@pytest.mark.parametrize("mode,phase", [("production", 5), ("production_v6", 6), ("v4", 3)])
def test_full_stage_cannot_bypass_position_isolation(story, mode, phase):
    with pytest.raises(ValueError, match="position-isolated"):
        render_phase_prompt(story, phase, ROOT, mode)


def test_no_ledger_legacy_prompt_still_runs(story):
    (story / "continuity-ledger.json").unlink()
    batch = [story / "scene-cards/scene-02.json", story / "scene-cards/scene-05.json"]
    assert "GLOBAL_FUTURE_SECRET" in prompt_for_batch(story, batch, 1, 1)
    assert build_context(story, "scene-02")["warnings"]
    assert build_context(story, "scene-02")["accepted_facts"] == []


def test_budget_never_drops_hard_facts(story):
    full = build_context(story, "scene-06")
    # Force enough removable excerpt with an unchanged reviewed source.
    text = "内鬼真实身份是老周。" * 1000
    write(story / "draft-scenes/scene-05.md", text)
    data = ledger(story)
    for entry in data["entries"]:
        if entry.get("source", {}).get("scene_id") == "scene-05":
            entry["source"] = {**source_evidence(story, "scene-05"), "quote": "内鬼真实身份是老周。"}
    write(story / "continuity-ledger.json", data)
    clipped = build_context(story, "scene-06", max_chars=6000)
    assert len(encoded(clipped)) <= 6000
    assert len(clipped["accepted_facts"]) == len(full["accepted_facts"])
    assert clipped["budget"]["trimmed"] and clipped["budget"]["hard_facts_dropped"] == 0
    with pytest.raises(ContextError, match="budget too small"):
        build_context(story, "scene-06", max_chars=100)


@pytest.mark.parametrize("mutation", ["hash", "quote", "reviewer", "duplicate", "outside", "effective"])
def test_invalid_accepted_evidence_is_never_silently_downgraded(story, mutation):
    data = ledger(story)
    first = data["entries"][0]
    if mutation == "hash":
        first["source"]["sha256"] = "0" * 64
    elif mutation == "quote":
        first["source"]["quote"] = "not in draft"
    elif mutation == "reviewer":
        first.pop("reviewed_by")
    elif mutation == "duplicate":
        data["entries"].append(copy.deepcopy(first))
    elif mutation == "outside":
        first["source"]["scene_id"] = "../other-story/scene-01"
    elif mutation == "effective":
        first["valid_from_scene"] = "scene-999"
    write(story / "continuity-ledger.json", data)
    with pytest.raises(ContextError):
        build_context(story, "scene-02")


def test_symlink_cannot_read_other_story(story, tmp_path_factory):
    external = tmp_path_factory.mktemp("other") / "source.md"
    external.write_text("private")
    path = story / "draft-scenes/scene-01.md"
    path.unlink()
    path.symlink_to(external)
    with pytest.raises(ContextError, match="escapes"):
        build_context(story, "scene-02")


def test_numeric_order_and_alias_rejection(tmp_path):
    for sid in ("scene-1", "scene-10", "scene-2"):
        write(tmp_path / "scene-cards" / f"{sid}.json", {"scene_id": sid})
    assert scene_order(tmp_path) == ["scene-1", "scene-2", "scene-10"]
    write(tmp_path / "scene-cards/scene-01.json", {"scene_id": "scene-01"})
    with pytest.raises(ContextError, match="ambiguous"):
        scene_order(tmp_path)


def test_hash_is_stable_and_projection_is_read_only(story):
    before = {str(p.relative_to(story)): p.read_bytes() for p in story.rglob("*") if p.is_file()}
    assert build_context(story, "scene-03") == build_context(story, "scene-03")
    after = {str(p.relative_to(story)): p.read_bytes() for p in story.rglob("*") if p.is_file()}
    assert before == after


def test_extra_source_fields_are_not_leaked(story):
    data = ledger(story)
    data["entries"][0]["source"]["future_notes"] = "UNTRUSTED_FUTURE_NOTE"
    write(story / "continuity-ledger.json", data)
    assert "UNTRUSTED_FUTURE_NOTE" not in encoded(build_context(story, "scene-02"))


def test_effective_position_and_ledger_order(story):
    data = ledger(story)
    data["entries"][2]["valid_from_scene"] = "scene-04"
    write(story / "continuity-ledger.json", data)
    assert state(build_context(story, "scene-03"), "key", "holder") == "阿青"
    before = build_context(story, "scene-04")
    assert state(before, "key", "holder") == "阿白"
    data["entries"].reverse()
    write(story / "continuity-ledger.json", data)
    assert build_context(story, "scene-04") == before


def test_cross_story_batch_card_rejected(story, tmp_path_factory):
    other = tmp_path_factory.mktemp("other-card") / "scene-02.json"
    write(other, {"scene_id": "scene-02"})
    with pytest.raises(ContextError, match="escapes"):
        prompt_for_batch(story, [other], 1, 1)


def test_scoped_repair_preserves_reviewed_prose_cards_and_assembly(story):
    from repairs import repair_fragmentation_and_soft_words as repair

    original = '阿青轻轻拿着钥匙。\n“你会归还信件吗？”\n'
    write(story / "draft-scenes/scene-01.md", original)
    data = ledger(story)
    data["entries"] = [data["entries"][0]]
    data["entries"][0]["source"] = {**source_evidence(story, "scene-01"), "quote": "阿青轻轻拿着钥匙。"}
    write(story / "continuity-ledger.json", data)
    write(story / "draft.md", "existing assembly must survive scoped repair")
    before = {str(p.relative_to(story)): p.read_bytes() for p in story.rglob("*") if p.is_file()}
    write(story / "draft-scenes/scene-02.md", '“阿白轻轻拿着纸条，站在窗边问话吗？”\n' * 8)
    report = repair.run(story, scene_ids=["scene-02"])
    assert report["question_rewrites"] > 0
    assert "轻轻" not in (story / "draft-scenes/scene-02.md").read_text()
    allowed = {"draft-scenes/scene-02.md", "scene-cards/scene-02.json"}
    for rel, content in before.items():
        if rel not in allowed:
            assert (story / rel).read_bytes() == content, rel
    assert state(build_context(story, "scene-03"), "key", "holder") == "阿青"


def test_generation_retry_repair_then_next_scene_keeps_accepted_history(story, monkeypatch):
    import re
    import subprocess

    import generate_scene_batches as batches

    # Resumed prefixes must satisfy the complete-draft gate as well.
    original = '阿青轻轻拿着钥匙。\n' + '她把那封信收进抽屉，转身关上窗。\n' * 7
    write(story / "draft-scenes/scene-01.md", original)
    data = ledger(story)
    data["entries"] = [data["entries"][0]]
    data["entries"][0]["source"] = {**source_evidence(story, "scene-01"), "quote": "阿青轻轻拿着钥匙。"}
    write(story / "continuity-ledger.json", data)
    first_card = (story / "scene-cards/scene-01.json").read_bytes()
    accepted_ledger = (story / "continuity-ledger.json").read_bytes()
    prompts = []
    attempts = {}

    def fake_codex(prompt, output_path, model, effort, timeout):
        prompts.append(prompt)
        sid = re.search(r"- draft-scenes/(scene-\d+)\.md", prompt).group(1)
        attempts[sid] = attempts.get(sid, 0) + 1
        prose = "短" if sid == "scene-02" and attempts[sid] == 1 else '“阿白轻轻拿着纸条，站在窗边问话吗？”\n' * 8
        output_path.write_text(f"<<<FILE: draft-scenes/{sid}.md>>>\n{prose}\n<<<END FILE>>>\n", encoding="utf-8")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(batches, "run_codex", fake_codex)
    monkeypatch.setattr(batches, "relative", str)
    monkeypatch.setattr(sys, "argv", ["generate_scene_batches.py", "--story", str(story), "--start-at", "2", "--run-id", "scoped-integration", "--batch-size", "3", "--no-human-gates"])
    assert batches.main() == 0
    assert attempts == {"scene-02": 2, "scene-03": 1, "scene-04": 1, "scene-05": 1, "scene-06": 1}
    assert any("split scene repair" in prompt for prompt in prompts)
    assert (story / "draft-scenes/scene-01.md").read_text() == original
    assert (story / "scene-cards/scene-01.json").read_bytes() == first_card
    assert (story / "continuity-ledger.json").read_bytes() == accepted_ledger
    assert state(build_context(story, "scene-06"), "key", "holder") == "阿青"
    manifest = json.loads((story / "runs/scoped-integration/split-scene-report.json").read_text())
    assert manifest["effective_batch_size"] == 1 and manifest["status"] == "success"
    assert (story / "draft.md").read_text().startswith(original.strip())


@pytest.mark.parametrize("ids", [["../scene-01"], ["scene-02", "scene-02"], ["scene-999"], []])
def test_scoped_repair_rejects_invalid_targets_before_writes(story, ids):
    from repairs import repair_fragmentation_and_soft_words as repair

    before = {str(p.relative_to(story)): p.read_bytes() for p in story.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        repair.run(story, scene_ids=ids)
    after = {str(p.relative_to(story)): p.read_bytes() for p in story.rglob("*") if p.is_file()}
    assert before == after
