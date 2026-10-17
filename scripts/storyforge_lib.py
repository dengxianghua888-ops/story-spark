#!/usr/bin/env python3
"""Shared StoryForge automation helpers."""

from __future__ import annotations

import contextlib
import hashlib
import ctypes
import os
import sys
import tempfile
import uuid
import fnmatch
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


V4_PHASE_KEYS = {
    1: "phase1",
    2: "phase2",
    3: "draft",
    4: "review",
    5: "final",
}
PRODUCTION_PHASE_KEYS = {
    1: "market_brief",
    2: "source_dissection",
    3: "adaptation_room",
    4: "beat_bible",
    5: "scene_writer",
    6: "critic_gauntlet",
    7: "final_packager",
    8: "feedback_learning",
}
PRODUCTION_V6_PHASE_KEYS = {
    1: "market_brief",
    2: "source_dissection_v2",
    3: "adaptation_room",
    4: "hook_writer",
    5: "beat_bible_v2",
    6: "scene_writer_v2",
    7: "critic_gauntlet",
    8: "final_packager",
    9: "feedback_learning",
}
PHASE_KEYS_BY_MODE = {
    "v4": V4_PHASE_KEYS,
    "production": PRODUCTION_PHASE_KEYS,
    "production_v6": PRODUCTION_V6_PHASE_KEYS,
    "ultra_short": PRODUCTION_PHASE_KEYS,
}


@dataclass(frozen=True)
class PhaseBundle:
    phase: int
    key: str
    role: str
    title: str
    system_prompt: str
    required_inputs: List[str]
    required_outputs: List[str]
    validators: List[str]
    human_gate: str
    retryable: bool


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o7777)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if " #" in value:
        value = value.split(" #", 1)[0].strip()
    value = value.strip("'\"")
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() in {"null", "~"}:
        return None
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in inner.split(",")]
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def parse_simple_yaml(path: Path) -> Dict[str, Any]:
    """Parse the limited YAML subset used by phase bundles and manifests."""
    data: Dict[str, Any] = {}
    current_key: str | None = None
    for raw in read_text(path).splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith("  - ") and current_key:
            data.setdefault(current_key, []).append(_parse_scalar(raw.strip()[2:]))
            continue
        if not raw.startswith((" ", "\t")) and ":" in raw:
            key, value = raw.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value == "":
                data[key] = []
                current_key = key
            else:
                data[key] = _parse_scalar(value)
                current_key = None
    return data


def normalize_pipeline_mode(mode: str | None) -> str:
    value = (mode or "v4").strip().lower()
    if value in {"", "full", "fast", "v4"}:
        return "v4"
    if value in {"production", "prod"}:
        return "production"
    if value in {"production_v6", "prod_v6", "v6"}:
        return "production_v6"
    if value in {"ultra_short", "ultrashort", "short"}:
        return "ultra_short"
    raise ValueError(f"unknown pipeline mode: {mode}")


def phase_keys_for_mode(mode: str | None = None) -> Dict[int, str]:
    normalized = normalize_pipeline_mode(mode)
    return PHASE_KEYS_BY_MODE[normalized]


def phase_for_role(mode: str | None, role: str) -> int:
    """Canonical role coordinates shared by runners, validators and repairs."""
    keys = {"critic": "critic_gauntlet", "final": "final_packager",
            "scene": "scene_writer", "beat": "beat_bible", "feedback": "feedback_learning"}
    if normalize_pipeline_mode(mode) == "v4":
        return {"critic": 4, "final": 5, "scene": 3, "beat": 2}[role]
    key = keys[role]
    for phase, name in phase_keys_for_mode(mode).items():
        if name == key or name == key + "_v2":
            return phase
    raise ValueError(f"No {role} phase for {mode}")


