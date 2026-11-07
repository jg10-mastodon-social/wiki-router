"""Resolve DOI metadata through Crossref.

Publisher pages answer a DOI with a challenge or a 403 more often than not. The
DOI itself is enough: Crossref serves the record as JSON, and that record
carries the title, first author and year the router wants.
"""

import html
import re
from typing import TYPE_CHECKING
from urllib.parse import unquote

if TYPE_CHECKING:
    from .fetch import FetchResult

DOI_URL = re.compile(
    r"^https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s?#]+)", re.IGNORECASE
)
TAG = re.compile(r"<[^>]+>")


def doi_from_url(url: str) -> str | None:
    """Return the DOI a resolver URL points at, or ``None``."""
    match = DOI_URL.match(unquote(url).strip())
    return match.group(1) if match else None


def strip_markup(value: str) -> str:
    """Drop HTML/JATS tags, unescape entities and collapse whitespace."""
    without_tags = TAG.sub(" ", value)
    return " ".join(html.unescape(without_tags).split())


def compose_title(title: str, subtitle: str = "") -> str:
    """Join a title and subtitle unless the subtitle adds nothing."""
    title = title.strip()
    subtitle = subtitle.strip()
    if not subtitle:
        return title
    if subtitle.casefold() in title.casefold():
        return title
    if not title:
        return subtitle
    return f"{title}: {subtitle}"


def resolve_doi(doi: str, *, timeout: int, json_getter) -> "FetchResult":
    """Build a ``FetchResult`` from the Crossref record for ``doi``."""
    from .fetch import MAX_FETCH_BYTES, FetchResult

    doi_url = f"https://doi.org/{doi}"
    api_url = f"https://api.crossref.org/works/{doi}"

    try:
        payload = json_getter(api_url, timeout, MAX_FETCH_BYTES)
    except LookupError:
        return FetchResult.failed(doi_url, "no crossref record")
    except Exception:
        return FetchResult.failed(doi_url, "crossref error")

    if not isinstance(payload, dict):
        return FetchResult.failed(doi_url, "no crossref record")

    message = payload.get("message")
    if not isinstance(message, dict):
        return FetchResult.failed(doi_url, "no crossref record")

    title = compose_title(
        strip_markup(_first(message.get("title"))),
        strip_markup(_first(message.get("subtitle"))),
    )

    return FetchResult(
        ok=True,
        final_url=doi_url,
        title=title,
        description=strip_markup(_first(message.get("container-title"))),
        source="crossref",
        creator=_creator(message.get("author")),
        date=_year(message),
        isbn="",
        canonical=doi_url,
        title_noisy=False,
        error="",
    )


def _first(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)) and value:
        first = value[0]
        return first if isinstance(first, str) else ""
    return ""


def _creator(authors) -> str:
    if not isinstance(authors, (list, tuple)) or not authors:
        return ""
    first = authors[0]
    if not isinstance(first, dict):
        return ""

    name = strip_markup(str(first.get("name", "")))
    if name:
        return name

    given = strip_markup(str(first.get("given", "")))
    family = strip_markup(str(first.get("family", "")))
    return " ".join(part for part in (given, family) if part)


def _year(message: dict) -> str:
    for key in ("published-print", "published-online", "issued"):
        part = message.get(key)
        if not isinstance(part, dict):
            continue
        date_parts = part.get("date-parts")
        if not isinstance(date_parts, (list, tuple)) or not date_parts:
            continue
        first = date_parts[0]
        if not isinstance(first, (list, tuple)) or not first:
            continue
        year = first[0]
        if year not in (None, ""):
            return str(year)
    return ""
