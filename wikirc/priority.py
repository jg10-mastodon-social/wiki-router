"""Load the wiki-preference policy used when candidates tie.

A corpus can be dominated by one collection of short notes, which then wins
against more deliberate pages elsewhere on small margins. The policy names the
wikis that lose those ties: when the top candidate belongs to one of them and
another wiki has a candidate within `within` of its score, the other wiki's page
takes the top slot.

It is a tie-break, not a weight. A candidate leading by more than the margin is
never displaced, so the rule stays surgical, and a policy with no entries changes
nothing at all.

The ordering itself lives in `score`, where ranking happens; this module only
reads the file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

from .score import order_candidates

PRIORITY_FILE = "wiki_priority.json"
DEFAULT_WITHIN = 0.05

__all__ = [
    "Priority",
    "PRIORITY_FILE",
    "DEFAULT_WITHIN",
    "load_priority",
    "order_candidates",
]


class Priority(NamedTuple):
    last: tuple[str, ...] = ()
    within: float = DEFAULT_WITHIN


def load_priority(path: Path | None) -> Priority:
    """Read a priority file. A missing file means no policy."""
    if path is None:
        return Priority()
    path = Path(path)
    if not path.is_file():
        return Priority()

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("priority file must be a JSON object")
    if "last" not in data:
        raise ValueError('priority file must contain a "last" list')

    last = data["last"]
    if not isinstance(last, list) or not all(isinstance(name, str) for name in last):
        raise ValueError('priority "last" must be a list of wiki names')

    within = data.get("within", DEFAULT_WITHIN)
    if not isinstance(within, (int, float)) or isinstance(within, bool) or within < 0:
        raise ValueError('priority "within" must be a non-negative number')

    return Priority(last=tuple(last), within=float(within))
