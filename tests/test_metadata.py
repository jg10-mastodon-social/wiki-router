import unittest
from pathlib import Path

from tests import metadata_eval
from wikirc.fetch import fetch

FIXTURE = Path(__file__).parent / "fixtures" / "metadata" / "doi_eval.json"
BOOK_FIXTURE = (
    Path(__file__).parent / "fixtures" / "metadata" / "book_eval.json"
)


def fetcher(url, json_getter):
    """Resolve a DOI without ever touching the HTML getter.

    A DOI must be answered by Crossref alone. If the implementation falls back
    to the publisher page the getter raises, and the case fails on the result
    it produces instead of a title.
    """

    def html_getter(*args, **kwargs):
        raise AssertionError(f"HTML getter called for {url}")

    return fetch(url, getter=html_getter, json_getter=json_getter)


def book_fetcher(url, json_getter):
    """Resolve an archive.org book without ever touching the HTML getter."""

    def html_getter(*args, **kwargs):
        raise AssertionError(f"HTML getter called for {url}")

    return fetch(url, getter=html_getter, json_getter=json_getter)


class DoiEvalTests(unittest.TestCase):
    def test_every_recorded_case_passes(self):
        results = metadata_eval.run_cases(FIXTURE, fetcher)

        if not all(result["ok"] for result in results):
            self.fail("\n" + metadata_eval.report(results))


class BookEvalTests(unittest.TestCase):
    def test_every_recorded_case_passes(self):
        results = metadata_eval.run_cases(BOOK_FIXTURE, book_fetcher)

        if not all(result["ok"] for result in results):
            self.fail("\n" + metadata_eval.report(results))


if __name__ == "__main__":
    unittest.main()
