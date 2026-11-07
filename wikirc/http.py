"""HTTP transport for fetching pages and JSON records."""

import json
import urllib.request

FETCH_TIMEOUT = 15
MAX_FETCH_BYTES = 600_000
USER_AGENT = "Mozilla/5.0 (compatible; wiki-router/1.0)"


def http_get(url: str, timeout: int, limit: int) -> tuple[str, str, bytes]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(limit)
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
    return final_url, content_type, body


def json_get(url: str, timeout: int, limit: int):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(limit)
    return json.loads(body.decode("utf-8"))
