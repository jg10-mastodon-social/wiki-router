import json
import tempfile
import unittest
from pathlib import Path

from wikirc.synonyms import expand, load_synonyms


class LoadTests(unittest.TestCase):
    def test_reads_a_map_and_casefolds_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synonyms.json"
            path.write_text('{"Foresight": "Futures"}', encoding="utf-8")
            self.assertEqual(load_synonyms(path), {"foresight": "futures"})

    def test_missing_file_means_no_expansion(self):
        self.assertEqual(load_synonyms(None), {})
        self.assertEqual(load_synonyms(Path("/nonexistent/synonyms.json")), {})

    def test_malformed_maps_fail_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synonyms.json"
            for body in ('{not json', "[]", '{"a": 3}', '{"": "x"}', '{"a": " "}'):
                path.write_text(body, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_synonyms(path)


class ExpandTests(unittest.TestCase):
    def test_a_word_is_expanded_case_insensitively(self):
        out = expand("A generic Foresight process framework", {"foresight": "futures"})
        self.assertTrue(out.startswith("A generic Foresight process framework"))
        self.assertIn("futures", out)

    def test_a_phrase_is_expanded(self):
        out = expand("Causal layered analysis", {"causal layered analysis": "futures"})
        self.assertIn("futures", out)

    def test_the_longest_phrase_wins(self):
        synonyms = {"causal layered": "methods", "causal layered analysis": "futures"}
        out = expand("causal layered analysis", synonyms)
        self.assertIn("futures", out)
        self.assertNotIn("methods", out)

    def test_expansion_needs_a_word_boundary(self):
        out = expand("foresightedness", {"foresight": "futures"})
        self.assertEqual(out, "foresightedness")

    def test_no_match_leaves_the_text_alone(self):
        self.assertEqual(expand("nothing here", {"foresight": "futures"}), "nothing here")

    def test_replacements_are_deduplicated(self):
        out = expand("foresight and futurology", {"foresight": "futures", "futurology": "futures"})
        self.assertEqual(out.count("futures"), 1)
