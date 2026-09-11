"""Pytest fixtures."""

import shutil
import subprocess
from pathlib import Path

import pytest

from reducio.models import ComplexityMetrics

FIXTURE_REPO = Path(__file__).resolve().parents[1] / "test-python-code" / "python"


@pytest.fixture
def fixture_repo_root() -> Path:
    return FIXTURE_REPO


@pytest.fixture
def fixture_files():
    # Relies on walk() excluding .reducio/dotdirs so this stays Python-only;
    # if that exclusion regresses, scenario tests fail (intended signal).
    from reducio.repo import walk

    return walk(str(FIXTURE_REPO))


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """A throwaway copy of the fixture corpus so mutating commands stay hermetic."""
    dest = tmp_path / "python"
    shutil.copytree(
        FIXTURE_REPO,
        dest,
        ignore=shutil.ignore_patterns(".reducio", "__pycache__"),
    )
    return dest


@pytest.fixture
def sample_complexity_metrics() -> ComplexityMetrics:
    return ComplexityMetrics(
        cyclomatic_complexity=5,
        cognitive_complexity=3,
        lines_of_code=20,
    )


@pytest.fixture
def temp_git_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@e.com"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True
    )
    (repo / "main.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo
