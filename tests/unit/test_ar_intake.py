"""Unit tests for the AR aging-file importer parsing helpers."""
from src.core.ar_intake.service import _num, _bucket_and_priority, _decode, _reader


class TestNum:
    def test_money_formats(self):
        assert _num("1,712.50") == 1712.50
        assert _num("$33.59") == 33.59
        assert _num("(45.00)") == -45.00   # parenthesized credit
        assert _num("") == 0.0
        assert _num(None) == 0.0
        assert _num("n/a") == 0.0


class TestBucket:
    def test_by_aging_days(self):
        assert _bucket_and_priority("200", {}) == (">120", 95)
        assert _bucket_and_priority("100", {}) == ("91-120", 85)
        assert _bucket_and_priority("75", {}) == ("61-90", 75)
        assert _bucket_and_priority("45", {}) == ("31-60", 65)
        assert _bucket_and_priority("10", {}) == ("0-30", 45)

    def test_by_bucket_column_when_days_blank(self):
        assert _bucket_and_priority("", {"b_120p": "500.00"}) == (">120", 95)


class TestDecodeAndHeaders:
    def test_utf16_tab_file(self):
        raw = ("Payer Name\tPatient Name\tClaim No\tAging Days\tCharges\tBalance\r\n"
               "Aetna\tDOE, JOHN\tCLM1\t95\t200\t150.00\r\n").encode("utf-16")
        # decoder strips the UTF-16 BOM/NULs
        assert "Payer Name" in _decode(raw)
        reader = _reader(raw)
        assert "Claim No" in (reader.fieldnames or [])
