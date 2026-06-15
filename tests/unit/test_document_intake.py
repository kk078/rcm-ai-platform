"""Unit tests for patient-document intake parsing helpers."""
from datetime import date

from src.core.document_intake.service import _parse_date, _money, _pct, DOC_TYPES


class TestParseDate:
    def test_formats(self):
        assert _parse_date("1/1/2026") == date(2026, 1, 1)
        assert _parse_date("2026-03-19") == date(2026, 3, 19)
        assert _parse_date("03/19/26") == date(2026, 3, 19)
        assert _parse_date("2/3/1972") == date(1972, 2, 3)

    def test_empty_and_garbage(self):
        assert _parse_date("") is None
        assert _parse_date(None) is None
        assert _parse_date("not a date") is None


class TestMoney:
    def test_money(self):
        assert _money("$25.00") == 25.0
        assert _money("1,500") == 1500.0
        assert _money("$2,500.50") == 2500.50
        assert _money(None) is None
        assert _money("n/a") is None


class TestPct:
    def test_pct(self):
        assert _pct("0.20") == 20      # decimal fraction
        assert _pct("20") == 20        # whole percent
        assert _pct("20%") == 20
        assert _pct(None) is None


def test_doc_types_include_eligibility():
    assert "eligibility_benefits" in DOC_TYPES
