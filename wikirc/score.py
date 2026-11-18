"""Rank in-memory wiki documents for a URL."""

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit, urlunsplit

from .text import tokenize

# Path segments that describe a site's structure rather than its subject.
_GENERIC_SEGMENTS = frozenset(
    {"wiki", "wikimedia", "index", "home", "default", "view", "watch", "en", "details"}
)
_EXTENSION = re.compile(r"\.(html?|php|aspx?|md|txt)$", re.IGNORECASE)
_INDEX_PAGE = re.compile(r"(?:^|/)index\.html?$", re.IGNORECASE)
_SEPARATOR = re.compile(r"[^0-9A-Za-z]+")
_YEAR = re.compile(r"^(19|20)\d\d$")

# A page that already points at the URL is the strongest evidence that this is
# where the link belongs: filing it again elsewhere would duplicate it.
ALREADY_LINKED_BOOST = 0.4

# Hosts that nearly every page links to, so one of these among a page's links
# says nothing about the page's subject. Matched by hostname suffix.
REFERENCE_HOSTS = (
    "wikipedia.org",
    "wikimedia.org",
    "wikidata.org",
    "doi.org",
    "archive.org",
    "openlibrary.org",
    "youtube.com",
    "youtu.be",
)


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
    headings: str = ""
    context: str = ""
    body: str = ""


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
    redirected: bool = False
    redirected_from: str | None = None


def rank(
    documents: Sequence[Document],
    query: Query,
    top: int = 5,
    respect_existing_links: bool = True,
) -> list[Candidate]:
    if top <= 0:
        return []

    query_terms = query_term_weights(query)
    if not query_terms:
        return []

    idf = idf_of(documents)
    query_weights = {
        term: weight * idf(term) for term, weight in query_terms.items()
    }
    query_norm = math.sqrt(sum(weight * weight for weight in query_weights.values()))
    query_set = set(query_terms)
    normalised_url = normalise_url(query.url)
    host = host_of(query.url)

    candidates = []
    for document in documents:
        cosine = _cosine(document, query_weights, query_norm, idf)
        already_linked = _already_linked(document, normalised_url)
        boosts, heading_match, suggested = _boosts(
            document, query, query_set, host, normalised_url
        )
        if already_linked and respect_existing_links:
            boosts["already_linked"] = ALREADY_LINKED_BOOST
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
                already_linked=already_linked,
                heading_match=heading_match,
                suggested_section=suggested,
                headings=document.headings,
                summary=document.summary,
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


def link_key(url: str) -> str:
    """The identity of a URL for "this page already carries that link".

    Built on :func:`normalise_url`, then drops what does not change which
    document a link points at: the scheme (a page that wrote ``http`` still
    links the same article as one that wrote ``https``), a trailing
    ``index.html``, and the difference between a bare host and its root path.
    """
    parts = urlsplit(normalise_url(url))
    path = _INDEX_PAGE.sub("", parts.path)
    if path.endswith("/"):
        path = path[:-1]
    return urlunsplit(("", parts.netloc, path, parts.query, ""))


def host_of(url: str) -> str:
    host = urlsplit(url).hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host


def same_site(left: str, right: str) -> bool:
    return host_of(left) == host_of(right)


def slug_text(url: str) -> str:
    """Words from a URL path, without site structure or bare identifiers.

    A Wikipedia URL says "wiki" because it is a wiki, not because the article is
    about one; a homepage says "index" for the same reason. Neither is evidence,
    and both outrank real subject words when they appear in a page's label.
    """
    path = unquote(urlsplit(url).path)
    words: list[str] = []

    for segment in path.split("/"):
        segment = _EXTENSION.sub("", segment)
        if not segment or segment.casefold() in _GENERIC_SEGMENTS:
            continue
        for word in _SEPARATOR.split(segment):
            if not word:
                continue
            if word.isdigit() and not _YEAR.match(word):
                continue
            words.append(word.casefold())

    return " ".join(words)


