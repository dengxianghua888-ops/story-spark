import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('corpus_index_atomic_test', ROOT / 'scripts/update-corpus-index.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_index_survives_replace_failure(tmp_path, monkeypatch):
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    index = corpus / '_index.json'
    old = '{"_meta": {}, "entries": [{"slug": "old"}]}'
    index.write_text(old, encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['update-corpus-index.py', '--corpus', str(corpus)])
    def fail_replace(*args):
        raise OSError('simulated replace failure')
    monkeypatch.setattr('storyforge_lib.os.replace', fail_replace)
    with pytest.raises(OSError, match='simulated'):
        module.main()
    assert index.read_text(encoding='utf-8') == old
    assert sorted(p.name for p in corpus.iterdir()) == ['_index.json']


def test_index_rebuilt_and_permissions_retained(tmp_path, monkeypatch):
    corpus = tmp_path / 'corpus'
    corpus.mkdir()
    index = corpus / '_index.json'
    index.write_text('{"_meta": {}, "entries": []}', encoding='utf-8')
    index.chmod(0o640)
    (corpus / 'one').mkdir()
    monkeypatch.setattr(sys, 'argv', ['update-corpus-index.py', '--corpus', str(corpus)])
    module.main()
    assert json.loads(index.read_text(encoding='utf-8'))['entries'][0]['slug'] == 'one'
    assert index.stat().st_mode & 0o777 == 0o640
