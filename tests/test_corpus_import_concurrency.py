"""Real local ZIP importer processes; synthetic text, no provider calls."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
IMPORTER = ROOT / 'scripts/import-corpus-zips.py'
sys.path.insert(0, str(ROOT / 'scripts'))
SPEC = importlib.util.spec_from_file_location('concurrent_corpus_importer', IMPORTER)
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)

OWNER = '''
import importlib.util,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).parent))
spec=importlib.util.spec_from_file_location('owner_importer',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
ready,release=map(Path,sys.argv[4:6])
def hold():
 ready.touch();deadline=time.monotonic()+10
 while not release.exists():
  if time.monotonic()>deadline:raise RuntimeError('finite fixture release expired')
  time.sleep(.01)
if sys.argv[6]=='scan':
 original=module.load_existing_fingerprints
 def pause(path):
  value=original(path);hold();return value
 module.load_existing_fingerprints=pause
else:
 original=module.write_text
 def pause(path,text):
  if path.name=='_manifest.tsv':hold()
  return original(path,text)
 module.write_text=pause
print(json.dumps(module.import_archives([Path(sys.argv[2])],Path(sys.argv[3]),False)))
'''


@unittest.skipUnless(os.name == 'posix', 'POSIX ZIP importer locking contract')
class CorpusImportConcurrencyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='corpus-import-lock-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.corpus = self.root / 'corpus'
        self.archives = []
        for title in ('first', 'second'):
            archive = self.root / (title + '.zip')
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr(title + '.txt', title + ' synthetic owned source text.')
            self.archives.append(archive)

    def tree(self):
        return {str(p.relative_to(self.corpus)): p.read_bytes()
                for p in self.corpus.rglob('*') if p.is_file()}

    def cli(self, archive, corpus=None, extra=()):
        return subprocess.run([sys.executable, str(IMPORTER), str(archive), '--corpus',
                               str(corpus or self.corpus), '--json', *extra],
                              capture_output=True, text=True, timeout=8)

    def owner(self, phase):
        ready = self.root / (self.corpus.name + '-' + phase + '-ready')
        release = self.root / (self.corpus.name + '-' + phase + '-release')
        process = subprocess.Popen([sys.executable, '-c', OWNER, str(IMPORTER),
            str(self.archives[0]), str(self.corpus), str(ready), str(release), phase],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 5
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(ready.exists(), 'owner must actually reach the guarded boundary')
        return process, release

    def finish_owner(self, process, release):
        release.touch()
        stdout, stderr = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(len(json.loads(stdout)['imported']), 1)

    def test_scan_and_manifest_boundaries_reject_second_writer_without_changes(self):
        for phase in ('scan', 'manifest'):
            with self.subTest(phase=phase):
                # Each boundary uses a fresh corpus and owner handshakes.
                self.corpus = self.root / phase
                process, release = self.owner(phase)
                try:
                    before = self.tree()
                    result = self.cli(self.archives[1])
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn('active ZIP importer', result.stderr)
                    self.assertEqual(self.tree(), before)
                finally:
                    self.finish_owner(process, release)
                retry = self.cli(self.archives[1])
                self.assertEqual(retry.returncode, 0, retry.stderr)
                self.assertEqual(len(json.loads(retry.stdout)['imported']), 1)
                rows = (self.corpus / '_manifest.tsv').read_text().splitlines()[1:]
                self.assertEqual(len(rows), 2)
                self.assertEqual(len(list(self.corpus.glob('*/source.md'))), 2)

    def test_path_aliases_share_one_guard_and_lock_file_is_not_removed(self):
        process, release = self.owner('scan')
        alias = self.root / 'corpus-alias'
        alias.symlink_to(self.corpus, target_is_directory=True)
        lock = self.root / '.corpus.corpus-import.lock'
        try:
            inode = lock.stat().st_ino
            relative = Path(os.path.relpath(self.corpus, Path.cwd()))
            for target in (alias, relative):
                result = self.cli(self.archives[1], target)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('active ZIP importer', result.stderr)
                self.assertEqual(lock.stat().st_ino, inode)
        finally:
            self.finish_owner(process, release)
        self.assertTrue(lock.is_file())
        self.assertEqual(lock.stat().st_ino, inode)
        before_manifest = (alias / '_manifest.tsv').read_bytes()
        write = importer.write_text

        def fail_alias_manifest(path, text):
            if path == alias / '_manifest.tsv':
                raise OSError('synthetic alias manifest write failure')
            return write(path, text)

        with patch.object(importer, 'write_text', fail_alias_manifest):
            with self.assertRaisesRegex(OSError, 'alias manifest write failure'):
                importer.import_archives([self.archives[1]], alias, False)
        self.assertEqual((alias / '_manifest.tsv').read_bytes(), before_manifest)
        self.assertEqual(self.cli(self.archives[1], alias).returncode, 0)
        self.assertEqual(len((alias / '_manifest.tsv').read_text().splitlines()[1:]), 2)
        self.assertEqual(lock.stat().st_ino, inode)

    def test_unsafe_lock_targets_are_rejected_without_truncating_or_importing(self):
        lock = self.root / '.corpus.corpus-import.lock'
        target = self.root / 'outside-lock-target'
        target.write_bytes(b'retain this independent file')
        lock.symlink_to(target)
        result = self.cli(self.archives[0])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('regular non-symlink', result.stderr)
        self.assertEqual(target.read_bytes(), b'retain this independent file')
        self.assertFalse(self.corpus.exists())
        lock.unlink()
        lock.mkdir()
        result = self.cli(self.archives[0])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.corpus.exists())
        lock.rmdir()
        lock.write_bytes(b'existing regular lock contents stay intact')
        inode = lock.stat().st_ino
        result = self.cli(self.archives[0])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(lock.read_bytes(), b'existing regular lock contents stay intact')

    def test_dry_run_does_not_create_a_writer_lock_or_block_on_owner(self):
        preview = self.cli(self.archives[1], extra=('--dry-run',))
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertFalse((self.root / '.corpus.corpus-import.lock').exists())
        process, release = self.owner('scan')
        try:
            before = self.tree()
            preview = self.cli(self.archives[1], extra=('--dry-run',))
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(self.tree(), before)
            self.assertTrue(json.loads(preview.stdout)['dry_run'])
        finally:
            self.finish_owner(process, release)


if __name__ == '__main__':
    unittest.main()
