"""Redirect migrated pages to the page that now holds their content.

When content moves from one page to another, the old page keeps enough of the
original wording to outrank its replacement. Ranking cannot know that; the
migration does. A redirect map states it directly:

    { "notes/futures.md": "topics/futures.md" }

A candidate whose page is a redirect source is reported as its target, keeping the
score it earned and marking the substitution, so the answer is the page the
content lives on now rather than the page it used to live on.

This is explicit data, not a threshold: there is no margin to tune, and an entry
that names a page the corpus does not contain is ignored rather than invented.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Mapping, Sequence

from .score import Candidate, Document

REDIRECTS_FILE = "wiki_redirects.json"

__all__ = ["REDIRECTS_FILE", "load_redirects", "apply_redirects", "page_key"]


def page_key(wiki: str, page_id: str) -> str:
    return f"{wiki}/{page_id}"


def load_redirects(path: Path | None) -> dict[str, str]:
    """Read a redirect map. A missing file means nothing redirects."""
    if path is None:
        return {}
    path = Path(path)
    if not path.is_file():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("redirects file must be a JSON object")

    for source, target in data.items():
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError("redirects must map page keys to page keys")
        if "/" not in source or "/" not in target:
            raise ValueError(f'redirect keys look like "wiki/page.md": {source!r}')

    return dict(data)


def apply_redirects(
    candidates: Sequence[Candidate],
    redirects: Mapping[str, str],
    documents: Mapping[str, Document],
) -> list[Candidate]:
    """Replace redirect sources with their targets, keeping the best score."""
    if not redirects:
        return list(candidates)

    mapped = []
    for row in candidates:
        target_key = redirects.get(page_key(row.wiki, row.id))
        target = documents.get(target_key) if target_key else None
        if target is None:
            mapped.append(row)
            continue
        mapped.append(
            replace(
                row,
                wiki=target.wiki,
                id=target.id,
                label=target.label,
                subject=target.subject,
                headings=target.headings,
                summary=target.summary,
                redirected=True,
                redirected_from=page_key(row.wiki, row.id),
            )
        )

    best: dict[str, Candidate] = {}
    for row in mapped:
        key = page_key(row.wiki, row.id)
        current = best.get(key)
        if current is None or row.score > current.score:
            best[key] = row

    return sorted(best.values(), key=lambda row: (-row.score, row.id))
