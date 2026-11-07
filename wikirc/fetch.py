"""Fetch a URL and extract its metadata."""

import html as html_module
import urllib.error
from dataclasses import replace
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from .books import (
    archive_identifier,
    looks_like_book_url,
    resolve_archive,
    resolve_isbn,
    valid_isbns,
)
from .http import FETCH_TIMEOUT, MAX_FETCH_BYTES, USER_AGENT, http_get, json_get
from .metadata import doi_from_url, resolve_doi
from .result import FetchResult

SUPPORTED_TYPES = ("text/html", "application/xhtml+xml")
MAX_BODY_TEXT = 4000
MIN_BLOCK_CHARS = 40
TITLE_SEPARATORS = (" | ", " - ", " — ")
NOISY_PHRASES = (
    "just a moment",
    "access denied",
    "attention required",
    "redirecting",
    "page not found",
)
MAX_TITLE = 120
MAX_SUFFIX = 20


class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.canonical = ""
        self.title_parts = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        values = {
            name.lower(): value or "" for name, value in attrs
        }
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = values.get("property") or values.get("name")
            if key and key.lower() not in self.meta:
                self.meta[key.lower()] = values.get("content", "")
        elif tag == "link":
            rel = values.get("rel", "").lower().split()
            if "canonical" in rel and not self.canonical:
                self.canonical = values.get("href", "")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)


def extract(html: str, base_url: str) -> dict:
    parser = _MetaParser()
    parser.feed(html)
    parser.close()

    def meta(key: str) -> str:
        return html_module.unescape(parser.meta.get(key, "")).strip()

    title = (
        meta("og:title")
        or meta("twitter:title")
        or html_module.unescape("".join(parser.title_parts)).strip()
    )
    description = meta("og:description") or meta("description")
    canonical = parser.canonical
    if canonical:
        canonical = urljoin(base_url, canonical)

    return {
        "title": title,
        "description": description,
        "canonical": canonical,
    }


class _TextParser(HTMLParser):
    """Collect visible text as blocks, dropping chrome and markup."""

    SKIP = ("script", "style", "head", "noscript", "nav", "header", "footer", "aside")
    SKIP_ROLES = ("navigation", "banner", "contentinfo")
    # Only true text blocks end a run. Container elements (div, section, main)
    # wrap paragraphs and must not split them, or every nested div produces a
    # fragment too short to survive the chrome filter.
    BLOCK = ("p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br",
             "blockquote", "pre", "td", "tr", "dt", "dd")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.buffer: list[str] = []
        self.stack: list[tuple[str, bool]] = []

    def _flush(self) -> None:
        text = " ".join(" ".join(self.buffer).split())
        if text:
            self.blocks.append(text)
        self.buffer = []

    def _skipping(self) -> bool:
        return any(skip for _, skip in self.stack)

    def handle_starttag(self, tag, attrs):
        role = next((value for name, value in attrs if name == "role"), None)
        self.stack.append((tag, tag in self.SKIP or role in self.SKIP_ROLES))
        if tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        # Pop back to the matching tag; malformed markup means it may be absent.
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if not self._skipping() and data.strip():
            self.buffer.append(data)


def extract_text(html: str, limit: int = MAX_BODY_TEXT) -> str:
    """Visible page text, bounded: the content a title alone does not carry.

    Browsing chrome arrives as many short blocks — menu items, link lists — while
    prose arrives as long ones. Keeping only substantial blocks drops the menu
    without needing to know the site.
    """
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    parser._flush()
    substantive = [block for block in parser.blocks if len(block) >= MIN_BLOCK_CHARS]
    return " ".join(substantive or parser.blocks)[:limit]


def clean_title(title: str, url: str) -> str:
    title = title.strip()
    host = (urlsplit(url).hostname or "").lower()

    for separator in TITLE_SEPARATORS:
        index = title.rfind(separator)
        if index == -1:
            continue
        suffix = title[index + len(separator):].strip()
        if not suffix or len(suffix) > MAX_SUFFIX:
            continue
        words = _words(suffix)
        if words and all(word in host for word in words):
            return title[:index].strip()

    return title


def title_is_noisy(title: str, url: str) -> bool:
    if not title or len(title) > MAX_TITLE:
        return True
    lowered = title.lower()
    return any(phrase in lowered for phrase in NOISY_PHRASES)


def fetch(
    url: str,
    *,
    timeout: int = FETCH_TIMEOUT,
    getter=http_get,
    json_getter=None,
) -> FetchResult:
    doi = doi_from_url(url)
    if doi is not None:
        reader = json_get if json_getter is None else json_getter
        result = resolve_doi(doi, timeout=timeout, json_getter=reader)
        if not result.ok and not result.title:
            return replace(result, title=_doi_slug_title(doi))
        return result

    identifier = archive_identifier(url)
    if identifier is not None:
        reader = json_get if json_getter is None else json_getter
        return resolve_archive(identifier, timeout=timeout, json_getter=reader)

    try:
        final_url, content_type, body = getter(url, timeout, MAX_FETCH_BYTES)
    except TimeoutError:
        return FetchResult.failed(url, "timed out")
    except urllib.error.HTTPError as error:
        return FetchResult.failed(url, f"HTTP {error.code}")
    except urllib.error.URLError:
        return FetchResult.failed(url, "cannot reach host")
    except Exception:
        return FetchResult.failed(url, "fetch error")

    media_type = content_type.split(";")[0].strip().lower()
    if media_type not in SUPPORTED_TYPES:
        return FetchResult.failed(url, "unsupported content type")

    page_html = body.decode("utf-8", errors="replace")
    parsed = extract(page_html, final_url)
    title = clean_title(parsed["title"], final_url)
    description = parsed["description"]

    result = FetchResult(
        ok=True,
        final_url=final_url,
        title=title,
        description=description,
        source="html",
        creator="",
        date="",
        isbn="",
        canonical=parsed["canonical"],
        title_noisy=title_is_noisy(title, final_url),
        error="",
        text=extract_text(page_html),
    )

    if result.title_noisy or looks_like_book_url(url):
        haystack = " ".join(
            (url, final_url, title, description, page_html[:4000])
        )
        candidates = valid_isbns(haystack)
        if candidates:
            reader = json_get if json_getter is None else json_getter
            resolved = resolve_isbn(
                candidates[0], timeout=timeout, json_getter=reader
            )
            if resolved.ok:
                return replace(
                    result,
                    title=resolved.title,
                    description=resolved.description,
                    source="openlibrary",
                    creator=resolved.creator,
                    date=resolved.date,
                    isbn=resolved.isbn,
                    canonical=resolved.canonical,
                    title_noisy=False,
                )

    return result


def _words(text: str) -> list[str]:
    cleaned = "".join(
        char if char.isalnum() else " " for char in text.lower()
    )
    return cleaned.split()


def _doi_slug_title(doi: str) -> str:
    suffix = doi.rsplit("/", 1)[-1]
    cleaned = "".join(
        char if char.isalnum() else " " for char in unquote(suffix)
    )
    return " ".join(cleaned.split())
