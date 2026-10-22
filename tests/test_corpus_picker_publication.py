"""New picker stories publish complete denied scaffolds or remain private."""
import ctypes
import errno
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("picker_publication", ROOT / "scripts/corpus-picker.py")
picker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(picker)
storyforge = importlib.import_module("storyforge")


class PickerPublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="picker-publication-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "corpus/synthetic/source.md"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("Synthetic source bytes remain private until publication.", encoding="utf-8")
        self.entry = {"slug": "synthetic", "source_path": "corpus/synthetic/source.md"}
        self.story = self.root / "stories/picked_synthetic"
        for name, value in [("ROOT", self.root), ("STORIES_DIR", self.root / "stories")]:
            patcher = patch.object(picker, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def scaffold(self, prefix="picked"):
        return picker._scaffold_story(self.entry, prefix, "synthetic-run")

    def private_attempts(self, prefix="picked"):
        return sorted((self.root / "stories").glob(f".{prefix}_synthetic.picker-*"))

    def assert_denied_complete(self, story):
        manifest = yaml.safe_load((story / "story.yaml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_policy"]["access"], "denied")
        self.assertEqual((story / "source.md").read_bytes(), self.source.read_bytes())
        self.assertEqual(json.loads((story / "pick-card.json").read_text())["slug"], story.name)
        for runner in ("agent", "codex", "openclaw", "claude"):
            args = storyforge.build_parser().parse_args([
                "run", "--story", str(story), "--runner", runner, "--run-id", "blocked",
            ])
            with patch.object(storyforge, "run_phase", side_effect=AssertionError(
                    "Denied scaffold must not reach a provider")) as execute:
                self.assertEqual(storyforge.run_pipeline(args), 30)
                execute.assert_not_called()
        self.assertFalse((story / "runs").exists())

    def test_partial_manifest_write_failure_has_no_public_source_and_retry_is_denied(self):
        original = Path.write_text

        def fail_manifest(path, text, *args, **kwargs):
            if path.name == "story.yaml":
                original(path, text[:12], *args, **kwargs)
                raise OSError("synthetic partial manifest write")
            return original(path, text, *args, **kwargs)

        with patch.object(Path, "write_text", fail_manifest), self.assertRaisesRegex(OSError, "manifest"):
            self.scaffold()
        self.assertFalse(self.story.exists())
        attempts = self.private_attempts()
        self.assertEqual(len(attempts), 1)
        self.assertFalse((attempts[0] / "source.md").exists())
        self.assertEqual(stat.S_IMODE(attempts[0].stat().st_mode), 0o700)
        self.assert_denied_complete(self.scaffold())

    def test_partial_source_copy_failure_retains_denied_private_candidate_and_retries(self):
        def fail_copy(source, destination, *args, **kwargs):
            Path(destination).write_bytes(b"synthetic partial body")
            raise OSError("synthetic partial source copy")

        with patch.object(picker.shutil, "copy2", fail_copy), self.assertRaisesRegex(OSError, "source copy"):
            self.scaffold()
        self.assertFalse(self.story.exists())
        attempts = self.private_attempts()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(storyforge.story_source_access(attempts[0]), "denied")
        self.assert_denied_complete(self.scaffold())

    def test_partial_pick_card_failure_has_no_public_story_and_retries(self):
        original = Path.write_text

        def fail_card(path, text, *args, **kwargs):
            if path.name == "pick-card.json":
                original(path, text[:10], *args, **kwargs)
                raise OSError("synthetic partial pick card")
            return original(path, text, *args, **kwargs)

        with patch.object(Path, "write_text", fail_card), self.assertRaisesRegex(OSError, "pick card"):
            self.scaffold()
        self.assertFalse(self.story.exists())
        self.assertEqual(storyforge.story_source_access(self.private_attempts()[0]), "denied")
        self.assert_denied_complete(self.scaffold())

    def test_publication_failure_retains_complete_private_candidate_and_retries(self):
        with (patch.object(picker, "_publish_scaffold", side_effect=OSError("synthetic publication failure")),
              self.assertRaisesRegex(OSError, "publication failure")):
            self.scaffold()
        self.assertFalse(self.story.exists())
        candidate = self.private_attempts()[0]
        self.assertEqual(storyforge.story_source_access(candidate), "denied")
        self.assertEqual((candidate / "source.md").read_bytes(), self.source.read_bytes())
        self.assertTrue((candidate / "pick-card.json").is_file())
        self.assert_denied_complete(self.scaffold())

    def test_native_publication_never_replaces_a_target_created_during_staging(self):
        publish = picker._publish_scaffold
        for kind in ("empty", "approved", "symlink", "dangling-symlink"):
            with self.subTest(target=kind):
                prefix = "race-" + kind
                target = self.root / "stories" / f"{prefix}_synthetic"
                owner = self.root / f"owner-{kind}"
                before = {}

                def race(staged, story, kind=kind, owner=owner, before=before):
                    if kind in ("symlink", "dangling-symlink"):
                        if kind == "symlink":
                            owner.mkdir()
                            (owner / "note.txt").write_bytes(b"owner's existing target")
                        story.symlink_to(owner, target_is_directory=True)
                    else:
                        story.mkdir()
                        if kind == "approved":
                            (story / "story.yaml").write_text(
                                "source_policy:\n  access: trusted_runners_allowed\n", encoding="utf-8")
                            (story / "source.md").write_bytes(b"existing owner source")
                        before.update({path.name: path.read_bytes() for path in story.iterdir()})
                    with self.assertRaises(FileExistsError):
                        publish(staged, story)
                    raise FileExistsError(errno.EEXIST, "synthetic wrapper preserves native collision", str(story))

                with patch.object(picker, "_publish_scaffold", race):
                    self.assertEqual(self.scaffold(prefix), target)
                if kind in ("symlink", "dangling-symlink"):
                    self.assertTrue(target.is_symlink())
                    self.assertEqual(target.readlink(), owner)
                    if kind == "symlink":
                        self.assertEqual((owner / "note.txt").read_bytes(), b"owner's existing target")
                else:
                    self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)

    def test_existing_approved_denied_and_legacy_stories_remain_byte_identical(self):
        for index, access in enumerate(("trusted_runners_allowed", "denied", None)):
            with self.subTest(access=access):
                prefix = f"existing{index}"
                story = self.root / "stories" / f"{prefix}_synthetic"
                story.mkdir(parents=True)
                (story / "source.md").write_bytes(b"existing legacy source")
                (story / "owner-note.txt").write_bytes(b"preserve this user work")
                if access is not None:
                    (story / "story.yaml").write_text(f"source_policy:\n  access: {access}\n", encoding="utf-8")
                before = {path.name: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                          for path in story.iterdir()}
                policy = storyforge.story_source_access(story)
                self.assertEqual(self.scaffold(prefix), story)
                self.assertEqual(storyforge.story_source_access(story), policy)
                self.assertEqual({path.name: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                                  for path in story.iterdir()}, before)
                self.assertEqual(self.private_attempts(prefix), [])

    def test_two_concurrent_pickers_publish_one_complete_scaffold(self):
        publish = picker._publish_scaffold
        barrier = threading.Barrier(2)

        def together(staged, story):
            barrier.wait(timeout=10)
            publish(staged, story)

        with patch.object(picker, "_publish_scaffold", together), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.scaffold) for _ in range(2)]
            self.assertEqual([future.result(timeout=15) for future in futures], [self.story, self.story])
        self.assert_denied_complete(self.story)
        self.assertEqual(len(self.private_attempts()), 1)

    def test_unsupported_native_publication_fails_closed_then_retry_can_publish(self):
        with patch.object(picker.sys, "platform", "unsupported"), self.assertRaisesRegex(OSError, "requires Linux"):
            self.scaffold()
        self.assertFalse(self.story.exists())
        self.assertEqual(storyforge.story_source_access(self.private_attempts()[0]), "denied")
        self.assert_denied_complete(self.scaffold())

    def test_darwin_exclusive_flag_mapping_and_native_errno(self):
        calls = []

        def rename(source, target, flags):
            calls.append((source, target, flags))
            ctypes.set_errno(errno.ENOTSUP)
            return -1

        libc = SimpleNamespace(renamex_np=rename)
        with (patch.object(picker.sys, "platform", "darwin"),
              patch.object(picker.ctypes, "CDLL", return_value=libc), self.assertRaises(OSError) as raised):
            picker._publish_scaffold(self.root / "private", self.story)
        self.assertEqual(raised.exception.errno, errno.ENOTSUP)
        self.assertEqual(calls, [(os.fsencode(self.root / "private"), os.fsencode(self.story), 4)])

    def test_abrupt_process_exits_before_and_after_publication_keep_retry_safe(self):
        code = """
from pathlib import Path
import importlib.util, os, shutil, sys
spec = importlib.util.spec_from_file_location('crash_picker', sys.argv[1])
picker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(picker)
root, point, prefix = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
picker.ROOT, picker.STORIES_DIR = root, root / 'stories'
write, copy, publish = Path.write_text, shutil.copy2, picker._publish_scaffold
def after_write(path, *args, **kwargs):
    result = write(path, *args, **kwargs)
    if (point == 'manifest' and path.name == 'story.yaml') or (point == 'card' and path.name == 'pick-card.json'):
        os._exit(73)
    return result
def after_copy(*args, **kwargs):
    result = copy(*args, **kwargs)
    if point == 'source': os._exit(73)
    return result
def around_publish(*args):
    if point == 'before-publish': os._exit(73)
    result = publish(*args)
    if point == 'after-publish': os._exit(73)
    return result
Path.write_text, shutil.copy2, picker._publish_scaffold = after_write, after_copy, around_publish
picker._scaffold_story({'slug': 'synthetic', 'source_path': 'corpus/synthetic/source.md'}, prefix, 'crash-run')
"""
        for point in ("manifest", "source", "card", "before-publish", "after-publish"):
            with self.subTest(point=point):
                prefix = "crash-" + point
                story = self.root / "stories" / f"{prefix}_synthetic"
                result = subprocess.run([sys.executable, "-c", code, str(SPEC.origin),
                                         str(self.root), point, prefix], capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 73, result.stderr)
                if point != "after-publish":
                    self.assertFalse(story.exists())
                    candidate = self.private_attempts(prefix)[0]
                    self.assertEqual(storyforge.story_source_access(candidate), "denied")
                    if point == "manifest":
                        self.assertFalse((candidate / "source.md").exists())
                else:
                    self.assert_denied_complete(story)
                self.assert_denied_complete(self.scaffold(prefix))


if __name__ == "__main__":
    unittest.main()
