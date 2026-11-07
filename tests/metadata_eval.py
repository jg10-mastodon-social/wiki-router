"""Replay recorded metadata payloads against a fetcher.

The eval fixture lists, per case, the URL under test, the payload files keyed
by
the URL that serves them, and the fields the result must carry. Payload paths
are relative to the fixture file, so ``doi/simple.json`` means
``tests/fixtures/metadata/doi/simple.json`` for the committed fixture.

``run_cases`` builds one ``json_getter`` per case. That getter raises
``LookupError`` for any URL the case did not map, so a missing payload can
never fall through to the network.
"""

import json
from pathlib import Path

_MISSING = object()


def _payload_getter(responses: dict, base: Path):
    def getter(url, timeout=None, limit=None):
        if url not in responses:
            raise LookupError(url)
        path = base / responses[url]
        return json.loads(path.read_text(encoding="utf-8"))

    return getter


def run_cases(path: Path, fetcher) -> list[dict]:
    """Run every case in ``path`` and collect failures per case."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data["cases"] if isinstance(data, dict) else data

    results = []
    for index, entry in enumerate(entries):
        case = {
            "index": index,
            "url": entry["url"],
            "note": entry.get("note", ""),
        }
        getter = _payload_getter(
            entry.get("responses", {}), path.parent
        )

        try:
            result = fetcher(entry["url"], getter)
        except Exception as error:  # a case may not fall through silently
            results.append(
                {
                    "case": case,
                    "ok": False,
                    "failures": [
                        f"raised {type(error).__name__}: {error}"
                    ],
                }
            )
            continue

        failures = []
        for field, want in entry.get("expects", {}).items():
            got = getattr(result, field, _MISSING)
            if got is _MISSING:
                failures.append(f"{field}: result has no such field")
            elif got != want:
                failures.append(f"{field}: want {want!r}, got {got!r}")

        results.append(
            {"case": case, "ok": not failures, "failures": failures}
        )

    return results


def report(results) -> str:
    """Render a small pass/fail table, with one line per failure."""
    if not results:
        return "no cases"

    width = max(len(result["case"]["url"]) for result in results)
    lines = []
    passed = 0
    for result in results:
        case = result["case"]
        if result["ok"]:
            passed += 1
        marker = "ok  " if result["ok"] else "FAIL"
        lines.append(
            f"{case['index']:>2}  {marker}  {case['url']:<{width}}"
            f"  {case['note']}".rstrip()
        )
        for failure in result["failures"]:
            lines.append(f"               {failure}")

    lines.append("")
    lines.append(f"{passed}/{len(results)} cases pass")
    return "\n".join(lines)