@contextlib.contextmanager
def story_write_lock(story: Path):
    """A stable sibling lock survives directory exchanges and process crashes."""
    import fcntl
    story = story.resolve()
    lock_path = story.parent / f".{story.name}.storyforge.lock"
    with lock_path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Story already has an active writer") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def story_fingerprint(story: Path):
    result = {}
    for path in story.rglob("*"):
        if path.is_symlink():
            raise ValueError("Staging refuses symlinked story content")
        if path.is_file() and "runs" not in path.relative_to(story).parts:
            result[str(path.relative_to(story))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result



class StagedStory:
    """Validate an isolated tree, then atomically exchange it with the live story.

    Old trees are retained as unique sibling attempt backups. No delete/rename
    fallback is used: unsupported filesystems/platforms fail without publication.
    A single writer must own a story during a run (including external editors).
    """

    def __init__(self, story: Path, run_dir: Path, phase: int):
        self.story = story.resolve()
        self.run_dir = run_dir.resolve()
        self.phase = phase
        self.parent = Path(tempfile.mkdtemp(prefix=f".{story.name}.attempt-", dir=self.story.parent))
        self.path = self.parent / story.name
        self.published = False
        self.diagnostics = [self.run_dir / f"phase{phase}.{suffix}" for suffix in
                            ["runner.log", "validator.log", "rubric.log", "parse-report.json", "normalizer.log"]]
        self.diagnostic_baseline = {p.name: self._diagnostic_version(p)
                                    for p in self.diagnostics if p.is_file()}
        write_json(self.parent / "attempt.json", {"story": str(self.story), "phase": phase,
                   "tree": str(self.path), "status": "staging"})

    @staticmethod
    def _diagnostic_version(path):
        stat = path.stat()
        return (stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, path.read_bytes())

    def __enter__(self):
        if any(path.is_symlink() for path in self.story.rglob("*")):
            raise ValueError("Staging refuses symlinked story content")
        self.fingerprint = story_fingerprint(self.story)
        shutil.copytree(self.story, self.path)
        return self

    def publish(self):
        if story_fingerprint(self.story) != self.fingerprint:
            raise OSError("Story changed during validation; candidate retained without publication")
        # Logs were written to the live run while validators read the staging tree.
        if self.run_dir.is_relative_to(self.story) and self.run_dir.exists():
            destination = self.path / self.run_dir.relative_to(self.story)
            shutil.copytree(self.run_dir, destination, dirs_exist_ok=True)
        write_json(self.parent / "attempt.json", {"story": str(self.story), "phase": self.phase,
                   "tree": str(self.path), "status": "exchange_pending",
                   "original_fingerprint": self.fingerprint,
                   "candidate_fingerprint": story_fingerprint(self.path),
                   "note": "After a successful exchange this tree is the previous live story"})
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
            exchange = libc.renameat2
            exchange.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            exchange.restype = ctypes.c_int
            result = exchange(-100, os.fsencode(self.story), -100, os.fsencode(self.path), 2)
        elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
            exchange = libc.renamex_np
            exchange.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            exchange.restype = ctypes.c_int
            result = exchange(os.fsencode(self.story), os.fsencode(self.path), 2)
        else:
            raise OSError("Atomic story exchange requires Linux renameat2 or macOS renamex_np")
        if result != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))
        self.published = True
        # The former live tree remains at self.path, never overwriting an attempt.

    def __exit__(self, *exc):
        # Retry reasoning reads rejected candidates explicitly, never as live artifacts.
        feedback = self.run_dir / "retry-feedback.json"
        try:
            if not self.published and self.path.exists():
                diagnostics = []
                for source in self.diagnostics:
                    if source.is_file() and self._diagnostic_version(source) != self.diagnostic_baseline.get(source.name):
                        destination = self.parent / "diagnostics" / source.name
                        destination.parent.mkdir(exist_ok=True)
                        shutil.copy2(source, destination)
                        diagnostics.append(source.name)
                write_json(feedback, {"status": "failed", "phase": self.phase,
                                      "candidate": str(self.path), "diagnostics": diagnostics,
                                      "changed_files": [name for name, digest in story_fingerprint(self.path).items()
                                                        if self.fingerprint.get(name) != digest]})
            elif self.published and feedback.exists():
                previous = json.loads(feedback.read_text(encoding="utf-8"))
                if self.phase >= previous.get("phase", self.phase):
                    write_json(feedback, {**previous, "status": "resolved"})
        except (OSError, ValueError):
            # A failed audit write must not turn a completed exchange into failure.
            pass
        return False


