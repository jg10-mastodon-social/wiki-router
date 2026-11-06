import argparse
import json
import sys
from collections.abc import Sequence

from . import CONTRACT, __version__, store
from .config import ConfigError, load_config


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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "version":
        return _print_version(args.as_json)
    if args.command == "config":
        return _print_config(args.as_json)
    if args.command == "build":
        return _run_build(args.check, args.as_json)

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

