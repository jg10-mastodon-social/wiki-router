import tempfile
import unittest
from pathlib import Path

from wikirc.priority import Priority, load_priority, order_candidates
from wikirc.score import Candidate


def candidate(page_id: str, wiki: str, score: float) -> Candidate:
    return Candidate(
        id=page_id,
        wiki=wiki,
        label=page_id,
        subject=None,
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
    def test_reads_last_and_defaults_the_margin(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "priority.json"
            path.write_text('{"last": ["notes"]}', encoding="utf-8")
            loaded = load_priority(path)
        self.assertEqual(loaded.last, ("notes",))
        self.assertEqual(loaded.within, 0.05)

    def test_reads_an_explicit_margin(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "priority.json"
            path.write_text('{"last": ["notes"], "within": 0.1}', encoding="utf-8")
            self.assertEqual(load_priority(path).within, 0.1)

    def test_missing_file_means_no_policy(self):
        self.assertEqual(load_priority(None), Priority())
        self.assertEqual(load_priority(Path("/nonexistent/priority.json")), Priority())

    def test_malformed_file_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "priority.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_priority(path)

    def test_last_and_within_are_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "priority.json"
            for body in (
                '{"last": "notes"}',
                '{"last": ["notes", 3]}',
                '{"last": ["notes"], "within": "near"}',
                '{"last": ["notes"], "within": -1}',
            ):
                path.write_text(body, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_priority(path)


class OrderingTests(unittest.TestCase):
    def test_a_clear_lead_is_not_displaced(self):
        rows = [candidate("wt.md", "notes", 0.30), candidate("other.md", "alpha", 0.10)]
        ordered = order_candidates(rows, ("notes",))
        self.assertEqual([r.id for r in ordered], ["wt.md", "other.md"])
        self.assertFalse(ordered[0].tiebreak)

    def test_a_close_runner_up_displaces_the_demoted_wiki(self):
        rows = [candidate("wt.md", "notes", 0.304), candidate("other.md", "alpha", 0.302)]
        ordered = order_candidates(rows, ("notes",))
        self.assertEqual([r.id for r in ordered], ["other.md", "wt.md"])
        self.assertTrue(ordered[1].tiebreak)

    def test_the_margin_is_configurable(self):
        rows = [candidate("wt.md", "notes", 0.304), candidate("other.md", "alpha", 0.290)]
        self.assertEqual(
            [r.id for r in order_candidates(rows, ("notes",), within=0.05)],
            ["other.md", "wt.md"],
        )
        self.assertEqual(
            [r.id for r in order_candidates(rows, ("notes",), within=0.01)],
            ["wt.md", "other.md"],
        )

    def test_only_the_top_slot_is_reconsidered(self):
        rows = [
            candidate("other.md", "alpha", 0.40),
            candidate("wt1.md", "notes", 0.30),
            candidate("wt2.md", "notes", 0.29),
        ]
        ordered = order_candidates(rows, ("notes",), within=0.2)
        self.assertEqual([r.id for r in ordered], ["other.md", "wt1.md", "wt2.md"])

    def test_no_other_wiki_leaves_order_alone(self):
        rows = [candidate("a.md", "notes", 0.30), candidate("b.md", "notes", 0.29)]
        ordered = order_candidates(rows, ("notes",))
        self.assertEqual([r.id for r in ordered], ["a.md", "b.md"])

    def test_no_priority_keeps_score_order(self):
        rows = [candidate("b.md", "zeta", 0.2), candidate("a.md", "alpha", 0.1)]
        ordered = order_candidates(rows)
        self.assertEqual([r.id for r in ordered], ["b.md", "a.md"])

    def test_order_is_independent_of_input_order(self):
        rows = [
            candidate("wt.md", "notes", 0.304),
            candidate("other.md", "alpha", 0.302),
            candidate("third.md", "beta", 0.100),
        ]
        forward = [r.id for r in order_candidates(rows, ("notes",))]
        backward = [r.id for r in order_candidates(list(reversed(rows)), ("notes",))]
        self.assertEqual(forward, backward)

    def test_identical_scores_break_by_id(self):
        rows = [candidate("b.md", "alpha", 0.2), candidate("a.md", "alpha", 0.2)]
        ordered = order_candidates(rows, ("notes",))
        self.assertEqual([r.id for r in ordered], ["a.md", "b.md"])


if __name__ == "__main__":
    unittest.main()