def retry_feedback_prompt(story: Path, run_dir: Path) -> tuple[str, dict]:
    path = run_dir / "retry-feedback.json"
    if not path.exists():
        return "", {}
    feedback = json.loads(path.read_text(encoding="utf-8"))
    if feedback.get("status") != "failed":
        return "", {}
    candidate = Path(feedback["candidate"]).resolve()
    live = story.resolve()
    if (candidate.name != live.name or candidate.parent.parent != live.parent
            or not candidate.parent.name.startswith(f".{live.name}.attempt-")):
        raise ValueError("Retry candidate is not a retained attempt for this story")
    parts = ["## Rejected attempt feedback (not approved artifacts)",
             "Use the following failed-attempt findings for targeted corrections. "
             "Keep this phase's output whitelist and current source policy unchanged."]
    included = []
    for name in ["quality-report.json", "review.md", "diff.md", "scene-rewrite-todo.json",
                 "source-rhythm-rewrite-todo.json", "scene-forbidden-scan.json", "repair-report.json"]:
        source = candidate / name
        if name in feedback.get("changed_files", []) and source.is_file() and source.resolve().is_relative_to(candidate):
            parts.extend([f"### Failed attempt: {name}", source.read_text(encoding="utf-8")])
            included.append(name)
    for name in feedback.get("diagnostics", []):
        source = candidate.parent / "diagnostics" / name
        if Path(name).name != name:
            raise ValueError("Invalid retry diagnostic name")
        if source.is_file():
            parts.extend([f"### Failure diagnostic: {source.name}", source.read_text(encoding="utf-8")])
            included.append(source.name)
    return "\n\n".join(parts), {**feedback, "included": included}


def phase_count(mode: str | None = None) -> int:
    return max(phase_keys_for_mode(mode))


def phase_bundle_path(phase: int, root: Path | None = None, mode: str | None = None) -> Path:
    root = root or repo_root()
    normalized = normalize_pipeline_mode(mode)
    if normalized == "production_v6":
        bundle_dir = "production-v6-phase-bundles"
    elif normalized in {"production", "ultra_short"}:
        bundle_dir = "production-phase-bundles"
    else:
        bundle_dir = "phase-bundles"
    return root / "prompts" / bundle_dir / f"phase{phase}.yaml"


def load_phase_bundle(phase: int, root: Path | None = None, mode: str | None = None) -> PhaseBundle:
    path = phase_bundle_path(phase, root, mode)
    if not path.exists():
        raise ValueError(f"missing phase bundle: {path}")
    data = parse_simple_yaml(path)
    required = ["phase", "key", "role", "title", "system_prompt", "required_outputs"]
    missing = [key for key in required if key not in data or data[key] in ("", [], None)]
    if missing:
        raise ValueError(f"{path}: missing required keys: {', '.join(missing)}")
    if int(data["phase"]) != phase:
        raise ValueError(f"{path}: phase mismatch, expected {phase}")
    outputs = list(data.get("required_outputs", []))
    if not outputs:
        raise ValueError(f"{path}: required_outputs cannot be empty")
    return PhaseBundle(
        phase=phase,
        key=str(data["key"]),
        role=str(data["role"]),
        title=str(data["title"]),
        system_prompt=str(data["system_prompt"]),
        required_inputs=list(data.get("required_inputs", [])),
        required_outputs=outputs,
        validators=list(data.get("validators", [])),
        human_gate=str(data.get("human_gate", "none")),
        retryable=bool(data.get("retryable", False)),
    )


