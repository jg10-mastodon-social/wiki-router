import unittest
import urllib.error
from unittest import mock

from wikirc.fetch import (
    FETCH_TIMEOUT,
    MAX_FETCH_BYTES,
    USER_AGENT,
    FetchResult,
    clean_title,
    extract,
    fetch,
    http_get,
    title_is_noisy,
)

BASE = "https://example.com/notes/"
HTML = "text/html; charset=utf-8"


class FakeResponse:
    def __init__(
        self,
        body=b"",
        url="https://example.com/final/",
        content_type=HTML,
    ):
        self.body = body
        self.url = url
        self.headers = {"Content-Type": content_type}
        self.read_sizes = []

    def read(self, size=None):
        self.read_sizes.append(size)
        return self.body if size is None else self.body[:size]

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def fake_getter(
    body=b"<title>Notes</title>",
    final_url="https://example.com/notes/",
    content_type=HTML,
):
    calls = []

    def getter(url, timeout, limit):
        calls.append((url, timeout, limit))
        return final_url, content_type, body

    getter.calls = calls
    return getter


def raising_getter(error):
    def getter(url, timeout, limit):
        raise error

    return getter


class ExtractTests(unittest.TestCase):
    def test_og_title_beats_twitter_title_beats_title(self):
        html = (
            "<title>Plain title</title>"
            '<meta property="og:title" content="Open graph title">'
            '<meta name="twitter:title" content="Twitter title">'
        )

        self.assertEqual(extract(html, BASE)["title"], "Open graph title")

        without_og = (
            "<title>Plain title</title>"
            '<meta name="twitter:title" content="Twitter title">'
        )
        self.assertEqual(extract(without_og, BASE)["title"], "Twitter title")
        self.assertEqual(
            extract("<title>Plain title</title>", BASE)["title"],
            "Plain title",
        )

    def test_entities_are_unescaped_in_title_and_description(self):
        html = (
            '<meta property="og:title" content="Tom &amp; Jerry&#39;s page">'
            '<meta property="og:description"'
            ' content="Notes &lt;about&gt; soil &amp; water">'
        )

        extracted = extract(html, BASE)

        self.assertEqual(extracted["title"], "Tom & Jerry's page")
        self.assertEqual(
            extracted["description"], "Notes <about> soil & water"
        )

    def test_og_description_beats_meta_description(self):
        html = (
            '<meta property="og:description" content="Open graph summary">'
            '<meta name="description" content="Plain summary">'
        )

        self.assertEqual(
            extract(html, BASE)["description"], "Open graph summary"
        )
        self.assertEqual(
            extract(
                '<meta name="description" content="Plain summary">', BASE
            )["description"],
            "Plain summary",
        )

    def test_canonical_is_resolved_against_the_base_url(self):
        html = '<link rel="canonical" href="../canonical/">'

        parsed = extract(html, "https://example.com/notes/page")

        self.assertEqual(parsed["canonical"], "https://example.com/canonical/")

    def test_missing_values_are_empty(self):
        parsed = extract("<p>No metadata here</p>", BASE)

        self.assertEqual(
            parsed, {"title": "", "description": "", "canonical": ""}
        )


class CleanTitleTests(unittest.TestCase):
    def test_suffix_matching_the_host_is_stripped(self):
        self.assertEqual(
            clean_title("Watering notes | Example", "https://example.com/a"),
            "Watering notes",
        )
        self.assertEqual(
            clean_title("Watering notes - Example", "https://example.com/a"),
            "Watering notes",
        )
        self.assertEqual(
            clean_title("Watering notes — Example", "https://example.com/a"),
            "Watering notes",
        )

    def test_unrelated_suffix_is_kept(self):
        self.assertEqual(
            clean_title("Watering notes | Garden", "https://example.com/a"),
            "Watering notes | Garden",
        )

    def test_overlong_suffix_is_kept(self):
        title = "Watering notes | An unrelated site name"

        self.assertEqual(clean_title(title, "https://example.com/a"), title)

    def test_surrounding_whitespace_is_trimmed(self):
        self.assertEqual(
            clean_title("  Watering notes  ", "https://example.com/a"),
            "Watering notes",
        )


class TitleNoisyTests(unittest.TestCase):
    def test_empty_title_is_noisy(self):
        self.assertTrue(title_is_noisy("", BASE))

    def test_overlong_title_is_noisy(self):
        self.assertTrue(title_is_noisy("x" * 121, BASE))

    def test_blocked_phrases_are_noisy(self):
        for title in (
            "Just a moment...",
            "Access denied",
            "Attention Required!",
            "Redirecting to the page",
            "Page not found",
        ):
            with self.subTest(title=title):
                self.assertTrue(title_is_noisy(title, BASE))

    def test_normal_title_is_not_noisy(self):
        self.assertFalse(title_is_noisy("Watering notes", BASE))