# What the caller knows about a link is not equally informative, so the query
# vector weights each field. A title names the subject; a slug is the same claim
# in URL form; a description or the caller's own context says why the link is
# being filed; a heading says what the fetched page is organised around; page
# content only says what it covers. A token found in several fields sums their
# weights: a term named by both title and slug therefore outweighs one named
# once by the title alone.
QUERY_FIELD_WEIGHTS: dict[str, float] = {
    "title": 4.0,
    "slug": 2.5,
    "description": 2.5,
    "headings": 2.0,
    "context": 1.5,
    "body": 0.7,
}


def _term_frequency(count: float) -> float:
    """Sublinear term frequency, shared by the query and document vectors.

    Repeating a term is more evidence than writing it once, but never twice the
    evidence: without the log, an echoed phrase in a long description or body
    outweighs a precise title. Both sides of the cosine use this transform, so
    the two vectors stay comparable.
    """
    return 1 + math.log(count)


def query_term_weights(query: Query) -> dict[str, float]:
    """The query vector's term weights, before idf.

    Each field is tokenised on its own so its tokens carry that field's weight
    (:data:`QUERY_FIELD_WEIGHTS`); a term's contribution from every field is
    summed, and its repetition inside a field is made sublinear before the
    weight is applied. A token appearing once in two fields therefore carries
    the sum of those two field weights.
    """
    fields = (
        ("slug", slug_text(query.url)),
        ("title", query.title),
        ("description", query.description),
        ("headings", query.headings),
        ("context", query.context),
        ("body", query.body),
    )

    weights: dict[str, float] = {}
    for name, text in fields:
        if not text:
            continue
        field_weight = QUERY_FIELD_WEIGHTS[name]
        for term, count in tokenize(text).items():
            weights[term] = (
                weights.get(term, 0.0) + field_weight * _term_frequency(count)
            )
    return weights


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
            weight = _term_frequency(count) * idf(term)
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
            dot += weight * (_term_frequency(count) * idf(term))
    return dot / (query_norm * norm)


def _label_tokens(label: str) -> set[str]:
    return set(tokenize(label, bigrams=False))


def _label_boost(label: str, query: Query) -> dict[str, float]:
    """Label evidence, taken from the URL's own identity only.

    A title or slug says what the link is; a description or the caller's
    context says why it is being filed. A label that happens to sit inside a
    sentence about the link is not evidence that the page is about it.
    """
    label_tokens = _label_tokens(label)
    if not label_tokens:
        return {}

    identities = (
        _label_tokens(query.title),
        set(tokenize(slug_text(query.url), bigrams=False)),
    )
    if any(label_tokens == identity for identity in identities):
        return {"label_exact": 0.5}
    if any(label_tokens <= identity for identity in identities):
        return {"label_most": 0.15}
    if any(label_tokens & identity for identity in identities):
        return {"label_contains": 0.05}
    return {}


def _boosts(
    document: Document,
    query: Query,
    query_set: set[str],
    host: str,
    normalised_url: str,
) -> tuple[dict[str, float], bool, str | None]:
    boosts = _label_boost(document.label, query)

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


def _is_reference_host(host: str) -> bool:
    return any(
        host == name or host.endswith("." + name) for name in REFERENCE_HOSTS
    )


def _keys_of(links: Sequence[str]) -> set[str]:
    return {normalise_url(link) for link in links}


def _shares_other_site(
    document: Document, host: str, normalised_url: str
) -> bool:
    if _is_reference_host(host):
        return False

    sites = document.sites or _sites_of(document.links)
    if host not in sites:
        return False

    keys = document.link_keys or _keys_of(document.links)
    return any(
        key != normalised_url and host_of(key) == host for key in keys
    )


def _already_linked(document: Document, normalised_url: str) -> bool:
    keys = document.link_keys or _keys_of(document.links)
    target = link_key(normalised_url)
    return any(link_key(key) == target for key in keys)
