"""Resolve book metadata for archive.org details pages.

An archive.org item page answers with page chrome in the title rather than the
catalog title. The item metadata is enough to route: title, creator and date
come from the item record. A valid ISBN lets Open Library supply a cleaner
record, and its ISBN page is then the canonical URL.
"""

import re

from .http import MAX_FETCH_BYTES
from .metadata import compose_title
from .result import FetchResult

ARCHIVE_DETAILS = re.compile(
    r"^https?://(?:www\.)?archive\.org/details/([^/?#]+)"
)
CHROME = (
    " : free download, borrow, and streaming",
    " : internet archive",
)
AUTHOR_TAIL = re.compile(r",\s*[^,]+,\s*[^,]+,\s*\d{4}\s*-?\s*$")


def archive_identifier(url: str) -> str | None:
    """Return the item identifier an archive.org details URL points at."""
    match = ARCHIVE_DETAILS.match(url.strip())
    return match.group(1) if match else None


def clean_archive_title(title: str) -> str:
    """Strip page chrome, an author/date tail and trailing punctuation."""
    text = title
    while True:
        lowered = text.casefold()
        for suffix in CHROME:
            if lowered.endswith(suffix):
                text = text[: -len(suffix)]
                break
        else:
            break

    text = AUTHOR_TAIL.sub("", text)
    text = " ".join(text.split())
    return text.rstrip(":,").rstrip()


def isbn_candidates(metadata: dict) -> list[str]:
    """Return the valid ISBNs carried by an archive metadata record."""
    found = []
    for part in _isbn_parts(metadata.get("isbn")):
        candidate = part.replace("-", "").strip().upper()
        if len(candidate) == 10 and _valid_isbn10(candidate):
            found.append(candidate)
        elif len(candidate) == 13 and _valid_isbn13(candidate):
            found.append(candidate)
    return found


def resolve_archive(
    identifier: str, *, timeout: int, json_getter
) -> "FetchResult":
    """Build a ``FetchResult`` from the archive.org item record."""
    url = f"https://archive.org/details/{identifier}"

    try:
        payload = json_getter(
            f"https://archive.org/metadata/{identifier}",
            timeout,
            MAX_FETCH_BYTES,
        )
    except LookupError:
        return FetchResult.failed(url, "no archive record")
    except Exception:
        return FetchResult.failed(url, "archive error")

    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    if not isinstance(metadata, dict):
        return FetchResult.failed(url, "no archive record")

    title = clean_archive_title(_text(metadata.get("title")))
    creator = _text(metadata.get("creator"))
    date = _text(metadata.get("date"))
    candidates = isbn_candidates(metadata)
    isbn = candidates[0] if candidates else ""
    source = "archive.org"
    canonical = ""

    if isbn:
        record = _openlibrary_record(isbn, timeout, json_getter)
        entry = (
            record.get(f"ISBN:{isbn}") if isinstance(record, dict) else None
        )
        if isinstance(entry, dict):
            openlibrary_title = compose_title(
                _text(entry.get("title")), _text(entry.get("subtitle"))
            )
            if openlibrary_title:
                title = openlibrary_title
            authors = _authors(entry.get("authors"))
            if authors:
                creator = authors
            publish_date = _text(entry.get("publish_date"))
            if publish_date:
                date = publish_date
            source = "openlibrary"
            canonical = f"https://openlibrary.org/isbn/{isbn}"

    return FetchResult(
        ok=True,
        final_url=url,
        title=title,
        description="",
        source=source,
        creator=creator,
        date=date,
        isbn=isbn,
        canonical=canonical,
        title_noisy=False,
        error="",
    )


def _isbn_parts(value) -> list[str]:
    if isinstance(value, str):
        return re.split(r"[,\s]+", value)
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.extend(re.split(r"[,\s]+", item))
        return parts
    return []


def _valid_isbn10(candidate: str) -> bool:
    if not candidate[:9].isdigit():
        return False
    last = candidate[9]
    if not (last.isdigit() or last == "X"):
        return False
    total = sum(
        (10 - index) * (10 if char == "X" else int(char))
        for index, char in enumerate(candidate)
    )
    return total % 11 == 0


def _valid_isbn13(candidate: str) -> bool:
    if not candidate.isdigit():
        return False
    total = sum(
        (1 if index % 2 == 0 else 3) * int(char)
        for index, char in enumerate(candidate)
    )
    return total % 10 == 0


def _text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "; ".join(
            part.strip()
            for part in value
            if isinstance(part, str) and part.strip()
        )
    return ""


def _authors(value) -> str:
    if not isinstance(value, (list, tuple)):
        return ""
    names = []
    for author in value:
        if isinstance(author, dict):
            name = _text(author.get("name"))
            if name:
                names.append(name)
    return "; ".join(names)


def _openlibrary_record(isbn: str, timeout: int, json_getter):
    url = (
        "https://openlibrary.org/api/books"
        f"?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
    )
    try:
        return json_getter(url, timeout, MAX_FETCH_BYTES)
    except Exception:
        return None
