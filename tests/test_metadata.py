import unittest
from pathlib import Path

from tests import metadata_eval
from wikirc import books
from wikirc.fetch import fetch

FIXTURE = Path(__file__).parent / "fixtures" / "metadata" / "doi_eval.json"
BOOK_FIXTURE = (
    Path(__file__).parent / "fixtures" / "metadata" / "book_eval.json"
)


def fetcher(url, *, getter, json_getter):
    """Resolve a DOI without ever touching the HTML getter.

    A DOI must be answered by Crossref alone. If the implementation falls back
    to the publisher page the harness getter would serve it, and the case fails
    on the result it produces instead of a Crossref title.
    """

    def html_getter(*args, **kwargs):
        raise AssertionError(f"HTML getter called for {url}")

    return fetch(url, getter=html_getter, json_getter=json_getter)


def book_fetcher(url, *, getter, json_getter):
    """Resolve a book page, HTML or archive.org, from the case payloads."""
    return fetch(url, getter=getter, json_getter=json_getter)


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


class LooksLikeBookUrlTests(unittest.TestCase):
    def test_known_bookseller_and_publisher_hosts(self):
        for url in (
            "https://www.amazon.com/dp/0000000000",
            "https://smile.amazon.co.uk/gp/product/0000000000",
            "https://www.penguinrandomhouse.com/books/000000/",
            "https://openlibrary.org/works/OL000000W",
        ):
            with self.subTest(url=url):
                self.assertTrue(books.looks_like_book_url(url))

    def test_a_books_path_counts_on_an_unknown_host(self):
        self.assertTrue(
            books.looks_like_book_url(
                "https://catalogue.example.org/books/salt-marsh-ledger"
            )
        )

    def test_lookalike_hosts_and_paths_do_not_count(self):
        for url in (
            "https://notamazon.example.com/dp/0000000000",
            "https://journal.example.com/essays/field-notes",
            "https://example.com/bookshelf/one",
            "https://example.com/notbooks/one",
        ):
            with self.subTest(url=url):
                self.assertFalse(books.looks_like_book_url(url))


class ValidIsbnsTests(unittest.TestCase):
    def test_hyphenated_isbn13_is_normalised(self):
        self.assertEqual(
            books.valid_isbns("ISBN 978-0-00-000001-9"),
            ["9780000000019"],
        )

    def test_spaced_isbn13_is_normalised(self):
        self.assertEqual(
            books.valid_isbns("ISBN 978 0 00 000001 9"),
            ["9780000000019"],
        )

    def test_hyphenated_isbn10_is_normalised(self):
        self.assertEqual(
            books.valid_isbns("ISBN 0-000-00001-9"),
            ["0000000019"],
        )

    def test_isbn10_with_x_check_digit_is_accepted(self):
        self.assertEqual(
            books.valid_isbns("ISBN 0-000-00006-X"),
            ["000000006X"],
        )

    def test_invalid_checksums_are_rejected(self):
        self.assertEqual(
            books.valid_isbns("ISBN 978-0-00-000003-4"),
            [],
        )
        self.assertEqual(
            books.valid_isbns("ISBN 0-000-00002-9"),
            [],
        )

    def test_isbn13s_come_before_isbn10s(self):
        text = "first 0-000-00001-9 then 978-0-00-000001-9"

        self.assertEqual(
            books.valid_isbns(text),
            ["9780000000019", "0000000019"],
        )

    def test_duplicates_are_removed_in_order(self):
        text = "978-0-00-000001-9 / 9780000000019 / 0-000-00001-9"

        self.assertEqual(
            books.valid_isbns(text),
            ["9780000000019", "0000000019"],
        )


if __name__ == "__main__":
    unittest.main()
