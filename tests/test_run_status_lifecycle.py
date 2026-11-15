"""Current execution status is not an inherited successful-run marker."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import storyforge
from source_policy import SourceAccessDenied
from storyforge_lib import write_json, write_text
from test_stage_safety import tree_bytes, successful_phase_harness, v6_fixtures
from test_storyforge_runner import run_storyforge


def fixture(tmp_path, mode='v4', phase=1):
    story = tmp_path / 'story'
    write_text(story / 'source.md', 'Synthetic offline source.')
    write_text(story / 'draft.md', 'Reviewed draft.')
    run = story / 'runs/r'
    write_json(run / 'run-manifest.json', {'status':'completed', 'ended_at':'old end',
        'ended_phase':9, 'last_failure':'old failure', 'exit_code':0})
    write_json(run / 'phase1.completed-snapshot.json', {'historical':'preserve'})
    args = storyforge.build_parser().parse_args(['run', '--story', str(story), '--run-id', 'r',
        '--runner', 'mock', '--mode', mode, '--from-phase', str(phase), '--to-phase', str(phase),
        '--max-retries', '0', '--no-human-gates'])
    return story, run, args


def manifest(run):
    return json.loads((run / 'run-manifest.json').read_text())


@pytest.mark.parametrize('mode', ['v4', 'production', 'ultra_short', 'production_v6'])
def test_actual_completed_run_then_manual_wait_is_paused(tmp_path, mode):
    story = tmp_path / 'story'
    write_text(story / 'source.md', 'Synthetic offline source.')
    base = ['run','--story',str(story),'--run-id','r','--mode',mode,'--to-phase','1',
            '--max-retries','0','--no-human-gates']
    env = {'STORYFORGE_MOCK_FIXTURE_DIR':str(v6_fixtures(tmp_path))} if mode == 'production_v6' else None
    good = run_storyforge(*base, '--runner','mock', env=env)
    assert good.returncode == 0, good.stderr
    run = story / 'runs/r'
    assert manifest(run)['status'] == 'completed'
    snapshot = (run / 'phase1.completed-snapshot.json').read_bytes()
    before = tree_bytes(story)
    waiting = run_storyforge(*base, '--runner','manual-prompt-pack', env=env)
    assert waiting.returncode == 23, waiting.stderr
    assert manifest(run)['status'] == 'paused'
    assert manifest(run)['exit_code'] == 23
    assert manifest(run)['ended_phase'] is None
    assert 'manual prompt pack generated:' in manifest(run)['last_failure']
    assert tree_bytes(story) == before
    assert (run / 'phase1.completed-snapshot.json').read_bytes() == snapshot


@pytest.mark.parametrize('outcome', ['false', 'oserror', 'valueerror', 'importerror', 'denial'])
def test_current_phase_exit_overrides_old_completion(tmp_path, monkeypatch, outcome):
    story, run, args = fixture(tmp_path)
    before = tree_bytes(story)
    snapshot = (run / 'phase1.completed-snapshot.json').read_bytes()

    def phase(*args):
        current = manifest(run)
        assert current['status'] == 'running'
        assert current['ended_at'] is None and current['ended_phase'] is None
        assert current['last_failure'] is None and current['exit_code'] is None
        errors = {'oserror':OSError, 'valueerror':ValueError, 'importerror':ImportError,
                  'denial':SourceAccessDenied}
        if outcome in errors:
            raise errors[outcome]('current fault')
        return False

    monkeypatch.setattr(storyforge, 'run_phase', phase)
    assert storyforge.run_pipeline(args) == (30 if outcome == 'denial' else 23)
    assert manifest(run)['status'] == ('blocked' if outcome == 'denial' else 'failed')
    assert manifest(run)['ended_at'] and manifest(run)['ended_at'] != 'old end'
    assert tree_bytes(story) == before
    assert (run / 'phase1.completed-snapshot.json').read_bytes() == snapshot


def test_approval_pause_does_not_retain_completed_status(tmp_path, monkeypatch):
    story, run, args = fixture(tmp_path, phase=3)
    args.runner = 'manual-prompt-pack'
    args.no_human_gates = False
    monkeypatch.setattr(storyforge, 'run_phase', lambda *a:pytest.fail('must not reach runner'))
    assert storyforge.run_pipeline(args) == 24
    assert manifest(run)['status'] == 'paused'
    assert manifest(run)['exit_code'] == 24


@pytest.mark.parametrize('mode,phase', [('v4',2),('production',4),('production_v6',5),('ultra_short',4)])
def test_failed_beat_is_failed_even_when_legacy_exit_is_human_gate(tmp_path, monkeypatch, mode, phase):
    story, run, args = fixture(tmp_path, mode, phase)
    args.runner = 'manual-prompt-pack'
    args.no_human_gates = False
    write_json(run / f'phase{phase}.awaiting-manual.json', {'stale':'marker'})
    monkeypatch.setattr(storyforge, 'run_phase', lambda *a:False)
    assert storyforge.run_pipeline(args) == 24
    assert manifest(run)['status'] == 'failed'
    assert manifest(run)['exit_code'] == 24


def test_failed_phase_cannot_use_old_manual_marker(tmp_path, monkeypatch):
    story, run, args = fixture(tmp_path)
    write_json(run / 'phase1.awaiting-manual.json', {'stale':'marker'})
    monkeypatch.setattr(storyforge, 'run_phase', lambda *a:False)
    assert storyforge.run_pipeline(args) == 23
    assert manifest(run)['status'] == 'failed'


def test_summary_failure_still_records_failed_status(tmp_path, monkeypatch):
    story, run, args = fixture(tmp_path)
    def phase(*a):
        raise OSError('summary disk full')
    monkeypatch.setattr(storyforge, 'run_phase', phase)
    assert storyforge.run_pipeline(args) == 23
    assert manifest(run)['status'] == 'failed'
    assert 'summary disk full' in manifest(run)['last_failure']


@pytest.mark.parametrize('eventual_success', [False, True])
def test_retry_clears_previous_pause_and_reports_final_outcome(tmp_path, monkeypatch, eventual_success):
    story, run, args = fixture(tmp_path, mode='production', phase=5)
    args.max_retries = 1
    observed = []

    def phase(*a):
        observed.append(manifest(run)['status'])
        if len(observed) == 1:
            write_json(run / 'phase5.awaiting-manual.json', {'old':'marker'})
            storyforge.update_manifest(run, {'status':'paused'})
            return False
        return eventual_success

    monkeypatch.setattr(storyforge, 'run_phase', phase)
    assert storyforge.run_pipeline(args) == (0 if eventual_success else 23)
    assert observed == ['running','running']
    assert manifest(run)['status'] == ('completed' if eventual_success else 'failed')
    assert manifest(run)['exit_code'] == (0 if eventual_success else 23)


def test_failure_audit_unavailable_does_not_hide_nonzero(tmp_path, monkeypatch, capsys):
    story, run, args = fixture(tmp_path)
    original = storyforge.update_manifest

    def update(target, patch):
        if patch.get('status') == 'failed':
            raise OSError('synthetic status sink unavailable')
        original(target, patch)

    monkeypatch.setattr(storyforge, 'update_manifest', update)
    monkeypatch.setattr(storyforge, 'run_phase', lambda *a:False)
    assert storyforge.run_pipeline(args) == 23
    assert manifest(run)['status'] == 'running'
    assert 'final status audit unavailable' in capsys.readouterr().err


def test_preflight_source_denial_preserves_no_write_contract(tmp_path):
    story, run, args = fixture(tmp_path)
    write_text(story / 'story.yaml', 'source_policy:\n  access: denied\n')
    args.runner = 'manual-prompt-pack'
    # manual packs retain their existing source contract; use the guarded name
    # solely for its preflight check. No provider can be reached after denial.
    args.runner = 'codex'
    before = {str(p.relative_to(story)):p.read_bytes() for p in story.rglob('*') if p.is_file()}
    assert storyforge.run_pipeline(args) == 30
    after = {str(p.relative_to(story)):p.read_bytes() for p in story.rglob('*') if p.is_file()}
    assert after == before


def test_published_success_is_not_relabelled_failed_on_audit_error(tmp_path, monkeypatch, capsys):
    _, story, run = successful_phase_harness(tmp_path, monkeypatch)
    write_text(story / 'source.md', 'Synthetic source')
    args = storyforge.build_parser().parse_args(['run','--story',str(story),'--run-id','r',
        '--runner','mock','--from-phase','3','--to-phase','3','--max-retries','0','--no-human-gates'])
    write_json(run / 'run-manifest.json', {'status':'completed'})
    original = storyforge.update_manifest

    def update(target, patch):
        if (story / 'draft.md').read_text() == 'NEW':
            raise OSError('post-publication audit unavailable')
        original(target, patch)

    monkeypatch.setattr(storyforge, 'update_manifest', update)
    assert storyforge.run_pipeline(args) == 0
    assert (story / 'draft.md').read_text() == 'NEW'
    assert manifest(run)['status'] == 'running'
    assert 'committed' in capsys.readouterr().err


def test_completion_summary_failure_does_not_block_manifest(tmp_path, monkeypatch, capsys):
    story, run, args = fixture(tmp_path)
    original_open = Path.open
    def opening(path, mode='r', *pos, **kw):
        if path == run / 'execution-summary.md' and mode == 'a':
            raise OSError('completion summary unavailable')
        return original_open(path, mode, *pos, **kw)
    monkeypatch.setattr(storyforge, 'run_phase', lambda *a:True)
    monkeypatch.setattr(Path, 'open', opening)
    assert storyforge.run_pipeline(args) == 0
    assert manifest(run)['status'] == 'completed'
    assert manifest(run)['exit_code'] == 0
    assert 'completion summary unavailable' in capsys.readouterr().err


def test_dry_run_preserves_completion_exit_without_runner(tmp_path, monkeypatch):
    story, run, args = fixture(tmp_path)
    args.dry_run = True
    monkeypatch.setattr(storyforge, 'run_command_with_heartbeat', lambda *a,**k:pytest.fail('no provider'))
    before = tree_bytes(story)
    assert storyforge.run_pipeline(args) == 0
    assert manifest(run)['status'] == 'completed'
    assert tree_bytes(story) == before
    assert not list(tmp_path.glob('.story.attempt-*'))


def test_summary_initialization_failure_cannot_retain_old_completion(tmp_path, monkeypatch):
    story, run, args = fixture(tmp_path)
    def fail(*a):
        raise OSError('summary initialization unavailable')
    monkeypatch.setattr(storyforge, 'init_summary', fail)
    assert storyforge.run_pipeline(args) == 23
    assert manifest(run)['status'] == 'failed'
    assert 'summary initialization unavailable' in manifest(run)['last_failure']


def test_actual_published_beat_pauses_for_human_gate(tmp_path):
    story, run, args = fixture(tmp_path)
    result = run_storyforge('run', '--story', str(story), '--run-id', 'r', '--runner', 'agent',
                           env={'STORYFORGE_AGENT_PROVIDER_PRIORITY':'mock'})
    assert result.returncode == 24, result.stderr
    assert manifest(run)['status'] == 'paused'
    assert manifest(run)['exit_code'] == 24
    assert (story / 'adaptation.md').exists()
    assert (run / 'phase2.completed-snapshot.json').exists()
