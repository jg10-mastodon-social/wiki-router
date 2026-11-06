"""Persist a routing index for the wiki tree."""

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .corpus import Page, discover_wikis
from .score import Document
from .text import tokenize

INDEX_VERSION = 1
INDEX_NAME = "index.json"
SUMMARY_LIMIT = 160

_HEADING = re.compile(r"^#{1,6}(?:\s|$)")


@dataclass(frozen=True)
class IndexPayload:
    version: int
    generated: str
    notes: str
    fingerprint: str
    pages: int
    documents: tuple[Document, ...]


def summary_of(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line and not _HEADING.match(line):
            return line[:SUMMARY_LIMIT]
    return ""


def document_from_page(page: Page) -> Document:
    return Document(
        id=page.id,
        wiki=page.wiki,
        label=page.label,
        subject=page.subject,
        terms=tokenize(" ".join([page.label, *page.headings, page.text])),
        headings=page.headings,
        links=page.links,
        text=page.text,
        summary=summary_of(page.text),
    )


def fingerprint(notes: Path, pod_base: str | None) -> str:
    notes = Path(notes)
    rows = []
    for wiki in discover_wikis(notes):
        rows.append(_row(notes, wiki.path))
        for page in wiki.pages:
            rows.append(_row(notes, page.local))
    rows.sort()

    digest = hashlib.sha256()
    digest.update(f"{INDEX_VERSION}\n{pod_base or ''}\n".encode("utf-8"))
    for relative, size, mtime in rows:
        digest.update(f"{relative}\0{size}\0{mtime}\n".encode("utf-8"))
    return digest.hexdigest()


def build(notes: Path, pod_base: str | None) -> IndexPayload:
    notes = Path(notes)
    documents = [
        document_from_page(page)
        for wiki in discover_wikis(notes, pod_base)
        for page in wiki.pages
    ]
    documents.sort(key=lambda document: (document.wiki, document.id))

    return IndexPayload(
        version=INDEX_VERSION,
        generated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        notes=str(notes),
        fingerprint=fingerprint(notes, pod_base),
        pages=len(documents),
        documents=tuple(documents),
    )


def write(payload: IndexPayload, state: Path) -> Path:
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    target = state / INDEX_NAME

    handle, temporary = tempfile.mkstemp(dir=state, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(_payload_to_dict(payload), stream, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, target)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise

    return target


def load(state: Path) -> IndexPayload:
    data = json.loads((Path(state) / INDEX_NAME).read_text(encoding="utf-8"))
    return IndexPayload(
        version=data["version"],
        generated=data["generated"],
        notes=data["notes"],
        fingerprint=data["fingerprint"],
        pages=data["pages"],
        documents=tuple(_document_from_dict(item) for item in data["documents"]),
    )


def is_stale(notes: Path, pod_base: str | None, state: Path) -> bool:
    try:
        payload = load(state)
    except (OSError, ValueError, KeyError, TypeError):
        return True
    return payload.fingerprint != fingerprint(notes, pod_base)


def _row(notes: Path, target: Path) -> tuple[str, int, int]:
    stat = target.stat()
    return str(target.relative_to(notes)), stat.st_size, stat.st_mtime_ns


def _payload_to_dict(payload: IndexPayload) -> dict:
    return {
        "version": payload.version,
        "generated": payload.generated,
        "notes": payload.notes,
        "fingerprint": payload.fingerprint,
        "pages": payload.pages,
        "documents": [
            _document_to_dict(document) for document in payload.documents
        ],
    }


def _document_to_dict(document: Document) -> dict:
    return {
        "id": document.id,
        "wiki": document.wiki,
        "label": document.label,
        "subject": document.subject,
        "terms": dict(document.terms),
        "headings": list(document.headings),
        "links": list(document.links),
        "summary": document.summary,
    }


def _document_from_dict(data: dict) -> Document:
    return Document(
        id=data["id"],
        wiki=data["wiki"],
        label=data["label"],
        subject=data["subject"],
        terms=dict(data["terms"]),
        headings=tuple(data["headings"]),
        links=tuple(data["links"]),
        text="",
        summary=data["summary"],
    )
