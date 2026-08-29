"""Tests for the seed's failure bookkeeping.

The database work is not exercised here (per the project's testing rules), but
the decision of whether a run counts as successful is pure and is the single
most important thing this script gets right.
"""

from typing import Any

from api.ingest.client import FetchFailure
from api.ingest.seed import RecordError, SeedReport, _normalise_many


def _boom(payload: dict[str, Any]) -> dict[str, Any]:
    if payload["id"] == 2:
        raise KeyError("stats")
    return payload


class TestNormaliseMany:
    def test_one_bad_record_does_not_discard_the_good_ones(self) -> None:
        errors: list[RecordError] = []
        rows = _normalise_many([{"id": 1}, {"id": 2}, {"id": 3}], "pokemon", _boom, errors)
        assert [r["id"] for r in rows] == [1, 3]

    def test_the_failure_is_recorded_not_swallowed(self) -> None:
        errors: list[RecordError] = []
        _normalise_many([{"id": 2, "name": "ivysaur"}], "pokemon", _boom, errors)
        assert len(errors) == 1
        assert errors[0].identity == "ivysaur"
        assert "stats" in errors[0].error

    def test_records_fall_back_to_id_when_unnamed(self) -> None:
        errors: list[RecordError] = []
        _normalise_many([{"id": 2}], "pokemon", _boom, errors)
        assert errors[0].identity == "2"


class TestSeedReport:
    def test_clean_run_is_ok(self) -> None:
        assert SeedReport(counts={"pokemon": 1}).ok

    def test_fetch_failure_makes_the_run_not_ok(self) -> None:
        """This is what becomes a non-zero exit code."""
        report = SeedReport(fetch_failures=[FetchFailure(url="u", error="boom")])
        assert not report.ok

    def test_record_error_makes_the_run_not_ok(self) -> None:
        report = SeedReport(record_errors=[RecordError("pokemon", "ivysaur", "KeyError")])
        assert not report.ok

    def test_rows_written_do_not_excuse_errors(self) -> None:
        """A partially successful seed is a failed seed: silence here is the
        exact bug this reporting exists to prevent."""
        report = SeedReport(
            counts={"pokemon": 1025},
            record_errors=[RecordError("pokemon", "ivysaur", "KeyError")],
        )
        assert not report.ok
