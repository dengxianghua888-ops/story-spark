"""Actual local subprocess regressions; no model/provider is invoked."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("corpus_parallel", ROOT / "scripts/run-corpus-phase1-parallel.py")
parallel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parallel)


class CorpusParallelTimeoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="story-parallel-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "scripts").mkdir()
        self.story = self.root / "story"
        self.story.mkdir()
        self.row = {"slug": "story", "filename": "synthetic.txt", "word_count": 3, "story": self.story}
        setting = patch.object(parallel, "ROOT", self.root)
        setting.start()
        self.addCleanup(setting.stop)

    def script(self, content):
        (self.root / "scripts/storyforge.py").write_text(content, encoding="utf-8")

    def run_one(self, timeout=0.3):
        return parallel.run_one(self.row, "mock", "", timeout, 1)

    def test_partial_timeout_is_json_serializable_and_keeps_both_streams(self):
        self.script("import os,time\nos.write(1,b'partial stdout\\xe4')\n"
                    "os.write(2,b'partial stderr\\xe4')\ntime.sleep(3)\n")
        result = self.run_one()
        self.assertEqual(result["exit_code"], 124)
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["stdout_tail"], "partial stdout\ufffd")
        self.assertEqual(result["stderr_tail"], "partial stderr\ufffd")
        log = self.root / "results.jsonl"
        parallel.append_jsonl(log, result, threading.Lock())
        self.assertEqual(json.loads(log.read_text())["exit_code"], 124)
        self.assertFalse((self.story / "dissection.md").exists())

    def test_silent_timeout_keeps_empty_text_streams(self):
        self.script("import time\ntime.sleep(3)\n")
        result = self.run_one()
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["stdout_tail"], "")
        self.assertEqual(result["stderr_tail"], "")
        json.dumps(result)

    @unittest.skipUnless(os.name == "posix", "process groups are the POSIX runner contract")
    def test_timeout_stops_own_descendant_without_killing_other_invocation(self):
        marker = self.root / "descendant-completed"
        ready = self.root / "descendant-ready"
        child = ("import pathlib,time;pathlib.Path(" + repr(str(ready)) + ").write_text('ready');"
                 "time.sleep(1);pathlib.Path(" + repr(str(marker)) + ").write_text('unexpected')")
        self.script("import subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c'," + repr(child) + "])\n"
                    "print('local descendant started',flush=True)\ntime.sleep(3)\n")
        other_marker = self.root / "independent-completed"
        with subprocess.Popen([sys.executable, "-c",
                               "import pathlib,time;time.sleep(0.7);pathlib.Path(" +
                               repr(str(other_marker)) + ").write_text('preserved')"]) as other:
            result = self.run_one(timeout=0.5)
            self.assertTrue(ready.exists(), "synthetic descendant must actually have started")
            self.assertTrue(result["timed_out"])
            other.wait(timeout=3)
        time.sleep(0.7)
        self.assertFalse(marker.exists())
        self.assertEqual(other_marker.read_text(), "preserved")

    def test_success_without_timeout_keeps_text_and_requires_dissection(self):
        self.script("import pathlib,sys\npathlib.Path(" + repr(str(self.story / "dissection.md")) +
                    ").write_text('synthetic local result')\nprint('stdout')\nprint('stderr',file=sys.stderr)\n")
        result = self.run_one(timeout=0)
        self.assertTrue(result["ok"])
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout_tail"], "stdout\n")
        self.assertEqual(result["stderr_tail"], "stderr\n")
        json.dumps(result)

    @unittest.skipUnless(os.name == "posix", "process groups are the POSIX runner contract")
    def test_detached_pipe_owner_does_not_block_timeout_result(self):
        ready = self.root / "detached-ready"
        release = self.root / "release-detached"
        finished = self.root / "detached-finished"
        child = ("import pathlib,time\nready=pathlib.Path(" + repr(str(ready)) + ")\n"
                 "release=pathlib.Path(" + repr(str(release)) + ")\n"
                 "ready.write_text('ready')\ndeadline=time.monotonic()+5\n"
                 "while not release.exists() and time.monotonic()<deadline:time.sleep(0.02)\n"
                 "pathlib.Path(" + repr(str(finished)) + ").write_text('finished')\n")
        self.script("import os,subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c'," +
                    repr(child) + "],start_new_session=True)\nos.write(1,b'partial detached\\xe4')\n"
                    "os.write(2,b'partial stderr\\xe4')\ntime.sleep(10)\n")
        try:
            result = self.run_one(timeout=1)
            self.assertTrue(ready.exists(), "detached local child must actually have started")
            self.assertFalse(finished.exists(), "result must return while the detached pipe owner is still waiting")
            self.assertTrue(result["timed_out"])
            self.assertEqual(result["exit_code"], 124)
            self.assertEqual(result["stdout_tail"], "partial detached\ufffd")
            self.assertEqual(result["stderr_tail"], "partial stderr\ufffd")
            json.dumps(result)
        finally:
            # The detached child is outside the group's termination promise.
            # Let only our finite fixture exit naturally; do not signal its group.
            release.touch()
            deadline = time.monotonic() + 5
            while not finished.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(finished.exists())

    def test_nonzero_exit_and_missing_dissection_do_not_count_as_success(self):
        for code in [0, 7]:
            with self.subTest(code=code):
                self.script("import sys\nprint('ordinary failure')\nsys.exit(" + str(code) + ")\n")
                result = self.run_one(timeout=0)
                self.assertFalse(result["ok"])
                self.assertFalse(result["timed_out"])
                self.assertEqual(result["exit_code"], code)
                self.assertEqual(result["stdout_tail"], "ordinary failure\n")

    def test_batch_records_timeout_and_other_result_then_refreshes_index(self):
        slow = self.root / "slow"
        slow.mkdir()
        rows = [dict(self.row, slug="slow", story=slow), self.row]
        self.script("import pathlib,sys,time\n"
                    "story=pathlib.Path(sys.argv[sys.argv.index('--story')+1])\n"
                    "print('synthetic '+story.name,flush=True)\n"
                    "if story.name=='slow':time.sleep(3)\n"
                    "(story/'dissection.md').write_text('synthetic result')\n")
        refreshed = self.root / "index-refreshed"
        (self.root / "scripts/update-corpus-index.py").write_text(
            "import pathlib\npathlib.Path(" + repr(str(refreshed)) + ").write_text('yes')\n")
        log = self.root / "results.jsonl"
        with patch.object(parallel, "pending_entries", return_value=rows), patch.object(sys, "argv", [
                "run-corpus-phase1-parallel.py", "--corpus", str(self.root),
                "--runner", "mock", "--jobs", "2", "--timeout-seconds", "1", "--log", str(log)]):
            self.assertEqual(parallel.main(), 1)
        results = {row["slug"]: row for row in map(json.loads, log.read_text().splitlines())}
        self.assertEqual(set(results), {"slow", "story"})
        self.assertEqual(results["slow"]["exit_code"], 124)
        self.assertTrue(results["story"]["ok"])
        self.assertTrue(refreshed.exists())
