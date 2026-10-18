"""Offline split-scene publication, approval, and complete-output regressions."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import approval_snapshots as approvals  # noqa: E402
import generate_scene_batches as batches  # noqa: E402
from production_normalize import normalize_story  # noqa: E402
from repairs import repair_fragmentation_and_soft_words as repair  # noqa: E402
from storyforge_lib import story_write_lock, write_json, write_text  # noqa: E402

PROSE = '“阿白轻轻拿着纸条，站在窗边问话吗？”\n' * 8


def artifacts(story):
    return {str(p.relative_to(story)): p.read_bytes() for p in story.rglob('*')
            if p.is_file() and 'runs' not in p.relative_to(story).parts}


def make_story(tmp_path, ledger=True):
    story = tmp_path / 'story'
    write_text(story / 'source.md', '用于离线测试的合成原文。')
    write_text(story / 'analysis/style-dna.md', '短句')
    write_json(story / 'beat-bible.json', {})
    write_text(story / 'story.yaml', 'slug: synthetic\n')
    if ledger:
        write_json(story / 'continuity-ledger.json', {'schema_version': 1, 'entries': []})
    for sid in ['scene-01', 'scene-02']:
        write_json(story / f'scene-cards/{sid}.json', {
            'scene_id': sid, 'target_chars_min': 100, 'target_chars_max': 200,
            'character_goal': '让读者知道她拿到了钥匙。', 'plan': '本场计划'})
        write_text(story / f'draft-scenes/{sid}.md', PROSE)
    repair.run(story, scene_ids=['scene-01', 'scene-02'])
    cards = sorted((story / 'scene-cards').glob('*.json'))
    assert not batches.validate_scene_batch(story, cards, ['draft-scenes/scene-01.md', 'draft-scenes/scene-02.md'])
    write_text(story / 'draft.md', 'REVIEWED ASSEMBLY')
    return story


def invoke(monkeypatch, story, runner, *extra, gated=False):
    monkeypatch.setattr(batches, 'run_codex', runner)
    argv = ['generate_scene_batches.py', '--story', str(story), '--run-id', 'test', '--retries', '0']
    argv += ['--approval-run-id', 'approved'] if gated else ['--no-human-gates']
    monkeypatch.setattr(sys, 'argv', argv + list(extra))
    return batches.main()


def model(prose=PROSE):
    def run(prompt, output, *args):
        ids = list(dict.fromkeys(re.findall(r'^- draft-scenes/(scene-\d+)\.md$', prompt, re.M)))
        write_text(output, ''.join(f'<<<FILE: draft-scenes/{sid}.md>>>\n{prose}\n<<<END FILE>>>\n' for sid in ids))
        return subprocess.CompletedProcess([], 0, '', '')
    return run


def report(story):
    return json.loads((story / 'runs/test/split-scene-report.json').read_text())


def approved(story):
    args = argparse.Namespace(mode='production', runner='codex', model='gpt-5.4', effort='medium', skip_rubric=False, rubric_threshold=None)
    run = story / 'runs/approved'
    cfg = approvals.configuration(args)
    write_json(run / 'blueprint-pending.json', {'configuration': cfg})
    # Synthetic explicit approval fixture; production approval checks are exercised
    # separately in test_approval_snapshots.py.
    write_json(run / 'blueprint-approval.json', {'snapshot': approvals.approval_snapshot(story, ROOT, cfg)})
    return run, args


@pytest.mark.parametrize('ledger', [False, True])
def test_failed_batch_preserves_all_live_artifacts_and_candidate(tmp_path, monkeypatch, ledger):
    story = make_story(tmp_path, ledger)
    before = artifacts(story)
    with pytest.raises(SystemExit, match='scene batch failed validation'):
        invoke(monkeypatch, story, model('坏'), '--start-at', '2')
    assert artifacts(story) == before
    r = report(story)
    assert r['status'] == 'failed'
    candidate = Path(r['candidate'])
    assert candidate.is_dir()
    assert (candidate / 'draft-scenes/scene-02.md').read_bytes() != before['draft-scenes/scene-02.md']
    assert (story / 'runs/test/retry-feedback.json').exists()


def test_later_batch_failure_does_not_publish_earlier_batch(tmp_path, monkeypatch):
    story = make_story(tmp_path)
    before = artifacts(story)
    calls = []
    def runner(prompt, output, *args):
        calls.append(prompt)
        return model(PROSE if len(calls) == 1 else '坏')(prompt, output, *args)
    with pytest.raises(SystemExit, match='failed validation'):
        invoke(monkeypatch, story, runner)
    assert len(calls) == 2
    assert artifacts(story) == before


def test_force_failure_only_clears_candidate(tmp_path, monkeypatch):
    story = make_story(tmp_path, ledger=False)
    before = artifacts(story)
    with pytest.raises(SystemExit, match='failed validation'):
        invoke(monkeypatch, story, model('坏'), '--force')
    assert artifacts(story) == before


def test_existing_writer_blocks_before_model_or_run_writes(tmp_path, monkeypatch):
    story = make_story(tmp_path)
    before = artifacts(story)
    def forbidden(*args):
        pytest.fail('runner must not start while another writer owns the story')
    with story_write_lock(story), pytest.raises(ValueError, match='active writer'):
        invoke(monkeypatch, story, forbidden)
    assert artifacts(story) == before
    assert not (story / 'runs/test').exists()


@pytest.mark.parametrize('earlier', ['short', 'bad_rhythm', 'missing'])
def test_resume_validates_skipped_scenes_before_publication(tmp_path, monkeypatch, earlier):
    story = make_story(tmp_path)
    path = story / 'draft-scenes/scene-01.md'
    if earlier == 'missing':
        path.unlink()
    else:
        path.write_text('旧稿' if earlier == 'short' else '字' * 150)
    before = artifacts(story)
    with pytest.raises(SystemExit, match='complete draft failed validation'):
        invoke(monkeypatch, story, model(), '--start-at', '2')
    assert artifacts(story) == before
    r = report(story)
    assert r['status'] == 'failed'
    assert any('scene-01' in failure for failure in r['failures'])


def test_success_preserves_approval_cards_and_keeps_previous_tree(tmp_path, monkeypatch):
    story = make_story(tmp_path)
    before = artifacts(story)
    run, args = approved(story)
    approval_bytes = (run / 'blueprint-approval.json').read_bytes()
    assert invoke(monkeypatch, story, model(), gated=True) == 0
    r = report(story)
    assert r['status'] == 'success'
    assert artifacts(Path(r['attempt_backup'])) == before
    for rel in ['scene-cards/scene-01.json', 'scene-cards/scene-02.json']:
        assert (story / rel).read_bytes() == before[rel]
    assert (run / 'blueprint-approval.json').read_bytes() == approval_bytes
    approvals.require_approval(story, run, ROOT, args)
    assert all(item['status'] == 'pass' for item in r['assembly']['scene_lengths'])
    assert (story / 'draft.md').read_text() != 'REVIEWED ASSEMBLY'
    # An actual subsequent user edit still requires renewed human approval.
    write_json(story / 'scene-cards/scene-01.json', {'scene_id': 'scene-01', 'plan': 'changed'})
    with pytest.raises(ValueError, match='stale'):
        approvals.require_approval(story, run, ROOT, args)


@pytest.mark.parametrize('edit', ['draft.md', 'scene-cards/scene-01.json'])
def test_concurrent_external_edit_fails_closed(tmp_path, monkeypatch, edit):
    story = make_story(tmp_path)
    approved(story)
    before = (story / 'draft-scenes/scene-02.md').read_bytes()
    def runner(prompt, output, *args):
        result = model()(prompt, output, *args)
        write_text(story / edit, 'external edit')
        return result
    with pytest.raises((OSError, ValueError)):
        invoke(monkeypatch, story, runner, '--start-at', '2', gated=True)
    assert (story / edit).read_text() == 'external edit'
    assert (story / 'draft-scenes/scene-02.md').read_bytes() == before
    assert report(story)['status'] == 'failed'


def test_beat_normalizes_before_review_and_prose_repairs_preserve_cards(tmp_path):
    story = make_story(tmp_path)
    before = (story / 'scene-cards/scene-01.json').read_bytes()
    normalization = normalize_story(story, 4, 'production')
    assert 'phase4_sanitized_scene_cards' in normalization['changes']
    after = (story / 'scene-cards/scene-01.json').read_bytes()
    assert after != before
    run, args = approved(story)
    for ids in [None, ['scene-01']]:
        assert repair.run(story, scene_ids=ids)['sanitized_scene_cards'] == 0
        assert (story / 'scene-cards/scene-01.json').read_bytes() == after
        approvals.require_approval(story, run, ROOT, args)


def test_pre_review_sanitizer_accepts_nested_structured_card_values(tmp_path):
    story = make_story(tmp_path)
    path = story / 'scene-cards/scene-01.json'
    card = json.loads(path.read_text())
    card['structured_notes'] = [{'action': '拿起钥匙'}, ['打开门']]
    write_json(path, card)
    normalize_story(story, 4, 'production')
    assert json.loads(path.read_text())['structured_notes'] == card['structured_notes']


def test_runner_timeout_retains_old_story_and_failure_report(tmp_path, monkeypatch):
    story = make_story(tmp_path)
    before = artifacts(story)
    def timeout(*args):
        raise subprocess.TimeoutExpired('offline fake runner', 1)
    with pytest.raises(subprocess.TimeoutExpired):
        invoke(monkeypatch, story, timeout)
    assert artifacts(story) == before
    assert report(story)['status'] == 'failed'
