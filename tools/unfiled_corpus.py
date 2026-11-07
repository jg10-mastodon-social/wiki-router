"""Produce an "unfiled" copy of a notes tree for evaluation.

A recorded routing decision usually comes from a link that was already added to
the page it belongs on. Replaying that fixture against the live corpus measures
the wrong thing: the answer page already contains the link, so its text carries
the link's words and any already-linked boost fires. Removing every fixture URL
from the corpus first gives the state the router actually faces — a link nobody
has seen yet.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from itertools import product
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

PAGE_SUFFIXES = (".md", ".md$.txt")


def url_variants(url: str) -> tuple[str, ...]:
    """Forms of the same URL that may appear in a page."""
    url = url.strip()
    if not url:
        return ()

    parts = urlsplit(url)
    schemes = {parts.scheme or "https"}
    schemes.add("http" if "https" in schemes else "https")

    host = (parts.hostname or "").lower()
    hosts = {host}
    if host.startswith("www."):
        hosts.add(host[4:])
    elif host:
        hosts.add(f"www.{host}")
    if host in ("doi.org", "dx.doi.org"):
        hosts.update(("doi.org", "dx.doi.org"))

    path = parts.path
    paths = {path, path.rstrip("/"), unquote(path), quote(unquote(path))}
    suffix = f"?{parts.query}" if parts.query else ""

    variants = {url, url.rstrip("/")}
    for scheme, host_form, path_form in product(schemes, hosts, paths):
        variants.add(f"{scheme}://{host_form}{path_form}{suffix}")

    return tuple(sorted(variant for variant in variants if variant))


def strip_text(text: str, variants: tuple[str, ...]) -> tuple[str, int]:
    """Drop every line containing one of the variants; return text and count."""
    kept = []
    removed = 0
    for line in text.splitlines(keepends=True):
        if any(variant in line for variant in variants):
            removed += 1
            continue
        kept.append(line)
    return "".join(kept), removed


def unfiled(notes: Path, fixture: Path, out: Path, dry_run: bool = False) -> dict:
    notes = Path(notes)
    out = Path(out)

    data = json.loads(Path(fixture).read_text(encoding="utf-8"))
    cases = data.get("cases", data) if isinstance(data, dict) else list(data)

    variants: dict[str, tuple[str, ...]] = {}
    for case in cases:
        url = case.get("url")
        if url:
            variants[url] = url_variants(url)

    if not dry_run:
        # Preserve symlinks: the corpus may contain dangling ones, and following
        # them would copy targets that do not exist here.
        shutil.copytree(notes, out, dirs_exist_ok=True, symlinks=True)

    root = notes if dry_run else out
    files_changed = 0
    lines_removed = 0
    per_url: dict[str, int] = {url: 0 for url in variants}

    for path in sorted(root.rglob("*")):
        if not path.is_file() or not path.name.endswith(PAGE_SUFFIXES):
            continue
        original = path.read_text(encoding="utf-8")
        text = original
        file_removed = 0
        for url, forms in variants.items():
            text, removed = strip_text(text, forms)
            per_url[url] += removed
            file_removed += removed
        if text != original:
            files_changed += 1
            lines_removed += file_removed
            if not dry_run:
                path.write_text(text, encoding="utf-8")

    residual = []
    if not dry_run:
        present = dict.fromkeys(variants, False)
        for path in out.rglob("*"):
            if not path.is_file() or not path.name.endswith(PAGE_SUFFIXES):
                continue
            content = path.read_text(encoding="utf-8")
            for url, forms in variants.items():
                if not present[url] and any(form in content for form in forms):
                    present[url] = True
        residual = [url for url, found in present.items() if found]

    return {
        "urls": len(variants),
        "files_changed": files_changed,
        "lines_removed": lines_removed,
        "per_url": per_url,
        "residual": residual,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="unfiled-corpus", description=__doc__.splitlines()[0])
    parser.add_argument("--notes", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = unfiled(args.notes, args.fixture, args.out, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        action = "would remove" if args.dry_run else "removed"
        print(
            f"{action} {report['lines_removed']} lines across "
            f"{report['files_changed']} files for {report['urls']} fixture URLs"
        )
        for url, count in report["per_url"].items():
            if count:
                print(f"  {count:>3}  {url}")
        if report["residual"]:
            print(f"residual URLs still present: {report['residual']}", file=sys.stderr)
    return 1 if report["residual"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
