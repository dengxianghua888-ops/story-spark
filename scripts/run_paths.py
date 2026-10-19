"""Keep run diagnostics and approval records inside their owning story."""
from pathlib import Path


def run_directory(story: Path, run_id: str) -> Path:
    """Validate before any run output is created; do not follow run symlinks.

    As with story publication, callers must hold the story writer lock. This
    check does not claim protection against an uncooperative filesystem writer.
    """
    if (not isinstance(run_id, str) or not run_id.strip()
            or run_id in {".", ".."} or "/" in run_id or "\\" in run_id
            or "\x00" in run_id or Path(run_id).is_absolute()):
        raise ValueError("Run ID must be a single non-empty directory name")
    runs = story / "runs"
    target = runs / run_id
    if runs.is_symlink() or target.is_symlink():
        raise ValueError("Run directory must not be symlinked")
    if target.exists() and not target.is_dir():
        raise ValueError("Run directory must be a directory")
    if target.exists() and any(path.is_symlink() for path in target.rglob("*")):
        raise ValueError("Run directory must not contain symlinked content")
    if not target.resolve().is_relative_to(story.resolve() / "runs"):
        raise ValueError("Run directory must remain inside story/runs")
    return target
