"""Canonical source-access policy shared by external generation entry points."""
from pathlib import Path


def story_source_access(story: Path) -> str:
    """Preserve legacy access while respecting explicit or malformed denials."""
    manifest = story / "story.yaml"
    if not manifest.exists():
        return "trusted_runners_allowed"
    import yaml
    try:
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return "denied"
        if data.get("source_policy", {}).get("access") == "denied":
            return "denied"
    except (yaml.YAMLError, AttributeError):
        return "denied"
    return "trusted_runners_allowed"


class SourceAccessDenied(ValueError):
    """A source denial is independent of blueprint review or its bypass flag."""


def require_source_access(story: Path, runner: str = "codex") -> None:
    if story_source_access(story) == "denied":
        raise SourceAccessDenied(f"source_policy.access=denied blocks runner {runner}")
