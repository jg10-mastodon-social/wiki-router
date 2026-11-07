"""Replay known URL-to-page decisions against the routing index.

The ``eval`` subcommand reads a fixture of URLs, titles and acceptable page
ids, ranks the indexed documents for each case and reports hit rates. A page is
identified by its wiki-qualified id (``garden/watering.md``); the bare index id
(``watering.md``) is accepted as well.

The default fixture is ``tests/fixtures/eval.json``, resolved relative to the
repository root (two levels up from this module). Real fixtures live outside
the repository and are passed with ``--fixture``.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .score import Candidate, Document, Query, rank

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "eval.json"
)


@dataclass(frozen=True)
class Case:
    url: str
    title: str
    acceptable: tuple[str, ...]
    description: str = ""
    context: str = ""
    note: str = ""
    capability: str = ""


def load_cases(path: Path) -> list[Case]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = data["cases"] if isinstance(data, dict) else data

    cases = []
    for index, entry in enumerate(entries):
        if "url" not in entry:
            raise ValueError(f"case {index}: url is required")
        if "acceptable" not in entry:
            raise ValueError(f"case {index}: acceptable is required")
        cases.append(
            Case(
                url=entry["url"],
                title=entry.get("title", ""),
                acceptable=tuple(entry["acceptable"]),
                description=entry.get("description", ""),
                context=entry.get("context", ""),
                note=entry.get("note", ""),
                capability=entry.get("capability", ""),
            )
        )
    return cases


def evaluate(
    documents: Sequence[Document],
    cases: Sequence[Case],
    top: int = 5,
    redirects: Mapping[str, str] = {},
) -> dict:
    results = []
    hit_at_1 = 0
    hit_at_top = 0
    unmet: dict[str, int] = {}
    unclassified = 0

    for case in cases:
        candidates = rank(
            documents,
            Query(
                url=case.url,
                title=case.title,
                description=case.description,
                context=case.context,
            ),
            top=top,
        )
        if redirects:
            from .redirects import apply_redirects, page_key

            by_key = {page_key(d.wiki, d.id): d for d in documents}
            candidates = apply_redirects(candidates, redirects, by_key)[:top]

        position = 0
        for offset, candidate in enumerate(candidates, start=1):
            if candidate.score > 0 and _acceptable(candidate, case.acceptable):
                position = offset
                break

        if position == 1:
            hit_at_1 += 1
        if position:
            hit_at_top += 1

        if position:
            outcome = "hit"
        elif case.capability:
            outcome = "unmet"
            unmet[case.capability] = unmet.get(case.capability, 0) + 1
        else:
            outcome = "unclassified"
            unclassified += 1

        results.append(
            {
                "url": case.url,
                "expected": list(case.acceptable),
                "rank": position,
                "top": [_page_id(candidate) for candidate in candidates],
                "note": case.note,
                "capability": case.capability,
                "outcome": outcome,
            }
        )

    return {
        "pages": len(documents),
        "total": len(cases),
        "top": top,
        "hit_at_1": hit_at_1,
        "hit_at_top": hit_at_top,
        "unmet_capabilities": unmet,
        "unclassified_misses": unclassified,
        "cases": results,
    }


def _page_id(candidate: Candidate) -> str:
    """Identify a page the way fixtures do: ``wiki/id``."""
    return f"{candidate.wiki}/{candidate.id}"


def _acceptable(
    candidate: Candidate, acceptable: Sequence[str]
) -> bool:
    return candidate.id in acceptable or _page_id(candidate) in acceptable
