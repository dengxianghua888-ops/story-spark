"""Content-addressed approval and resume identities. Never infer historical consent."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import yaml

from storyforge_lib import expand_input_paths, load_phase_bundle, phase_bundle_path, phase_for_role


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def content(path: Path):
    if not path.is_file():
        return None
    if path.name == "story.yaml":
        data = yaml.safe_load(path.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError("story.yaml must be a mapping")
        data.pop("automation", None)
        return digest(data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configuration(args):
    # Hash environment values rather than persist potentially private commands.
    env = {k: digest(v) for k, v in os.environ.items()
           if k.startswith("STORYFORGE_") and k != "STORYFORGE_HEARTBEAT_SECONDS"}
    env["STORYFORGE_CODEX_REASONING_EFFORT"] = digest(
        getattr(args, "effort", os.environ.get("STORYFORGE_CODEX_REASONING_EFFORT", "medium")).strip())
    return {"mode": args.mode, "runner": args.runner, "model": args.model,
            "skip_rubric": getattr(args, "skip_rubric", False),
            "rubric_threshold": getattr(args, "rubric_threshold", None), "environment": env}


def dependencies(root: Path):
    # Include runner defaults, validators and their local helpers, templates and rules.
    paths = [root / "workspace.yaml"]
    for folder, pattern in [("scripts", "*.py"), ("prompts", "*"),
                            ("templates", "*"), ("context", "*")]:
        paths.extend(p for p in (root / folder).rglob(pattern)
                     if p.is_file() and p.suffix in {".py", ".md", ".json", ".yaml", ".yml", ".txt"})
    return {str(p.relative_to(root)): content(p) for p in sorted(paths)}


def phase_inputs(story, phase, root, mode):
    bundle = load_phase_bundle(phase, root, mode)
    values = {}
    for rel in [bundle.system_prompt, *bundle.required_inputs]:
        for label, path in expand_input_paths(story, rel, root):
            values[label] = content(path)
    # Authorization policy is relevant even when omitted from the prompt bundle.
    metadata = yaml.safe_load((story / "story.yaml").read_text()) if (story / "story.yaml").exists() else {}
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("story.yaml must be a mapping")
    values["source_policy"] = digest((metadata or {}).get("source_policy", {}))
    return values


def outputs(story, phase, root, mode):
    result = {}
    for rel in load_phase_bundle(phase, root, mode).required_outputs:
        for label, path in expand_input_paths(story, "story/" + rel, root):
            result[label] = content(path)
    return result


def snapshot(story, phase, root, config, *, prompt=None):
    data = {"version": 1, "phase": phase, "configuration": config,
            "inputs": phase_inputs(story, phase, root, config["mode"]),
            "dependencies": dependencies(root),
            "bundle": content(phase_bundle_path(phase, root, config["mode"]))}
    if prompt is not None:
        data["prompt"] = digest(prompt)
    return {"identity": digest(data), "data": data}


def approval_snapshot(story, root, config):
    phase = phase_for_role(config["mode"], "beat")
    result = snapshot(story, phase, root, config)
    result["data"]["upstream_inputs"] = {
        str(p): phase_inputs(story, p, root, config["mode"]) for p in range(1, phase + 1)}
    result["data"]["candidate"] = outputs(story, phase, root, config["mode"])
    result["identity"] = digest(result["data"])
    return result


def require_approval(story, run_dir, root, args):
    path = run_dir / "blueprint-approval.json"
    if not path.is_file():
        raise ValueError("Blueprint approval snapshot missing; explicitly approve this run before continuing")
    record = json.loads(path.read_text())
    if not isinstance(record, dict):
        raise ValueError("Blueprint approval record is invalid; re-approve this run")
    current = approval_snapshot(story, root, configuration(args))
    if record.get("snapshot") != current:
        raise ValueError("Blueprint approval is stale; inputs, candidate, prompts, rules or model changed. Re-approve this run")
