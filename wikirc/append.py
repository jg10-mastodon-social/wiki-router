"""Plan and apply a single markdown bullet append."""

import difflib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .corpus import Page
from .text import tokenize

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_REFERENCE = re.compile(r"^\[[^\]]+\]:\s*\S")
_MARKDOWN_LINK = re.compile(
    r"\[[^\]]*\]\(\s*(?:<([^>]*)>|([^)\s]+))"
)
_BARE_URL = re.compile(r"https?://[^\s<>()\[\]]+")
_SENTENCE_PUNCTUATION = ".,;:!?"


@dataclass(frozen=True)
class AppendPlan:
    ok: bool
    page_id: str
    wiki: str
    bullet: str
    section: str
    diff: str
    already_present: bool
    reason: str


def markdown_link(title: str, url: str) -> str:
    title = " ".join(title.split())
    if any(char in url for char in "() "):
        url = f"<{url}>"
    return f"[{title}]({url})"


def link_key(url: str) -> tuple[str, str, str]:
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return ("", url, "")
    if parts.scheme not in ("http", "https") or not host:
        return ("", url, "")

    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "dx.doi.org":
        host = "doi.org"
    path = unquote(parts.path).rstrip("/")
    return (host, path, parts.query)


def existing_links(text: str) -> list[str]:
    markdown_spans = []
    found = []
    for match in _MARKDOWN_LINK.finditer(text):
        markdown_spans.append((match.start(), match.end()))
        target = (
            match.group(1) if match.group(1) is not None else match.group(2)
        )
        found.append((match.start(), target.rstrip(_SENTENCE_PUNCTUATION)))

    for match in _BARE_URL.finditer(text):
        if any(start <= match.start() < end for start, end in markdown_spans):
            continue
        found.append(
            (match.start(), match.group(0).rstrip(_SENTENCE_PUNCTUATION))
        )

    found.sort(key=lambda item: item[0])
    links = []
    for _, target in found:
        if target not in links:
            links.append(target)
    return links


def choose_section(text: str, title: str, requested: str = "") -> str:
    headings = _headings(text)
    if not headings:
        return ""

    if requested:
        lowered = requested.casefold()
        for _, _, name in headings:
            if name.casefold() == lowered:
                return name
        closest = _best_overlap(headings, _tokens(requested))
        if closest is not None:
            return closest

    best = _best_overlap(headings, _tokens(title))
    if best is not None:
        return best

    for _, _, name in headings:
        if name.casefold() == "unsorted":
            return name
    return ""


def plan_append(
    page: Page, title: str, url: str, note: str = "", section: str = ""
) -> AppendPlan:
    text = Path(page.local).read_text(encoding="utf-8")
    bullet = f"- {markdown_link(title, url)}"
    if note:
        bullet = f"{bullet} — {note}"
    chosen = choose_section(text, title, section)

    wanted = link_key(url)
    present = any(link_key(link) == wanted for link in existing_links(text))
    if present:
        return AppendPlan(
            ok=False,
            page_id=page.id,
            wiki=page.wiki,
            bullet=bullet,
            section=chosen,
            diff="",
            already_present=True,
            reason="already-present",
        )

    edited = _insert(text, chosen, bullet)
    diff = "".join(
        difflib.unified_diff(
            text.splitlines(keepends=True),
            edited.splitlines(keepends=True),
            fromfile=f"a/{page.id}",
            tofile=f"b/{page.id}",
            n=3,
        )
    )
    return AppendPlan(
        ok=True,
        page_id=page.id,
        wiki=page.wiki,
        bullet=bullet,
        section=chosen,
        diff=diff,
        already_present=False,
        reason="",
    )


def apply(plan: AppendPlan, page: Page) -> None:
    if not plan.ok:
        return

    path = Path(page.local)
    text = path.read_text(encoding="utf-8")
    edited = _insert(text, plan.section, plan.bullet)

    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(edited)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def _headings(text: str) -> list[tuple[int, int, str]]:
    headings = []
    for position, line in enumerate(text.splitlines()):
        match = _HEADING.match(line)
        if match is not None:
            headings.append(
                (position, len(match.group(1)), match.group(2).strip())
            )
    return headings


def _tokens(text: str) -> set[str]:
    return set(tokenize(text, bigrams=False))


def _best_overlap(
    headings: list[tuple[int, int, str]], wanted: set[str]
) -> str | None:
    best = None
    best_score = 0
    for _, _, name in headings:
        score = len(_tokens(name) & wanted)
        if score > best_score:
            best = name
            best_score = score
    return best


def _insert(text: str, section: str, bullet: str) -> str:
    lines = text.splitlines(keepends=True)
    headings = _headings(text)

    if section:
        start = None
        level = 0
        for position, heading_level, name in headings:
            if name == section:
                start = position
                level = heading_level
                break

        if start is None:
            target = _body_end(lines)
        else:
            stop = len(lines)
            for position, heading_level, _ in headings:
                if position > start and heading_level <= level:
                    stop = position
                    break
            target = _last_body_line(lines, start + 1, stop)
            if target is None:
                target = start
    else:
        target = _body_end(lines)

    return _splice(lines, target, bullet)


def _last_body_line(lines: list[str], start: int, stop: int) -> int | None:
    for position in range(stop - 1, start - 1, -1):
        line = lines[position]
        if line.strip() and not _REFERENCE.match(line):
            return position
    return None


def _body_end(lines: list[str]) -> int | None:
    for position in range(len(lines) - 1, -1, -1):
        line = lines[position]
        if line.strip() and not _REFERENCE.match(line):
            return position
    return None


def _splice(lines: list[str], target: int | None, bullet: str) -> str:
    index = -1 if target is None else target
    head = list(lines[: index + 1])
    tail = lines[index + 1 :]

    if head and not head[-1].endswith(("\n", "\r")):
        head[-1] = head[-1] + "\n"
    if head and head[-1].strip():
        head.append("\n")

    head.append(bullet + "\n")

    if tail and tail[0].strip():
        head.append("\n")

    return "".join(head + tail)