class HttpGetTests(unittest.TestCase):
    def test_reads_at_most_the_limit_and_returns_raw_bytes(self):
        response = FakeResponse(body=b"x" * 5000)

        with mock.patch(
            "urllib.request.urlopen", return_value=response
        ) as urlopen:
            final_url, content_type, body = http_get(
                "https://example.com/notes/", 15, 10
            )

        self.assertEqual(final_url, "https://example.com/final/")
        self.assertEqual(content_type, HTML)
        self.assertEqual(body, b"x" * 10)
        self.assertEqual(response.read_sizes, [10])
        request = urlopen.call_args[0][0]
        self.assertEqual(request.headers["User-agent"], USER_AGENT)
        self.assertEqual(request.headers["Accept"], "text/html")
        self.assertEqual(request.headers["Accept-encoding"], "identity")


class FetchErrorTests(unittest.TestCase):
    def test_unsupported_content_type_fails(self):
        result = fetch(
            "https://example.com/file.pdf",
            getter=fake_getter(content_type="application/pdf"),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "unsupported content type")

    def test_xhtml_is_accepted(self):
        result = fetch(
            "https://example.com/notes/",
            getter=fake_getter(content_type="application/xhtml+xml"),
        )

        self.assertTrue(result.ok)

    def test_http_error_reports_the_status_code(self):
        error = urllib.error.HTTPError(
            "https://example.com/", 403, "Forbidden", None, None
        )

        result = fetch("https://example.com/", getter=raising_getter(error))

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "HTTP 403")

    def test_url_error_reports_an_unreachable_host(self):
        error = urllib.error.URLError("boom")

        result = fetch("https://example.com/", getter=raising_getter(error))

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "cannot reach host")

    def test_timeout_is_reported(self):
        result = fetch(
            "https://example.com/", getter=raising_getter(TimeoutError())
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timed out")

    def test_unexpected_error_is_reported(self):
        result = fetch(
            "https://example.com/", getter=raising_getter(ValueError("bad"))
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "fetch error")


class FetchSuccessTests(unittest.TestCase):
    def test_success_reports_the_redirect_target_and_html(self):
        body = (
            "<html><head>"
            "<title>Watering notes | Example</title>"
            '<meta property="og:description" content="Keep soil damp">'
            '<link rel="canonical" href="/watering/">'
            "</head></html>"
        ).encode()

        result = fetch(
            "https://example.com/old/",
            getter=fake_getter(
                body=body, final_url="https://example.com/watering/"
            ),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.source, "html")
        self.assertEqual(result.final_url, "https://example.com/watering/")
        self.assertEqual(result.title, "Watering notes")
        self.assertEqual(result.description, "Keep soil damp")
        self.assertEqual(result.canonical, "https://example.com/watering/")
        self.assertFalse(result.title_noisy)
        self.assertEqual(result.error, "")

    def test_noisy_titles_are_flagged_after_cleaning(self):
        body = b"<title>Just a moment...</title>"

        result = fetch("https://example.com/", getter=fake_getter(body=body))

        self.assertTrue(result.ok)
        self.assertTrue(result.title_noisy)

    def test_undecodable_bytes_are_replaced(self):
        body = b"<title>Caf\xc3</title>"

        result = fetch("https://example.com/", getter=fake_getter(body=body))

        self.assertTrue(result.ok)
        self.assertEqual(result.title, "Caf\ufffd")

    def test_default_timeout_and_limit_are_passed_to_the_getter(self):
        getter = fake_getter()

        fetch("https://example.com/", getter=getter)

        self.assertEqual(
            getter.calls,
            [("https://example.com/", FETCH_TIMEOUT, MAX_FETCH_BYTES)],
        )
        self.assertEqual(FETCH_TIMEOUT, 15)


class FetchResultTests(unittest.TestCase):
    def test_disabled_describes_a_fetch_that_did_not_happen(self):
        result = FetchResult.disabled("https://example.com/a")

        self.assertFalse(result.ok)
        self.assertEqual(result.final_url, "https://example.com/a")
        self.assertEqual(result.error, "fetch disabled")
        self.assertEqual(result.source, "")
        self.assertEqual(result.title, "")

    def test_failed_carries_the_error(self):
        result = FetchResult.failed("https://example.com/a", "timed out")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timed out")


if __name__ == "__main__":
    unittest.main()
