"""Unit tests for knowledge-base helpers (URL extraction, HTML->text, context build)."""
from types import SimpleNamespace

from src.core.knowledge.service import extract_urls, html_to_text, build_reference_context


class TestExtractUrls:
    def test_finds_urls(self):
        urls = extract_urls("See https://www.usa.gov/health-insurance and http://cms.gov/x for info.")
        assert "https://www.usa.gov/health-insurance" in urls
        assert "http://cms.gov/x" in urls

    def test_trims_trailing_punctuation(self):
        assert extract_urls("ref: https://www.usa.gov/health-insurance.") == ["https://www.usa.gov/health-insurance"]

    def test_dedupes(self):
        u = "https://a.gov/p"
        assert extract_urls(f"{u} and again {u}") == [u]

    def test_none_and_empty(self):
        assert extract_urls(None) == []
        assert extract_urls("no links here") == []


class TestHtmlToText:
    def test_strips_tags_and_extracts_title(self):
        html = "<html><head><title>Health Insurance</title></head><body><h1>Plans</h1><p>HMO &amp; PPO</p></body></html>"
        text, title = html_to_text(html)
        assert title == "Health Insurance"
        assert "Plans" in text
        assert "HMO & PPO" in text          # entity unescaped
        assert "<" not in text and ">" not in text

    def test_drops_script_and_style(self):
        html = "<body><style>.x{color:red}</style><script>alert(1)</script><p>Keep this</p></body>"
        text, _ = html_to_text(html)
        assert "Keep this" in text
        assert "alert" not in text and "color:red" not in text

    def test_empty(self):
        assert html_to_text("") == ("", None)


class TestBuildReferenceContext:
    def test_empty_returns_empty_string(self):
        assert build_reference_context([]) == ""

    def test_renders_numbered_citations(self):
        refs = [
            SimpleNamespace(title="USA.gov Health Insurance", url="https://www.usa.gov/health-insurance",
                            content="Marketplace plans and Medicaid eligibility details."),
            SimpleNamespace(title="CMS Coverage", url=None, content="Medicare Part B coverage rules."),
        ]
        ctx = build_reference_context(refs)
        assert "[1] USA.gov Health Insurance (https://www.usa.gov/health-insurance)" in ctx
        assert "[2] CMS Coverage" in ctx
        assert "Marketplace plans" in ctx
        assert "REFERENCE MATERIAL" in ctx

    def test_truncates_long_content(self):
        refs = [SimpleNamespace(title="Long", url=None, content="x" * 5000)]
        ctx = build_reference_context(refs, max_chars_each=100)
        assert ctx.count("x") <= 100
