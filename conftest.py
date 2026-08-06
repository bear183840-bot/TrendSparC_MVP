import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def _archive_runs_to_tmp(tmp_path, monkeypatch):
    """Keep the run archive out of the real storage/requests during tests.

    run_pipeline archives every run by default so real usage builds a history
    worth diagnosing from; the suite calls it hundreds of times and would
    otherwise fill that directory with fixture noise and make the archive
    useless for its actual purpose.
    """
    from core import run_archive

    monkeypatch.setattr(run_archive, "ARCHIVE_DIR", tmp_path / "requests")
