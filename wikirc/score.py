"""Rank in-memory wiki documents for a URL."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit

from .text import tokenize


@dataclass(frozen=True)
class Document:
    id: str
    wiki: str
    label: str
    subject: str | None
    terms: Mapping[str, int]
    headings: tuple[str, ...]
    links: tuple[str, ...]
    text: str
    summary: str = ""


@dataclass(frozen=True)
class Query:
    url: str
    title: str = ""
    description: str = ""
    context: str = ""


@dataclass(frozen=True)
class Candidate:
    id: str
    wiki: str
    label: str
    subject: str | None
    score: float
    cosine: float
    boosts: dict[str, float]
    matched: tuple[str, ...]
    already_linked: bool
    heading_match: bool
    suggested_section: str | None


def rank(
    documents: Sequence[Document], query: Query, top: int = 5
) -> list[Candidate]:
    if top <= 0:
        return []

    query_terms = _query_terms(query)
    if not query_terms:
        return []

    idf = _idf(documents)
    query_weights = {
        term: count * idf(term) for term, count in query_terms.items()
    }
    query_norm = math.sqrt(sum(weight * weight for weight in query_weights.values()))
    query_set = set(query_terms)

    candidates = []
    for document in documents:
        cosine = _cosine(document, query_weights, query_norm, idf)
        boosts, heading_match, suggested = _boosts(document, query, query_set)
        score = round(cosine + sum(boosts.values()), 4)
        candidates.append(
            Candidate(
                id=document.id,
                wiki=document.wiki,
                label=document.label,
                subject=document.subject,
                score=score,
                cosine=round(cosine, 4),
                boosts=boosts,
                matched=tuple(sorted(query_set & document.terms.keys())[:8]),
                already_linked=_already_linked(document, query.url),
                heading_match=heading_match,
                suggested_section=suggested,
            )
        )

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.id))
    return candidates[:top]


def normalise_url(url: str) -> str:
    parts = urlsplit(url)
    netloc = parts.netloc
    if parts.hostname:
        userinfo = ""
        if parts.username is not None:
            userinfo = parts.username
            if parts.password is not None:
                userinfo += ":" + parts.password
            userinfo += "@"
        port = f":{parts.port}" if parts.port is not None else ""
        netloc = f"{userinfo}{parts.hostname.lower()}{port}"

    path = parts.path
    if path not in ("", "/") and path.endswith("/"):
        path = path[:-1]

    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


def host_of(url: str) -> str:
    host = urlsplit(url).hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host


def same_site(left: str, right: str) -> bool:
    return host_of(left) == host_of(right)


def _slug_text(url: str) -> str:
    path = unquote(urlsplit(url).path)
    return "".join(char if char.isalnum() else " " for char in path)


def _query_terms(query: Query) -> dict[str, int]:
    text = " ".join(
        [_slug_text(query.url), query.title, query.description, query.context]
    )
    return tokenize(text)


def _idf(documents: Sequence[Document]):
    total = len(documents)
    counts: dict[str, int] = {}

    def idf(term: str) -> float:
        if term not in counts:
            document_frequency = sum(
                1 for document in documents if term in document.terms
            )
            counts[term] = math.log((total + 1) / (document_frequency + 1)) + 1
        return counts[term]

    return idf


def _cosine(
    document: Document,
    query_weights: Mapping[str, float],
    query_norm: float,
    idf,
) -> float:
    weights = {
        term: (1 + math.log(count)) * idf(term)
        for term, count in document.terms.items()
        if count > 0
    }
    document_norm = math.sqrt(sum(weight * weight for weight in weights.values()))
    if query_norm == 0 or document_norm == 0:
        return 0.0

    dot = sum(
        weight * weights[term]
        for term, weight in query_weights.items()
        if term in weights
    )
    return dot / (query_norm * document_norm)


def _label_tokens(label: str) -> set[str]:
    return set(tokenize(label, bigrams=False))


def _label_boost(label: str, query: Query, query_set: set[str]) -> dict[str, float]:
    label_tokens = _label_tokens(label)
    if label_tokens:
        normalised = _collapse(label)
        if normalised == _collapse(query.title) or normalised == _collapse(
            _slug_text(query.url)
        ):
            return {"label_exact": 0.5}
        shared = label_tokens & query_set
        if len(shared) / len(label_tokens) >= 0.6:
            return {"label_most": 0.15}
        if shared:
            return {"label_contains": 0.05}
    return {}


def _collapse(value: str) -> str:
    return " ".join(value.casefold().split())


def _boosts(
    document: Document, query: Query, query_set: set[str]
) -> tuple[dict[str, float], bool, str | None]:
    boosts = _label_boost(document.label, query, query_set)

    if _shares_other_site(document.links, query.url):
        boosts["same_domain"] = 0.1

    heading_match = False
    best_overlap = 0
    suggested = None
    for heading in document.headings:
        overlap = len(_label_tokens(heading) & query_set)
        if overlap > 0:
            heading_match = True
        if overlap > best_overlap:
            best_overlap = overlap
            suggested = heading

    if heading_match:
        boosts["heading_match"] = 0.05

    return boosts, heading_match, suggested


def _shares_other_site(links: Sequence[str], url: str) -> bool:
    normalised = normalise_url(url)
    return any(
        same_site(link, url) and normalise_url(link) != normalised
        for link in links
    )


def _already_linked(document: Document, url: str) -> bool:
    normalised = normalise_url(url)
    return any(normalise_url(link) == normalised for link in document.links)
