import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from . import CONTRACT, __version__, append as append_ops, evaluate, router, store
from .config import ConfigError, load_config
from .corpus import discover_wikis
from .fetch import FetchResult, fetch
from .redirects import REDIRECTS_FILE, load_redirects


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wiki-router")
    subparsers = parser.add_subparsers(dest="command", required=True)

    version = subparsers.add_parser(
        "version", help="print version information"
    )
    version.add_argument(
        "--json", action="store_true", dest="as_json", help="print JSON"
    )

    config = subparsers.add_parser(
        "config", help="print the resolved configuration"
    )
    config.add_argument(
        "--json", action="store_true", dest="as_json", help="print JSON"
    )

    build = subparsers.add_parser(
        "build", help="build the routing index"
    )
    build.add_argument(
        "--check", action="store_true", help="report staleness without writing"
    )
    build.add_argument(
        "--json", action="store_true", dest="as_json", help="print JSON"
    )

    route = subparsers.add_parser(
        "route", help="route a URL against the routing index"
    )
    route.add_argument("url")
    route.add_argument("--top", type=int, default=5)
    route.add_argument("--wiki", default="")
    route.add_argument("--exclude-wiki", default="", dest="exclude_wiki")
    route.add_argument("--context", default="")
    route.add_argument("--title", default="")
    route.add_argument("--description", default="")
    route.add_argument("--redirects", type=Path, default=None)
    route.add_argument(
        "--no-fetch",
        action="store_true",
        dest="no_fetch",
        help="describe a fetch that did not happen",
    )
    route.add_argument(
        "--json", action="store_true", dest="as_json", help="print JSON"
    )

    evaluate_parser = subparsers.add_parser(
        "eval", help="replay known routing decisions from a fixture"
    )
    evaluate_parser.add_argument("--fixture", type=Path, default=None)
    evaluate_parser.add_argument("--top", type=int, default=5)
    evaluate_parser.add_argument("--redirects", type=Path, default=None)
    evaluate_parser.add_argument(
        "--json", action="store_true", dest="as_json", help="print JSON"
    )

    append_parser = subparsers.add_parser(
        "append", help="plan or apply appending a link to a page"
    )
    append_parser.add_argument("url")
    append_parser.add_argument("--page", required=True)
    append_parser.add_argument("--title", default="")
    append_parser.add_argument("--note", default="")
    append_parser.add_argument("--section", default="")
    append_parser.add_argument(
        "--apply", action="store_true", dest="apply_changes"
    )
    append_parser.add_argument(
        "--json", action="store_true", dest="as_json", help="print JSON"
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "version":
        return _print_version(args.as_json)
    if args.command == "config":
        return _print_config(args.as_json)
    if args.command == "build":
        return _run_build(args.check, args.as_json)
    if args.command == "route":
        return _run_route(args)
    if args.command == "eval":
        return _run_eval(args.fixture, args.top, args.as_json, args.redirects)
    if args.command == "append":
        return _run_append(args)

    raise AssertionError(f"unhandled command: {args.command}")


def _print_version(as_json: bool) -> int:
    if as_json:
        print(json.dumps({"version": __version__, "contract": CONTRACT}))
    else:
        print(f"wiki-router {__version__} (contract {CONTRACT})")
    return 0


def _print_config(as_json: bool) -> int:
    try:
        config = load_config()
    except ConfigError as error:
        print(f"wiki-router: {error}", file=sys.stderr)
        return 2

    if as_json:
        print(
            json.dumps(
                {
                    "notes": str(config.notes),
                    "state": str(config.state),
                    "podBase": config.pod_base,
                }
            )
        )
    else:
        pod_base = config.pod_base if config.pod_base is not None else "-"
        print(f"notes: {config.notes}")
        print(f"state: {config.state}")
        print(f"podBase: {pod_base}")
    return 0


def _run_build(check: bool, as_json: bool) -> int:
    try:
        config = load_config()
    except ConfigError as error:
        print(f"wiki-router: {error}", file=sys.stderr)
        return 2

    payload = store.build(config.notes, config.pod_base)

    if check:
        stale = store.is_stale(config.notes, config.pod_base, config.state)
        if as_json:
            print(json.dumps(_build_report(payload, stale)))
        else:
            print("index is stale" if stale else "index is up to date")
        return 1 if stale else 0

    path = store.write(payload, config.state)
    if as_json:
        print(json.dumps(_build_report(payload, False)))
    else:
        print(f"indexed {payload.pages} pages -> {path}")
    return 0


def _build_report(payload: store.IndexPayload, stale: bool) -> dict:
    return {
        "pages": payload.pages,
        "fingerprint": payload.fingerprint,
        "generated": payload.generated,
        "notes": payload.notes,
        "stale": stale,
    }


def _load_redirects(path: Path) -> dict[str, str] | None:
    try:
        return load_redirects(path)
    except (ValueError, OSError) as error:
        print(f"wiki-router: {error}", file=sys.stderr)
        return None


def _run_eval(
    fixture: Path | None,
    top: int,
    as_json: bool,
    redirects: Path | None = None,
) -> int:
    try:
        config = load_config()
    except ConfigError as error:
        print(f"wiki-router: {error}", file=sys.stderr)
        return 2

    path = Path(fixture) if fixture is not None else evaluate.DEFAULT_FIXTURE
    if not path.is_file():
        print(f"eval fixture not found: {path}", file=sys.stderr)
        return 1

    try:
        index = store.load(config.state)
    except FileNotFoundError:
        print("routing index missing: run build", file=sys.stderr)
        return 1

    try:
        cases = evaluate.load_cases(path)
    except ValueError as error:
        print(f"wiki-router: {error}", file=sys.stderr)
        return 1

    mapping = _load_redirects(
        redirects if redirects is not None else config.state / REDIRECTS_FILE
    )
    if mapping is None:
        return 2

    payload = evaluate.evaluate(index.documents, cases, top=top, redirects=mapping)
    payload["fixture"] = str(path)

    if as_json:
        print(json.dumps(payload))
    else:
        _print_eval(payload)

    return 0 if payload["hit_at_top"] == payload["total"] else 1


def _print_eval(payload: dict) -> None:
    print(f"fixture: {payload['fixture']}")
    for result in payload["cases"]:
        rank = result["rank"]
        marker = f"ok   #{rank}   " if rank else "MISS —    "
        print(f"{marker}{result['url']}")
        print(f"     want {', '.join(result['expected'])}")
        if not rank:
            print(f"     got  {', '.join(result['top']) or '-'}")
    print()
    print(
        f"hit@1 {payload['hit_at_1']}/{payload['total']}"
        f" · hit@{payload['top']} {payload['hit_at_top']}/{payload['total']}"
    )


def _run_route(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as error:
        print(f"wiki-router: {error}", file=sys.stderr)
        return 2

    try:
        index = store.load(config.state)
    except FileNotFoundError:
        print("routing index missing: run build", file=sys.stderr)
        return 1

    if store.is_stale(config.notes, config.pod_base, config.state):
        print("warning: index is stale; run build", file=sys.stderr)

    if args.no_fetch:
        fetched = FetchResult.disabled(args.url)
    else:
        fetched = fetch(args.url)

    overrides = {}
    if args.title:
        overrides["title"] = args.title
    if args.description:
        overrides["description"] = args.description
    if overrides:
        fetched = replace(fetched, **overrides)

    mapping = _load_redirects(
        args.redirects if args.redirects is not None else config.state / REDIRECTS_FILE
    )
    if mapping is None:
        return 2

    payload = router.route_payload(
        index.documents,
        args.url,
        fetched=fetched,
        context=args.context,
        top=args.top,
        wiki=args.wiki,
        exclude_wiki=args.exclude_wiki,
        redirects=mapping,
    )

    if args.as_json:
        print(json.dumps(payload))
        return 0

    print(f"url: {payload['url']}")
    print(f"title: {payload['fetched']['title']}")
    print(f"reliability: {payload['reliability']}")
    for candidate in payload["candidates"]:
        print(
            f"{candidate['score']:.4f} "
            f"{candidate['wiki']}/{candidate['label']} ({candidate['id']})"
        )
    return 0


def _run_append(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as error:
        print(f"wiki-router: {error}", file=sys.stderr)
        return 2

    try:
        index = store.load(config.state)
    except FileNotFoundError:
        print("routing index missing: run build", file=sys.stderr)
        return 1

    document = _resolve_document(index.documents, args.page)
    page = None
    if document is not None:
        page = _find_page(config.notes, config.pod_base, document)
    if page is None:
        print(f"page not found: {args.page}", file=sys.stderr)
        return 1

    title = args.title
    if not title:
        fetched = fetch(args.url)
        title = fetched.title or router._title_from_url(args.url)

    plan = append_ops.plan_append(
        page, title, args.url, note=args.note, section=args.section
    )

    applied = False
    if args.apply_changes and plan.ok:
        append_ops.apply(plan, page)
        applied = True

    if args.as_json:
        print(
            json.dumps(
                {
                    "ok": plan.ok,
                    "page": f"{plan.wiki}/{plan.page_id}",
                    "id": plan.page_id,
                    "bullet": plan.bullet,
                    "section": plan.section,
                    "diff": plan.diff,
                    "already_present": plan.already_present,
                    "applied": applied,
                }
            )
        )
        return 0 if plan.ok else 1

    print(f"page: {plan.wiki}/{plan.page_id}")
    print(f"section: {plan.section}")
    print(f"bullet: {plan.bullet}")
    if plan.diff:
        print(plan.diff, end="")
    if plan.already_present:
        print("already present")
    if applied:
        print("applied")
    return 0 if plan.ok else 1


def _resolve_document(documents, query: str):
    for document in documents:
        if document.id == query:
            return document
    for document in documents:
        if f"{document.wiki}/{document.id}" == query:
            return document

    lowered = query.casefold()
    for document in documents:
        if document.label.casefold() == lowered:
            return document
    for document in documents:
        if document.subject is not None and document.subject == query:
            return document
    return None


def _find_page(notes, pod_base, document):
    for wiki in discover_wikis(notes, pod_base):
        if wiki.name != document.wiki:
            continue
        for page in wiki.pages:
            if page.id == document.id:
                return page
    return None
