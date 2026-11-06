import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from .index import LabelEntry, load_label_index

INDEX_NAME = "label-index.ttl"
MAX_TEXT = 20000
MAX_BYTES = 200000

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_BARE_URL = re.compile(r"https?://[^\s<>()\[\]]+")


@dataclass(frozen=True)
class Page:
    id: str
    wiki: str
    label: str
    subject: str | None
    local: Path
    headings: tuple[str, ...]
    links: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Wiki:
    name: str
    path: Path
    pages: tuple[Page, ...]


def discover_wikis(notes: Path, pod_base: str | None = None) -> list[Wiki]:
    notes = Path(notes)
    wikis = []
    for child in notes.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        if not (child / INDEX_NAME).is_file():
            continue
        wikis.append(_build_wiki(child, pod_base))
    wikis.sort(key=lambda wiki: wiki.name)
    return wikis


def _build_wiki(path: Path, pod_base: str | None) -> Wiki:
    pages = []
    for entry in load_label_index(path / INDEX_NAME):
        page = _build_page(path, entry, pod_base)
        if page is not None:
            pages.append(page)
    pages.sort(key=lambda page: page.id)
    return Wiki(name=path.name, path=path, pages=tuple(pages))


def _build_page(
    path: Path, entry: LabelEntry, pod_base: str | None
) -> Page | None:
    if not entry.labels:
        return None

    page_id = _resolve_id(entry.ref, path.name)
    if page_id is None:
        return None

    local = _resolve_file(path, page_id)
    if local is None:
        return None

    try:
        text = local.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    subject = None
    if pod_base is not None:
        subject = f"{pod_base}/{quote(path.name)}/{quote(page_id)}"

    return Page(
        id=page_id,
        wiki=path.name,
        label=_pick_label(entry.labels),
        subject=subject,
        local=local,
        headings=_headings(text),
        links=_links(text),
        text=text[:MAX_TEXT],
    )


def _resolve_id(ref: str, wiki: str) -> str | None:
    if ref.startswith(("http://", "https://")):
        url_path = unquote(urlsplit(ref).path)
        marker = f"/{wiki}/"
        index = url_path.rfind(marker)
        if index == -1:
            return None
        return url_path[index + len(marker) :]
    return unquote(ref).lstrip("/")


def _resolve_file(path: Path, page_id: str) -> Path | None:
    for candidate in (path / page_id, path / (page_id + "$.txt")):
        if candidate.is_file() and candidate.stat().st_size <= MAX_BYTES:
            return candidate
    return None


def _pick_label(labels: tuple[str, ...]) -> str:
    for label in labels:
        if not label.startswith("/"):
            return label
    return labels[0]


def _headings(text: str) -> tuple[str, ...]:
    headings = []
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match is not None:
            headings.append(match.group(2).strip())
    return tuple(headings)


def _links(text: str) -> tuple[str, ...]:
    found = []
    for match in _MD_LINK.finditer(text):
        target = match.group(1)
        if target.startswith(("http://", "https://")):
            found.append((match.start(), target))
    for match in _BARE_URL.finditer(text):
        found.append((match.start(), match.group(0).rstrip(".,;:!?")))
    found.sort(key=lambda item: item[0])

    links = []
    for _, target in found:
        if target not in links:
            links.append(target)
    return tuple(links)