def load_all_phase_bundles(root: Path | None = None, mode: str | None = None) -> Dict[int, PhaseBundle]:
    return {phase: load_phase_bundle(phase, root, mode) for phase in range(1, phase_count(mode) + 1)}


def validate_bundle_schema(root: Path | None = None, mode: str | None = None) -> None:
    normalized = normalize_pipeline_mode(mode)
    bundles = load_all_phase_bundles(root, normalized)
    phase_keys = phase_keys_for_mode(normalized)
    seen_outputs: set[str] = set()
    for phase, bundle in bundles.items():
        if bundle.key != phase_keys[phase]:
            raise ValueError(f"phase {phase}: key must be {phase_keys[phase]!r}")
        for rel in bundle.required_outputs:
            validate_safe_relpath(rel)
            if "*" not in rel and rel in seen_outputs:
                raise ValueError(f"artifact {rel!r} appears in more than one phase")
            if "*" not in rel:
                seen_outputs.add(rel)


def resolve_input_path(story: Path, rel: str, root: Path | None = None) -> Path:
    root = root or repo_root()
    if rel.startswith("story/"):
        return story / rel[len("story/") :]
    return root / rel


def expand_input_paths(story: Path, rel: str, root: Path | None = None) -> List[Tuple[str, Path]]:
    root = root or repo_root()
    if "*" not in rel:
        return [(rel, resolve_input_path(story, rel, root))]
    base = story if rel.startswith("story/") else root
    pattern = rel[len("story/") :] if rel.startswith("story/") else rel
    matches = sorted(path for path in base.glob(pattern) if path.is_file())
    if not matches:
        return [(rel, resolve_input_path(story, rel, root))]
    label_prefix = "story/" if rel.startswith("story/") else ""
    return [(label_prefix + str(path.relative_to(base)), path) for path in matches]


def render_phase_prompt(story: Path, phase: int, root: Path | None = None, mode: str | None = None) -> Tuple[str, Dict[str, Any]]:
    root = root or repo_root()
    normalized = normalize_pipeline_mode(mode)
    bundle = load_phase_bundle(phase, root, normalized)
    if phase == phase_for_role(normalized, "scene") and (story / "continuity-ledger.json").exists():
        raise ValueError("Continuity ledger requires position-isolated prompts; use generate_scene_batches.py")
    parts = [
        f"# StoryForge {normalized} Phase {phase}: {bundle.title}",
        "",
        f"Role: {bundle.role}",
        "",
        f"你正在执行 StoryForge {normalized} 自动产线。必须只输出 artifact bundle 文件块，不要直接修改文件系统。",
        "",
        "## Output Protocol",
        "",
        "每个产物必须使用以下格式：",
        "",
        "<<<FILE: relative/path.md>>>",
        "文件内容",
        "<<<END FILE>>>",
        "",
        "禁止输出绝对路径、.. 路径或未列入 required outputs 的文件。",
        "若 required outputs 包含通配符(如 scene-cards/*.json),可以输出匹配该通配符的多个文件。",
        "",
        "## Required Outputs",
        "",
    ]
    parts.extend(f"- {rel}" for rel in bundle.required_outputs)
    parts.extend(["", "## Source Materials", ""])
    manifest_inputs = []
    for rel in [bundle.system_prompt, *bundle.required_inputs]:
        for label, path in expand_input_paths(story, rel, root):
            manifest_inputs.append({"label": label, "path": str(path), "exists": path.exists()})
            parts.append(f"### {label}")
            parts.append("")
            if path.exists():
                if path.name == "story.yaml":
                    # Operational gate/run metadata is not model input.
                    import yaml
                    data = yaml.safe_load(read_text(path)) or {}
                    if not isinstance(data, dict):
                        raise ValueError("story.yaml must be a mapping")
                    data.pop("automation", None)
                    parts.append(yaml.safe_dump(data, allow_unicode=True, sort_keys=True))
                else:
                    parts.append(read_text(path))
            else:
                parts.append(f"[MISSING INPUT: {path}]")
            parts.append("")
    manifest = {
        "phase": phase,
        "role": bundle.role,
        "mode": normalized,
        "story": str(story),
        "bundle": str(phase_bundle_path(phase, root, normalized)),
        "required_outputs": bundle.required_outputs,
        "inputs": manifest_inputs,
        "rendered_at": now_stamp(),
    }
    return "\n".join(parts).rstrip() + "\n", manifest


