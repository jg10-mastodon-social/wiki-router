"""Expand a query with the vocabulary a corpus uses for the same subject.

A page is often filed under a name the link never uses: a paper about foresight
belongs with futures, and a method called causal layered analysis is futures
material. Scoring is lexical, so without this the query shares no words with the
right page.

The map is external and optional, because the vocabulary of a corpus is a fact
about that corpus rather than about the tool:

    { "foresight": "futures", "causal layered analysis": "futures" }

Phrases are allowed and are matched longest-first. Expansion applies to what a
caller knows — title, description, context — not to the page index, so changing
the map never invalidates an index.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SYNONYMS_FILE = "synonyms.json"

__all__ = ["SYNONYMS_FILE", "load_synonyms", "expand"]


def load_synonyms(path: Path | None) -> dict[str, str]:
    """Read a synonym map. A missing file means no expansion."""
    if path is None:
        return {}
    path = Path(path)
    if not path.is_file():
        return {}

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("synonyms file must be a JSON object")

    synonyms: dict[str, str] = {}
    for phrase, replacement in data.items():
        if not isinstance(phrase, str) or not isinstance(replacement, str):
            raise ValueError("synonyms must map phrases to phrases")
        if not phrase.strip() or not replacement.strip():
            raise ValueError("synonyms must not contain empty phrases")
        synonyms[phrase.casefold().strip()] = replacement.strip().casefold()

    return synonyms


def expand(text: str, synonyms: dict[str, str]) -> str:
    """Append replacements for the synonym phrases found in `text`.

    The original text is kept: a phrase is evidence in its own right, and adding
    the subject it belongs to must not remove it. When phrases overlap, the
    longest claims the span, so `causal layered analysis` wins over
    `causal layered`.
    """
    if not text or not synonyms:
        return text

    taken: list[tuple[int, int]] = []
    found: list[str] = []
    for phrase in sorted(synonyms, key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < other_end and other_start < end for other_start, other_end in taken):
                continue
            taken.append((start, end))
            found.append(synonyms[phrase])

    if not found:
        return text
    return text + " " + " ".join(dict.fromkeys(found))
