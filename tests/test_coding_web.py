"""Tests for web search and web fetch."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# web_search
# ---------------------------------------------------------------------------

def test_web_search_returns_structured_results() -> None:
    from hermes_lite.coding.web import web_search

    result = web_search("python pytest tutorial", limit=3)
    assert result["ok"] is True
    assert isinstance(result["results"], list)
    assert result["count"] == len(result["results"])
    for r in result["results"]:
        assert isinstance(r["title"], str)
        assert isinstance(r["url"], str)
        assert isinstance(r["snippet"], str)


def test_web_search_empty_query() -> None:
    from hermes_lite.coding.web import web_search

    result = web_search("")
    assert result["ok"] is False
    assert result["error"] == "empty_query"


def test_web_search_result_shape_is_stable() -> None:
    from hermes_lite.coding.web import web_search

    result = web_search("hermes lite coding agent github", limit=5)
    # Even on failure, the shape is stable
    assert "ok" in result
    if result["ok"]:
        assert "query" in result
        assert "results" in result
        assert "count" in result


def test_web_search_no_duplicate_urls() -> None:
    from hermes_lite.coding.web import web_search

    result = web_search("test", limit=10)
    if result["ok"] and result["results"]:
        urls = [r["url"] for r in result["results"]]
        assert len(urls) == len(set(urls))


# ---------------------------------------------------------------------------
# web_fetch
# ---------------------------------------------------------------------------

def test_web_fetch_returns_content() -> None:
    from hermes_lite.coding.web import web_fetch

    result = web_fetch("https://example.com")
    assert result["ok"] is True
    assert isinstance(result["content"], str)
    assert len(result["content"]) > 0


def test_web_fetch_empty_url() -> None:
    from hermes_lite.coding.web import web_fetch

    result = web_fetch("")
    assert result["ok"] is False
    assert result["error"] == "empty_url"


def test_web_fetch_truncates_long_content() -> None:
    from hermes_lite.coding.web import web_fetch

    result = web_fetch("https://example.com", max_chars=50)
    if result["ok"]:
        assert len(result["content"]) <= 50


def test_web_fetch_invalid_url() -> None:
    from hermes_lite.coding.web import web_fetch

    result = web_fetch("https://invalid.testdomain.nonexistent/tools")
    assert result["ok"] is False


def test_web_fetch_result_shape_stable() -> None:
    from hermes_lite.coding.web import web_fetch

    result = web_fetch("https://example.com", max_chars=200)
    assert "ok" in result
    assert "url" in result
    if result["ok"]:
        assert "content" in result
        assert "truncated" in result
    else:
        assert "error" in result


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def test_strip_tags_removes_html() -> None:
    from hermes_lite.coding.web import _strip_tags

    result = _strip_tags("<p>Hello <b>World</b></p>")
    assert "Hello" in result
    assert "World" in result
    assert "<p>" not in result
    assert "<b>" not in result


def test_strip_tags_removes_script() -> None:
    from hermes_lite.coding.web import _strip_tags

    result = _strip_tags("<script>alert(1)</script><p>content</p>")
    assert "alert" not in result
    assert "content" in result


def test_clean_html_strips_tags_and_entities() -> None:
    from hermes_lite.coding.web import _clean_html

    result = _clean_html("<span>&amp; test</span>")
    assert "&amp;" not in result
    assert "& test" in result
    assert "<span>" not in result


def test_detect_charset_from_content_type() -> None:
    from hermes_lite.coding.web import _detect_charset

    assert _detect_charset("text/html; charset=utf-16", b"") == "utf-16"


def test_detect_charset_from_html_meta() -> None:
    from hermes_lite.coding.web import _detect_charset

    raw = b'<html><meta charset="latin1"></html>'
    assert _detect_charset("text/html", raw) == "latin1"


def test_strip_redirect_extracts_real_url() -> None:
    from hermes_lite.coding.web import _strip_redirect

    href = "https://duckduckgo.com/l/?uddg=http://example.com/test"
    assert _strip_redirect(href) == "http://example.com/test"
