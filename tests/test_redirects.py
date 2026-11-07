import json
import tempfile
import unittest
from pathlib import Path

from wikirc.evaluate import Case, evaluate
from wikirc.fetch import FetchResult
from wikirc.redirects import apply_redirects, load_redirects
from wikirc.router import route_payload
from wikirc.score import Candidate, Document, rank, Query
from wikirc.text import tokenize


def document(wiki: str, page_id: str, text: str) -> Document:
    return Document(
        id=page_id,
        wiki=wiki,
        label=page_id,
        subject=None,
        terms=tokenize(text),
        headings=(),
        links=(),
        text="",
        summary="",
    )


def candidate(row: Document, score: float = 0.5) -> Candidate:
    return Candidate(
        id=row.id,
        wiki=row.wiki,
        label=row.label,
        subject=row.subject,
        score=score,
        cosine=score,
        boosts={},
        matched=(),
        already_linked=False,
        heading_match=False,
        suggested_section=None,
        headings=(),
        summary="",
    )


class LoadTests(unittest.TestCase):
    def test_reads_a_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "redirects.json"
            path.write_text('{"notes/a.md": "topics/a.md"}', encoding="utf-8")
            self.assertEqual(load_redirects(path), {"notes/a.md": "topics/a.md"})

    def test_missing_file_means_no_redirects(self):
        self.assertEqual(load_redirects(None), {})
        self.assertEqual(load_redirects(Path("/nonexistent/redirects.json")), {})

    def test_malformed_values_fail_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "redirects.json"
            for body in ('{not json', '[]', '{"notes/a.md": 3}', '{"a": "topics/a.md"}'):
                path.write_text(body, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_redirects(path)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.source = document("notes", "a.md", "alpha beta")
        self.target = document("topics", "a.md", "gamma delta")
        self.other = document("topics", "b.md", "epsilon")
        self.by_key = {
            "notes/a.md": self.source,
            "topics/a.md": self.target,
            "topics/b.md": self.other,
        }

    def test_a_source_is_replaced_by_its_target(self):
        rows = apply_redirects(
            [candidate(self.source, 0.5)], {"notes/a.md": "topics/a.md"}, self.by_key
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].wiki, rows[0].id), ("topics", "a.md"))
        self.assertEqual(rows[0].score, 0.5)
        self.assertTrue(rows[0].redirected)
        self.assertEqual(rows[0].redirected_from, "notes/a.md")

    def test_the_higher_score_survives_deduplication(self):
        rows = apply_redirects(
            [candidate(self.source, 0.5), candidate(self.target, 0.4)],
            {"notes/a.md": "topics/a.md"},
            self.by_key,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].score, 0.5)
        self.assertTrue(rows[0].redirected)

    def test_a_target_that_already_leads_is_left_alone(self):
        rows = apply_redirects(
            [candidate(self.target, 0.6), candidate(self.source, 0.5)],
            {"notes/a.md": "topics/a.md"},
            self.by_key,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].score, 0.6)
        self.assertFalse(rows[0].redirected)

    def test_a_missing_target_leaves_the_source(self):
        rows = apply_redirects(
            [candidate(self.source, 0.5)], {"notes/a.md": "topics/absent.md"}, self.by_key
        )
        self.assertEqual((rows[0].wiki, rows[0].id), ("notes", "a.md"))
        self.assertFalse(rows[0].redirected)

    def test_unrelated_candidates_are_untouched(self):
        rows = apply_redirects(
            [candidate(self.other, 0.3)], {"notes/a.md": "topics/a.md"}, self.by_key
        )
        self.assertEqual((rows[0].wiki, rows[0].id), ("topics", "b.md"))
        self.assertFalse(rows[0].redirected)


class RouterTests(unittest.TestCase):
    def test_payload_reports_the_redirect(self):
        source = document("notes", "a.md", "alpha beta")
        target = document("topics", "a.md", "gamma delta")
        payload = route_payload(
            [source, target],
            "https://example.com/alpha/",
            fetched=FetchResult.disabled("https://example.com/alpha/"),
            redirects={"notes/a.md": "topics/a.md"},
        )
        first = payload["candidates"][0]
        self.assertEqual((first["wiki"], first["id"]), ("topics", "a.md"))
        self.assertTrue(first["redirected"])
        self.assertEqual(first["redirectedFrom"], "notes/a.md")


class EvalTests(unittest.TestCase):
    def test_a_redirect_turns_a_miss_into_a_hit(self):
        source = document("notes", "a.md", "alpha beta")
        target = document("topics", "a.md", "gamma")
        case = Case(url="https://example.com/alpha/", title="alpha beta",
                    acceptable=("topics/a.md",))

        before = evaluate([source, target], [case], top=5)
        after = evaluate([source, target], [case], top=5,
                         redirects={"notes/a.md": "topics/a.md"})

        self.assertEqual(before["hit_at_1"], 0)
        self.assertEqual(after["hit_at_1"], 1)


if __name__ == "__main__":
    unittest.main()
