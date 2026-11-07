"""Rank in-memory wiki documents for a URL."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
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
    norm: float = 0.0
    sites: tuple[str, ...] = ()
    link_keys: tuple[str, ...] = ()


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
    headings: tuple[str, ...]
    summary: str
    tiebreak: bool = False


DEFAULT_WITHIN = 0.05


def order_candidates(
    candidates: Sequence[Candidate],
    last: Sequence[str] = (),
    within: float = DEFAULT_WITHIN,
) -> list[Candidate]:
    """Prefer another wiki when it is within `within` of a demoted wiki's lead."""
    demoted = set(last)
    ordered = sorted(candidates, key=lambda row: (-row.score, row.id))
    if not demoted or len(ordered) < 2:
        return ordered

    top = ordered[0]
    if top.wiki not in demoted:
        return ordered

    best_other = next((row for row in ordered if row.wiki not in demoted), None)
    if best_other is None or top.score - best_other.score > within:
        return ordered

    result = [best_other]
    for row in ordered:
        if row is best_other:
            continue
        result.append(replace(row, tiebreak=True) if row is top else row)
    return result


def rank(
    documents: Sequence[Document],
    query: Query,
    top: int = 5,
    last: Sequence[str] = (),
    within: float = DEFAULT_WITHIN,
) -> list[Candidate]:
    if top <= 0:
        return []

    query_terms = _query_terms(query)
    if not query_terms:
        return []

    idf = idf_of(documents)
    query_weights = {
        term: count * idf(term) for term, count in query_terms.items()
    }
    query_norm = math.sqrt(sum(weight * weight for weight in query_weights.values()))
    query_set = set(query_terms)
    normalised_url = normalise_url(query.url)
    host = host_of(query.url)

    candidates = []
    for document in documents:
        cosine = _cosine(document, query_weights, query_norm, idf)
        boosts, heading_match, suggested = _boosts(
            document, query, query_set, host, normalised_url
        )
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
                already_linked=_already_linked(document, normalised_url),
                heading_match=heading_match,
                suggested_section=suggested,
                headings=document.headings,
                summary=document.summary,
            )
        )

    return order_candidates(candidates, last, within)[:top]


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


def document_frequencies(documents: Sequence[Document]) -> dict[str, int]:
    frequencies: dict[str, int] = {}
    for document in documents:
        for term in document.terms:
            frequencies[term] = frequencies.get(term, 0) + 1
    return frequencies


def idf_of(documents: Sequence[Document]):
    total = len(documents)
    frequencies = document_frequencies(documents)

    def idf(term: str) -> float:
        document_frequency = frequencies.get(term, 0)
        return math.log((total + 1) / (document_frequency + 1)) + 1

    return idf


def document_norm(terms: Mapping[str, int], idf) -> float:
    """The tf-idf length of one document, as ``rank`` measures it."""

    total = 0.0
    for term, count in terms.items():
        if count > 0:
            weight = (1 + math.log(count)) * idf(term)
            total += weight * weight
    return math.sqrt(total)


def _cosine(
    document: Document,
    query_weights: Mapping[str, float],
    query_norm: float,
    idf,
) -> float:
    if query_norm == 0:
        return 0.0

    norm = document.norm
    if norm == 0:
        norm = document_norm(document.terms, idf)
    if norm == 0:
        return 0.0

    dot = 0.0
    for term, weight in query_weights.items():
        count = document.terms.get(term, 0)
        if count > 0:
            dot += weight * ((1 + math.log(count)) * idf(term))
    return dot / (query_norm * norm)


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
    document: Document,
    query: Query,
    query_set: set[str],
    host: str,
    normalised_url: str,
) -> tuple[dict[str, float], bool, str | None]:
    boosts = _label_boost(document.label, query, query_set)

    if _shares_other_site(document, host, normalised_url):
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


def _sites_of(links: Sequence[str]) -> set[str]:
    return {host_of(link) for link in links}


def _keys_of(links: Sequence[str]) -> set[str]:
    return {normalise_url(link) for link in links}


def _shares_other_site(
    document: Document, host: str, normalised_url: str
) -> bool:
    sites = document.sites or _sites_of(document.links)
    if host not in sites:
        return False

    keys = document.link_keys or _keys_of(document.links)
    return any(
        key != normalised_url and host_of(key) == host for key in keys
    )


def _already_linked(document: Document, normalised_url: str) -> bool:
    keys = document.link_keys or _keys_of(document.links)
    return normalised_url in keys
