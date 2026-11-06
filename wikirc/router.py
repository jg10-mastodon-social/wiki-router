"""Assemble the routing payload consumed by the webhook."""

from collections.abc import Sequence
from urllib.parse import unquote, urlsplit

from . import CONTRACT
from .score import Candidate, Document, Query, rank
from .text import tokenize


def fetched_block(
    url: str,
    *,
    title: str = "",
    description: str = "",
    fetched: bool = False,
    error: str = "",
) -> dict:
    return {
        "ok": fetched,
        "title": title or _title_from_url(url),
        "description": description,
        "source": "",
        "creator": "",
        "date": "",
        "isbn": "",
        "canonical": "",
        "title_noisy": False,
        "error": error,
    }


def route_payload(
    documents: Sequence[Document],
    url: str,
    *,
    title: str = "",
    description: str = "",
    context: str = "",
    top: int = 5,
    wiki: str = "",
    exclude_wiki: str = "",
    fetch_ok: bool = False,
    fetch_error: str = "",
) -> dict:
    selected = [
        document
        for document in documents
        if (not wiki or document.wiki == wiki)
        and (not exclude_wiki or document.wiki != exclude_wiki)
    ]
    fetched = fetched_block(
        url,
        title=title,
        description=description,
        fetched=fetch_ok,
        error=fetch_error,
    )
    candidates = rank(
        selected,
        Query(
            url=url,
            title=title,
            description=description,
            context=context,
        ),
        top=len(selected),
    )
    candidates = [
        candidate for candidate in candidates if candidate.score > 0
    ][: max(top, 0)]

    return {
        "contract": CONTRACT,
        "url": url,
        "final_url": url,
        "fetched": fetched,
        "reliability": _reliability(fetched),
        "candidates": [_candidate(candidate) for candidate in candidates],
    }


def _reliability(fetched: dict) -> str:
    if fetched["ok"] and tokenize(fetched["title"], bigrams=False):
        return "ok"
    return "low"


def _candidate(candidate: Candidate) -> dict:
    return {
        "id": candidate.id,
        "wiki": candidate.wiki,
        "label": candidate.label,
        "subject": candidate.subject,
        "score": candidate.score,
        "cosine": candidate.cosine,
        "boosts": dict(candidate.boosts),
        "matched": list(candidate.matched),
        "already_linked": candidate.already_linked,
        "heading_match": candidate.heading_match,
        "suggested_section": candidate.suggested_section,
        "headings": list(candidate.headings),
        "summary": candidate.summary,
    }


def _title_from_url(url: str) -> str:
    parts = urlsplit(url)
    segments = [
        segment for segment in unquote(parts.path).split("/") if segment
    ]
    source = segments[-1] if segments else (parts.hostname or "")
    text = "".join(char if char.isalnum() else " " for char in source)
    return " ".join(text.split())
