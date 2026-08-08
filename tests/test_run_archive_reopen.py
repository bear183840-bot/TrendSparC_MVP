"""A question asked yesterday has to be openable today.

Only a summary of each run used to be kept - enough to count what happened
across runs, not enough to redraw one - so a report existed for exactly as
long as the browser tab did.
"""

from __future__ import annotations

import json

from common.contracts import UserRequest
from core.request_pipeline.pipeline import run_pipeline
from core.run_archive import list_runs, load_result, result_path


def _run(request_id: str, question: str):
    return run_pipeline(
        UserRequest(request_id=request_id, question=question, target_audience="practitioner"),
        dry_run=True,
    )


def test_a_finished_run_can_be_loaded_back(tmp_path, monkeypatch):
    import core.run_archive as archive

    monkeypatch.setattr(archive, "ARCHIVE_DIR", tmp_path)
    original = _run("reopen_me", "유료방송 가입자 추이는?")

    restored = archive.load_result("reopen_me")

    assert restored is not None
    assert restored.request_id == original.request_id
    assert [t.stage for t in restored.trace] == [t.stage for t in original.trace]


def test_the_index_stays_cheap_and_says_what_it_can_reopen(tmp_path, monkeypatch):
    """Listing reads summaries only - that's why the two files are separate."""
    import core.run_archive as archive

    monkeypatch.setattr(archive, "ARCHIVE_DIR", tmp_path)
    _run("has_result", "질문 하나")
    # A run archived before full results were stored: summary only.
    (tmp_path / "old_run.json").write_text(
        json.dumps({"request_id": "old_run", "question": "예전 질문"}), encoding="utf-8"
    )

    runs = {run["request_id"]: run for run in archive.list_runs()}

    assert runs["has_result"]["reopenable"] is True
    assert runs["old_run"]["reopenable"] is False
    # The result file is never listed as a run of its own.
    assert "has_result.result" not in runs


def test_a_missing_result_reads_as_none_rather_than_raising(tmp_path, monkeypatch):
    import core.run_archive as archive

    monkeypatch.setattr(archive, "ARCHIVE_DIR", tmp_path)

    assert archive.load_result("never_ran") is None
    assert not result_path("never_ran").exists()
