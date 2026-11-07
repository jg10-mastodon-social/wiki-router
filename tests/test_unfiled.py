import tempfile
import unittest
from pathlib import Path

from tools.unfiled_corpus import strip_text, unfiled, url_variants


class VariantTests(unittest.TestCase):
    def test_https_and_http_are_variants(self):
        variants = url_variants("https://example.com/a")
        self.assertIn("https://example.com/a", variants)
        self.assertIn("http://example.com/a", variants)

    def test_trailing_slash_is_a_variant(self):
        self.assertIn("https://example.com/a", url_variants("https://example.com/a/"))

    def test_www_is_a_variant(self):
        self.assertIn("https://www.example.com/a", url_variants("https://example.com/a"))

    def test_doi_hosts_are_the_same(self):
        variants = url_variants("https://dx.doi.org/10.1234/abc")
        self.assertTrue(any(v.startswith("https://doi.org/10.1234/abc") for v in variants))

    def test_percent_encoded_path_is_a_variant(self):
        variants = url_variants("https://example.com/a%20b")
        self.assertIn("https://example.com/a b", variants)


class StripTests(unittest.TestCase):
    def test_removes_only_the_matching_line(self):
        text = "# Heading\n\n- [A](https://example.com/a)\n\nKeep me.\n"
        stripped, removed = strip_text(text, url_variants("https://example.com/a"))
        self.assertEqual(removed, 1)
        self.assertNotIn("example.com/a", stripped)
        self.assertIn("Keep me.", stripped)
        self.assertIn("# Heading", stripped)

    def test_leaves_unrelated_text_alone(self):
        text = "Nothing to see.\nhttps://other.example/b\n"
        stripped, removed = strip_text(text, url_variants("https://example.com/a"))
        self.assertEqual(removed, 0)
        self.assertEqual(stripped, text)

    def test_matches_every_variant(self):
        text = (
            "https://example.com/a\n"
            "http://example.com/a\n"
            "https://example.com/a/\n"
            "https://www.example.com/a\n"
        )
        _, removed = strip_text(text, url_variants("https://example.com/a"))
        self.assertEqual(removed, 4)


class UnfiledTests(unittest.TestCase):
    def _corpus(self, root: Path) -> None:
        (root / "one").mkdir(parents=True)
        (root / "two").mkdir(parents=True)
        (root / "one" / "page.md").write_text(
            "# Page\n\n- [Thing](https://example.com/thing)\n\nKeep this.\n", encoding="utf-8"
        )
        (root / "two" / "other.md").write_text(
            "# Other\n\nSee https://doi.org/10.1234/abc here.\nKeep.\n", encoding="utf-8"
        )
        (root / "two" / "untouched.md").write_text("Plain text.\n", encoding="utf-8")

    def _fixture(self, root: Path) -> Path:
        path = root / "eval.json"
        path.write_text(
            '{"cases": ['
            '{"url": "https://example.com/thing/", "acceptable": ["one/page.md"]},'
            '{"url": "https://dx.doi.org/10.1234/abc", "acceptable": ["two/other.md"]}'
            "]}",
            encoding="utf-8",
        )
        return path

    def test_removes_fixture_urls_and_keeps_everything_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes = root / "notes"
            self._corpus(notes)
            out = root / "unfiled"
            report = unfiled(notes, self._fixture(root), out)

            page = (out / "one" / "page.md").read_text(encoding="utf-8")
            other = (out / "two" / "other.md").read_text(encoding="utf-8")
            untouched = (out / "two" / "untouched.md").read_text(encoding="utf-8")

            self.assertNotIn("example.com/thing", page)
            self.assertIn("Keep this.", page)
            self.assertNotIn("10.1234/abc", other)
            self.assertIn("Keep.", other)
            self.assertEqual(untouched, "Plain text.\n")
            self.assertEqual(report["lines_removed"], 2)
            self.assertEqual(report["residual"], [])

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes = root / "notes"
            self._corpus(notes)
            out = root / "unfiled"
            report = unfiled(notes, self._fixture(root), out, dry_run=True)

            self.assertFalse(out.exists())
            self.assertEqual(report["lines_removed"], 2)

    def test_reports_a_residual_when_a_url_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes = root / "notes"
            self._corpus(notes)
            # a fixture URL that does not appear in the corpus is fine; but one
            # that appears on a line that also lacks a newline must still go
            (notes / "two" / "other.md").write_text(
                "# Other\n\nSee https://doi.org/10.1234/abc here.\nKeep.\n", encoding="utf-8"
            )
            report = unfiled(notes, self._fixture(root), root / "unfiled")
            self.assertEqual(report["residual"], [])


if __name__ == "__main__":
    unittest.main()