def validate_safe_relpath(rel: str) -> Path:
    path = Path(rel)
    if path.is_absolute():
        raise ValueError(f"absolute artifact paths are not allowed: {rel}")
    if any(part == ".." for part in path.parts):
        raise ValueError(f"artifact path cannot contain '..': {rel}")
    if not str(path).strip():
        raise ValueError("artifact path cannot be empty")
    return path


def _repair_json_quotes(content: str) -> str:
    """Repair unescaped ASCII quotes inside JSON string values (common LLM issue with Chinese text)."""
    try:
        json.loads(content)
        return content
    except (json.JSONDecodeError, ValueError):
        pass
    lines = content.split('\n')
    for i, line in enumerate(lines):
        match = re.match(r'^(\s*"[^"]+"\s*:\s*)"(.+)"(\s*,?\s*)$', line)
        if match:
            prefix, value, suffix = match.group(1), match.group(2), match.group(3)
            if '"' in value:
                new_val = []
                q_open = True
                for ch in value:
                    if ch == '"':
                        new_val.append('“' if q_open else '”')
                        q_open = not q_open
                    else:
                        new_val.append(ch)
                lines[i] = f'{prefix}"{"".join(new_val)}"{suffix}'
    fixed = '\n'.join(lines)
    try:
        json.loads(fixed)
        return fixed
    except (json.JSONDecodeError, ValueError):
        return content


FILE_BLOCK_RE = re.compile(
    r"^<<<FILE:\s*(?P<path>[^>\n]+?)\s*>>>\s*\n(?P<content>.*?)\n?^<<<END FILE>>>\s*$",
    re.MULTILINE | re.DOTALL,
)

FILE_BLOCK_UNCLOSED_RE = re.compile(
    r"^<<<FILE:\s*(?P<path>[^>\n]+?)\s*>>>\s*\n(?P<content>.+)",
    re.MULTILINE | re.DOTALL,
)


