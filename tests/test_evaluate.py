import json
import tempfile
import unittest
from pathlib import Path

from wikirc import store
from wikirc.evaluate import Case, evaluate, load_cases
from wikirc.score import Document
from wikirc.text import tokenize

FIXTURES = Path(__file__).parent / "fixtures"


def make_document(id, label, terms):
    return Document(
        id=id,
        wiki="w",
        label=label,
        subject=None,
        terms=tokenize(terms) if isinstance(terms, str) else terms,
        headings=(),
        links=(),
        text="",
    )


def documents():
    return [
        make_document("a.md", "First", {"alpha": 3}),
        make_document("b.md", "Second", {"alpha": 1}),
        make_document("c.md", "Third", {"gamma": 1}),
    ]


class LoadCasesTests(unittest.TestCase):
    def _write(self, directory, data):
        path = Path(directory) / "eval.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_parses_required_fields_and_defaults_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                {
                    "cases": [
                        {
                            "url": "https://example.com/a/",
                            "title": "A",
                            "acceptable": ["a.md", "b.md"],
                        },
                        {
                            "url": "https://example.com/b/",
                            "acceptable": ["b.md"],
                        },
                    ]
                },
            )
            cases = load_cases(path)

        self.assertEqual(
            cases,
            [
                Case(
                    url="https://example.com/a/",
                    title="A",
                    acceptable=("a.md", "b.md"),
                ),
                Case(
                    url="https://example.com/b/",
                    title="",
                    acceptable=("b.md",),
                ),
            ],
        )
        self.assertEqual(cases[0].description, "")
        self.assertEqual(cases[0].context, "")
        self.assertEqual(cases[0].note, "")

    def test_ignores_a_comment_and_accepts_a_bare_list(self):
        entry = {
            "url": "https://example.com/a/",
            "title": "A",
            "acceptable": ["a.md"],
        }
        expected = [
            Case(
                url="https://example.com/a/",
                title="A",
                acceptable=("a.md",),
            )
        ]

        with tempfile.TemporaryDirectory() as tmp:
            wrapped_path = Path(tmp) / "wrapped"
            bare_path = Path(tmp) / "bare"
            wrapped_path.mkdir()
            bare_path.mkdir()
            wrapped = self._write(
                wrapped_path,
                {"_comment": "free text, ignored", "cases": [entry]},
            )
            bare = self._write(bare_path, [entry])

            self.assertEqual(load_cases(wrapped), expected)
            self.assertEqual(load_cases(bare), expected)

    def test_missing_url_names_the_case_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                {
                    "cases": [
                        {
                            "url": "https://example.com/a/",
                            "title": "A",
                            "acceptable": ["a.md"],
                        },
                        {"title": "No URL", "acceptable": ["a.md"]},
                    ]
                },
            )
            with self.assertRaisesRegex(ValueError, r"\b1\b"):
                load_cases(path)

    def test_missing_acceptable_names_the_case_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                {"cases": [{"url": "https://example.com/a/", "title": "A"}]},
            )
            with self.assertRaisesRegex(ValueError, r"\b0\b"):
                load_cases(path)


class EvaluateTests(unittest.TestCase):
    def test_counts_hits_at_one_and_at_top(self):
        cases = [
            Case(
                url="https://example.com/alpha/",
                title="",
                acceptable=("a.md",),
            ),
            Case(
                url="https://example.com/alpha/",
                title="",
                acceptable=("b.md",),
            ),
        ]

        result = evaluate(documents(), cases)

        self.assertEqual([case["rank"] for case in result["cases"]], [1, 2])
        self.assertEqual(result["hit_at_1"], 1)
        self.assertEqual(result["hit_at_top"], 2)

    def test_any_acceptable_id_counts(self):
        cases = [
            Case(
                url="https://example.com/alpha/",
                title="",
                acceptable=("b.md", "a.md"),
            )
        ]

        result = evaluate(documents(), cases)

        self.assertEqual(result["cases"][0]["rank"], 1)
        self.assertEqual(result["hit_at_1"], 1)

    def test_a_zero_score_candidate_is_not_a_hit(self):
        cases = [
            Case(
                url="https://example.com/zzz/",
                title="",
                acceptable=("a.md",),
            )
        ]

        result = evaluate(documents(), cases)

        self.assertEqual(result["cases"][0]["top"][0], "w/a.md")
        self.assertEqual(result["cases"][0]["rank"], 0)
        self.assertEqual(result["hit_at_1"], 0)
        self.assertEqual(result["hit_at_top"], 0)

    def test_payload_has_exactly_the_documented_keys(self):
        cases = [
            Case(
                url="https://example.com/alpha/",
                title="",
                acceptable=("a.md",),
            )
        ]

        payload = evaluate(documents(), cases)

        self.assertEqual(
            list(payload),
            ["pages", "total", "top", "hit_at_1", "hit_at_top", "cases"],
        )
        self.assertEqual(
            list(payload["cases"][0]),
            ["url", "expected", "rank", "top", "note"],
        )
        self.assertEqual(payload["pages"], 3)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["top"], 5)


class CommittedFixtureTests(unittest.TestCase):
    def test_the_committed_fixture_scores_every_case_at_top_five(self):
        documents_ = store.build(FIXTURES / "corpus", None).documents
        cases = load_cases(FIXTURES / "eval.json")

        result = evaluate(documents_, cases, top=5)

        self.assertEqual(result["pages"], 7)
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["hit_at_1"], 5)
        self.assertEqual(result["hit_at_top"], 5)
        self.assertEqual(
            [case["rank"] for case in result["cases"]], [1, 1, 1, 1, 1]
        )


if __name__ == "__main__":
    unittest.main()
