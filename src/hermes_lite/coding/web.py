"""Web search and content fetch — zero external dependencies.

Uses DuckDuckGo Lite for search (no API key) and urllib for fetches.
"""

from __future__ import annotations

import html as _html
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_UA = "HermesLite/1.0"

# ---------------------------------------------------------------------------
# web_search
# ---------------------------------------------------------------------------


def web_search(query: str, limit: int = 10) -> dict[str, object]:
    """Search the web via DuckDuckGo Lite.  No API key required.

    Returns a structured result with ``results``, each containing
    ``title``, ``url``, and ``snippet``.
    """
    if not query.strip():
        return {"ok": False, "error": "empty_query"}

    encoded = urllib.parse.quote(query.strip())
    url = f"https://lite.duckduckgo.com/lite/?q={encoded}"

    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "error": "search_request_failed", "detail": str(exc)}

    results: list[dict[str, str]] = []
    # Lite pages have result links with <a> inside table rows
    rows = re.findall(
        r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?<td[^>]*>(.*?)</td>',
        raw, re.DOTALL | re.IGNORECASE,
    )

    if not rows:
        # Try simpler pattern
        rows = re.findall(
            r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            raw, re.DOTALL | re.IGNORECASE,
        )
        for href, title in rows[:limit]:
            href_parsed = urllib.parse.urljoin(url, _strip_redirect(href))
            results.append({
                "title": _clean_html(title).strip() or "Untitled",
                "url": href_parsed,
                "snippet": "",
            })
    else:
        for href, title, snippet in rows[:limit]:
            href_parsed = urllib.parse.urljoin(url, _strip_redirect(href))
            results.append({
                "title": _clean_html(title).strip() or "Untitled",
                "url": href_parsed,
                "snippet": _clean_html(snippet).strip(),
            })

    return {"ok": True, "query": query, "results": results, "count": len(results)}


# ---------------------------------------------------------------------------
# web_fetch
# ---------------------------------------------------------------------------


def web_fetch(url: str, max_chars: int = 8000) -> dict[str, object]:
    """Fetch a URL and return its text content.

    HTML tags are stripped.  Output is truncated to *max_chars*.
    """
    if not url.strip():
        return {"ok": False, "error": "empty_url"}

    req = urllib.request.Request(url.strip(), headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            content_type = resp.headers.get("Content-Type", "text/html")
            raw = resp.read()
            # Try to detect encoding
            charset = _detect_charset(content_type, raw)
            text = raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"http_{exc.code}", "url": url}
    except urllib.error.URLError as exc:
        return {"ok": False, "error": "fetch_failed", "detail": str(exc.reason), "url": url}
    except Exception as exc:
        return {"ok": False, "error": "fetch_failed", "detail": str(exc), "url": url}

    # If HTML, strip tags
    if "html" in content_type.lower():
        text = _strip_tags(text)

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    return {
        "ok": True,
        "url": url,
        "content": text.strip(),
        "content_length": len(text.strip()),
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _strip_redirect(href: str) -> str:
    """DuckDuckGo wraps external links in redirect."""
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in parsed.netloc:
        qs = urllib.parse.parse_qs(parsed.query)
        real = qs.get("uddg", qs.get("url", []))
        if real:
            return real[0]
    return href


def _clean_html(raw: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", " ", raw)).strip()


def _strip_tags(html_text: str) -> str:
    """Remove HTML tags and decode entities, keeping whitespace structure."""
    # Remove scripts and styles
    text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
    # Replace block elements with newlines
    text = re.sub(r"</?(p|div|br|h[1-6]|li|tr|article|section)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Unescape HTML entities
    text = _html.unescape(text)
    # Collapse whitespace
    text = re.sub(r"\n\s*\n", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _detect_charset(content_type: str, raw: bytes) -> str:
    """Extract charset from Content-Type header or HTML meta."""
    match = re.search(r"charset=([^\s;]+)", content_type, re.IGNORECASE)
    if match:
        return match.group(1)
    # Try from HTML meta
    head = raw[:1024].decode("ascii", errors="ignore")
    match = re.search(r'charset=["\']?([^"\';>\s]+)', head, re.IGNORECASE)
    if match:
        return match.group(1)
    return "utf-8"