def _matches_output_pattern(rel: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(rel, pattern) if "*" in pattern else rel == pattern


def _is_allowed_output(rel: str, allowed_patterns: set[str]) -> bool:
    return any(_matches_output_pattern(rel, pattern) for pattern in allowed_patterns)


def _missing_output_patterns(parsed_paths: set[str], allowed_patterns: set[str]) -> List[str]:
    missing = []
    for pattern in sorted(allowed_patterns):
        if "*" in pattern:
            if not any(_matches_output_pattern(path, pattern) for path in parsed_paths):
                missing.append(pattern)
        elif pattern not in parsed_paths:
            missing.append(pattern)
    return missing


def parse_artifact_bundle(text: str) -> Dict[str, str]:
    files: Dict[str, str] = {}
    for match in FILE_BLOCK_RE.finditer(text):
        rel = str(validate_safe_relpath(match.group("path").strip()))
        content = match.group("content")
        if not content.strip():
            raise ValueError(f"artifact block is empty: {rel}")
        files[rel] = content.rstrip() + "\n"
    if not files:
        match = FILE_BLOCK_UNCLOSED_RE.search(text)
        if match:
            rel = str(validate_safe_relpath(match.group("path").strip()))
            content = match.group("content")
            if content.strip():
                files[rel] = content.rstrip() + "\n"
    if not files:
        raise ValueError("no artifact blocks found")
    return files


def write_json(path: Path, data: Dict[str, Any]) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def apply_artifact_bundle(story: Path, phase: int, bundle_text: str, run_dir: Path,
                          root: Path | None = None, mode: str | None = None,
                          *, staged: bool = False) -> Dict[str, Any]:
    if staged:
        return _apply_artifact_bundle(story, phase, bundle_text, run_dir, root, mode)
    with story_write_lock(story), StagedStory(story, run_dir, phase) as candidate:
        report = _apply_artifact_bundle(candidate.path, phase, bundle_text, run_dir, root, mode)
        candidate.publish()
        return report


def _apply_artifact_bundle(
    story: Path,
    phase: int,
    bundle_text: str,
    run_dir: Path,
    root: Path | None = None,
    mode: str | None = None,
) -> Dict[str, Any]:
    root = root or repo_root()
    phase_bundle = load_phase_bundle(phase, root, mode)
    allowed = set(phase_bundle.required_outputs)
    parsed = parse_artifact_bundle(bundle_text)
    # Strip "story/" prefix if model added it (common LLM output quirk)
    parsed = {k.removeprefix("story/"): v for k, v in parsed.items()}
    unknown = sorted(path for path in set(parsed) if not _is_allowed_output(path, allowed))
    if unknown:
        raise ValueError("artifact bundle contains files not allowed for this phase: " + ", ".join(unknown))
    missing = _missing_output_patterns(set(parsed), allowed)
    if missing:
        raise ValueError("artifact bundle missing required outputs: " + ", ".join(missing))

    backup_dir = run_dir / "backups" / f"phase{phase}" / uuid.uuid4().hex
    # The supplied wildcard set replaces the previous set, rather than mixing runs.
    stale = set()
    for pattern in allowed:
        if "*" in pattern:
            stale.update(path for path in story.glob(pattern) if path.is_file()
                         and str(path.relative_to(story)) not in parsed)
    written = []
    backed_up = []
    for target in sorted(stale):
        if not target.resolve().is_relative_to(story.resolve()):
            raise ValueError("Stale artifact path escapes story directory")
        rel = str(target.relative_to(story))
        backup = backup_dir / rel
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        backed_up.append(rel)
        target.unlink()
    for rel, content in parsed.items():
        target = story / validate_safe_relpath(rel)
        if not target.resolve().is_relative_to(story.resolve()):
            raise ValueError(f"artifact path escapes story directory: {rel}")
        if target.exists():
            backup = backup_dir / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            backed_up.append(rel)
        if rel == "story.yaml":
            # Generated metadata is never an independent source-access approval.
            import yaml
            previous = yaml.safe_load(target.read_text(encoding="utf-8")) if target.exists() else {}
            replacement = yaml.safe_load(content)
            if not isinstance(replacement, dict):
                raise ValueError("story.yaml must contain an object")
            if "source_policy" in (previous or {}):
                replacement["source_policy"] = previous["source_policy"]
            else:
                replacement.pop("source_policy", None)
            content = yaml.safe_dump(replacement, allow_unicode=True, sort_keys=False)
        # Auto-repair JSON files with unescaped quotes (common LLM generation issue)
        if rel.endswith(".json"):
            content = _repair_json_quotes(content)
        write_text(target, content)
        written.append(rel)
    report = {
        "phase": phase,
        "status": "success",
        "written": sorted(written),
        "backed_up": sorted(backed_up),
        "backup_dir": str(backup_dir),
        "removed_stale": sorted(str(path.relative_to(story)) for path in stale),
        "required_outputs": phase_bundle.required_outputs,
        "mode": normalize_pipeline_mode(mode),
        "generated_at": now_stamp(),
    }
    write_json(run_dir / f"phase{phase}.parse-report.json", report)
    return report


def phase_range(from_phase: int) -> Iterable[int]:
    return range(from_phase, 6)


def phase_key(phase: int, mode: str | None = None) -> str:
    return phase_keys_for_mode(mode)[phase]
