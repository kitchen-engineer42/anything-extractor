"""Git operations for the workflows repository."""

from __future__ import annotations

import logging
from pathlib import Path

from git import Repo
from git.exc import InvalidGitRepositoryError

from ae.config import get_settings

logger = logging.getLogger(__name__)


def ensure_workflows_repo() -> Repo:
    """Ensure the workflows directory is a git repo. Initialize if needed."""
    settings = get_settings()
    workflows_dir = settings.workflows_path
    workflows_dir.mkdir(parents=True, exist_ok=True)

    try:
        repo = Repo(str(workflows_dir))
    except InvalidGitRepositoryError:
        repo = Repo.init(str(workflows_dir))
        # Create initial .gitignore
        gitignore = workflows_dir / ".gitignore"
        gitignore.write_text("__pycache__/\n*.pyc\n.DS_Store\n")
        repo.index.add([".gitignore"])
        repo.index.commit("Initial commit: initialize workflows repository")
        logger.info("Initialized workflows git repository at %s", workflows_dir)

    return repo


def commit_workflow(
    task_name: str,
    version: int,
    code: str,
    message: str | None = None,
) -> tuple[str, str]:
    """Write workflow code and commit to git.

    Returns (module_path, commit_hash).
    """
    settings = get_settings()
    repo = ensure_workflows_repo()
    workflows_dir = settings.workflows_path

    # Create task directory
    task_dir = workflows_dir / task_name
    task_dir.mkdir(parents=True, exist_ok=True)

    # Write __init__.py if not exists
    init_file = task_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("")

    # Write workflow file
    filename = f"extract_v{version}.py"
    filepath = task_dir / filename
    filepath.write_text(code)

    # Module path relative to workflows dir
    module_path = f"{task_name}/{filename}"

    # Git add and commit
    repo.index.add([str(filepath.relative_to(workflows_dir))])
    if not init_file.exists() or repo.is_dirty(path=str(init_file.relative_to(workflows_dir))):
        repo.index.add([str(init_file.relative_to(workflows_dir))])

    if message is None:
        message = f"[{task_name}] Workflow v{version}"

    commit = repo.index.commit(message)
    commit_hash = commit.hexsha[:8]

    logger.info("Committed workflow: %s (commit: %s)", module_path, commit_hash)
    return module_path, commit_hash


def get_workflow_code(task_name: str, version: int) -> str:
    """Read workflow code from file."""
    settings = get_settings()
    filepath = settings.workflows_path / task_name / f"extract_v{version}.py"
    if not filepath.exists():
        raise FileNotFoundError(f"Workflow not found: {filepath}")
    return filepath.read_text()


def get_workflow_diff(task_name: str, v1: int, v2: int) -> str:
    """Get git diff between two workflow versions."""
    settings = get_settings()
    repo = ensure_workflows_repo()

    file1 = f"{task_name}/extract_v{v1}.py"
    file2 = f"{task_name}/extract_v{v2}.py"

    path1 = settings.workflows_path / file1
    path2 = settings.workflows_path / file2

    if not path1.exists() or not path2.exists():
        return f"Cannot diff: v{v1} or v{v2} not found"

    # Read both files and produce a simple diff
    text1 = path1.read_text()
    text2 = path2.read_text()

    import difflib
    diff = difflib.unified_diff(
        text1.splitlines(keepends=True),
        text2.splitlines(keepends=True),
        fromfile=f"extract_v{v1}.py",
        tofile=f"extract_v{v2}.py",
    )
    return "".join(diff)


def list_workflow_versions(task_name: str) -> list[int]:
    """List all workflow versions for a task."""
    settings = get_settings()
    task_dir = settings.workflows_path / task_name
    if not task_dir.exists():
        return []

    versions = []
    for f in task_dir.glob("extract_v*.py"):
        try:
            v = int(f.stem.replace("extract_v", ""))
            versions.append(v)
        except ValueError:
            pass
    return sorted(versions)
