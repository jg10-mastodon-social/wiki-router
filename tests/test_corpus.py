import tempfile
import unittest
from pathlib import Path

from wikirc.corpus import Page, Wiki, discover_wikis, strip_urls
from wikirc.store import document_from_page

FIXTURES = Path(__file__).parent / "fixtures" / "corpus"
POD_BASE = "https://pod.example.com/pod/notes"
LABEL = "<http://www.w3.org/2000/01/rdf-schema#label>"


def _write_wiki(root: Path, name: str, index: str, files: dict[str, str]) -> Path:
    wiki = root / name
    wiki.mkdir(parents=True)
    (wiki / "label-index.ttl").write_text(index, encoding="utf-8")
    for relative, content in files.items():
        target = wiki / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return wiki


def _garden() -> Wiki:
    return next(wiki for wiki in discover_wikis(FIXTURES) if wiki.name == "garden")


def _page(wiki: Wiki, page_id: str) -> Page:
    return next(page for page in wiki.pages if page.id == page_id)


class DiscoveryTests(unittest.TestCase):
    def test_discovers_only_directories_with_a_label_index_sorted_by_name(self):
        wikis = discover_wikis(FIXTURES)

        self.assertEqual([wiki.name for wiki in wikis], ["cycling", "garden"])
        self.assertEqual(wikis[1].path, FIXTURES / "garden")
        self.assertEqual(
            [page.id for page in wikis[0].pages], ["commute.md", "maintenance.md"]
        )

    def test_pages_are_sorted_by_id(self):
        ids = [page.id for page in _garden().pages]

        self.assertEqual(
            ids,
            [
                "Pruning tomatoes.md",
                "folder-only.md",
                "topics/soil.md",
                "topics/solar.md",
                "watering.md",
            ],
        )

    def test_symlinked_wiki_directory_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real").mkdir()
            (root / "real" / "label-index.ttl").write_text("", encoding="utf-8")
            (root / "linked").symlink_to(root / "real", target_is_directory=True)

            wikis = discover_wikis(root)

        self.assertEqual([wiki.name for wiki in wikis], ["real"])


class ReferenceResolutionTests(unittest.TestCase):
    def test_percent_encoded_relative_ref_resolves_to_decoded_id(self):
        page = _page(_garden(), "Pruning tomatoes.md")

        self.assertEqual(page.local, FIXTURES / "garden" / "Pruning tomatoes.md")

    def test_leading_slash_is_stripped_from_relative_ref(self):
        page = _page(_garden(), "topics/soil.md")

        self.assertEqual(page.local, FIXTURES / "garden" / "topics" / "soil.md")

    def test_absolute_ref_resolves_after_the_last_wiki_segment(self):
        page = _page(_garden(), "topics/solar.md")

        self.assertEqual(page.local, FIXTURES / "garden" / "topics" / "solar.md")

    def test_absolute_ref_without_the_wiki_segment_is_skipped(self):
        self.assertTrue((FIXTURES / "garden" / "ghost.md").is_file())

        ids = [page.id for page in _garden().pages]

        self.assertNotIn("ghost.md", ids)

    def test_storage_suffix_resolves_with_logical_id(self):
        garden = FIXTURES / "garden"
        page = _page(_garden(), "watering.md")

        self.assertEqual(page.local, garden / "watering.md$.txt")
        self.assertTrue(page.local.is_file())
        self.assertFalse((garden / "watering.md").exists())

    def test_entry_whose_file_is_missing_is_skipped(self):
        self.assertFalse((FIXTURES / "garden" / "missing.md").exists())

        self.assertNotIn("missing.md", [page.id for page in _garden().pages])

    def test_file_without_a_label_entry_is_not_included(self):
        orphan = (FIXTURES / "garden" / "orphan.md").resolve()

        self.assertTrue(orphan.is_file())
        self.assertNotIn(orphan, [page.local.resolve() for page in _garden().pages])

    def test_entry_without_labels_is_skipped(self):
        self.assertTrue((FIXTURES / "garden" / "comment-only.md").is_file())

        self.assertNotIn("comment-only.md", [page.id for page in _garden().pages])

    def test_label_prefers_first_label_not_starting_with_a_slash(self):
        self.assertEqual(
            _page(_garden(), "Pruning tomatoes.md").label, "Pruning Tomatoes"
        )

    def test_slash_only_labels_use_the_first(self):
        self.assertEqual(_page(_garden(), "folder-only.md").label, "/Only Folder")


class SubjectTests(unittest.TestCase):
    def test_subject_is_none_without_a_pod_base(self):
        subjects = [
            page.subject
            for wiki in discover_wikis(FIXTURES)
            for page in wiki.pages
        ]

        self.assertTrue(all(subject is None for subject in subjects))

    def test_subject_is_percent_encoded_with_a_pod_base(self):
        garden = _garden_with_pod_base()

        self.assertEqual(
            _page(garden, "Pruning tomatoes.md").subject,
            POD_BASE + "/garden/Pruning%20tomatoes.md",
        )
        self.assertEqual(
            _page(garden, "topics/soil.md").subject,
            POD_BASE + "/garden/topics/soil.md",
        )

    def test_subject_encodes_the_wiki_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_wiki(
                root,
                "field notes",
                f'<page.md> {LABEL} "Page" .\n',
                {"page.md": "# Page\n"},
            )

            wikis = discover_wikis(root, pod_base=POD_BASE)

        self.assertEqual(
            wikis[0].pages[0].subject, POD_BASE + "/field%20notes/page.md"
        )


class PageContentTests(unittest.TestCase):
    def test_headings_are_extracted_in_file_order(self):
        page = _page(_garden(), "watering.md")

        self.assertEqual(
            page.headings,
            ("Watering", "Watering", "Deep bed", "Fine print", "Detail", "Last"),
        )

    def test_absolute_links_are_deduplicated_in_order(self):
        page = _page(_garden(), "watering.md")

        self.assertEqual(
            page.links,
            (
                "https://pod.example.com/pod/notes/garden/seeds.md",
                "https://pod.example.com/pod/notes/garden/watering.md",
            ),
        )

    def test_bare_urls_drop_trailing_sentence_punctuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "See https://example.com/page. and https://example.com/list,\n"
            _write_wiki(
                root,
                "punctuation",
                f'<punctuation.md> {LABEL} "Punctuation" .\n',
                {"punctuation.md": body},
            )

            page = discover_wikis(root)[0].pages[0]

        self.assertEqual(
            page.links,
            ("https://example.com/page", "https://example.com/list"),
        )

    def test_file_with_invalid_utf8_is_skipped_without_aborting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wiki = _write_wiki(
                root,
                "mixed",
                f'<binary.md> {LABEL} "Binary" .\n'
                f'<text.md> {LABEL} "Text" .\n',
                {"text.md": "# Text\n"},
            )
            (wiki / "binary.md").write_bytes(b"\xff\xfe\x00broken")

            pages = discover_wikis(root)[0].pages

        self.assertEqual([page.id for page in pages], ["text.md"])

    def test_text_is_the_raw_file_content(self):
        source = (FIXTURES / "garden" / "watering.md$.txt").read_text(encoding="utf-8")

        self.assertEqual(_page(_garden(), "watering.md").text, source)

    def test_text_is_truncated_to_twenty_thousand_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "# Big\n" + "x" * 25000
            _write_wiki(
                root, "big", f'<big.md> {LABEL} "Big" .\n', {"big.md": body}
            )

            page = discover_wikis(root)[0].pages[0]

        self.assertEqual(len(page.text), 20000)
        self.assertEqual(page.text, body[:20000])


class PageWikiTests(unittest.TestCase):
    def test_pages_carry_their_wiki_directory_name(self):
        wikis = discover_wikis(FIXTURES)

        for wiki in wikis:
            for page in wiki.pages:
                self.assertEqual(page.wiki, wiki.name)

    def test_nested_page_carries_its_wiki_directory_name(self):
        page = _page(_garden(), "topics/soil.md")

        self.assertEqual(page.wiki, "garden")


class SizeCapTests(unittest.TestCase):
    def test_file_over_the_size_cap_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_wiki(
                root,
                "huge",
                f'<small.md> {LABEL} "Small" .\n<huge.md> {LABEL} "Huge" .\n',
                {"small.md": "# Small\n", "huge.md": "x" * 200001},
            )

            wiki = discover_wikis(root)[0]

        self.assertEqual([page.id for page in wiki.pages], ["small.md"])

    def test_file_at_the_size_cap_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_wiki(
                root,
                "edge",
                f'<edge.md> {LABEL} "Edge" .\n',
                {"edge.md": "x" * 200000},
            )

            page = discover_wikis(root)[0].pages[0]

        self.assertEqual(len(page.text), 20000)


def _garden_with_pod_base() -> Wiki:
    return next(
        wiki
        for wiki in discover_wikis(FIXTURES, pod_base=POD_BASE)
        if wiki.name == "garden"
    )


if __name__ == "__main__":
    unittest.main()


class StripUrlTests(unittest.TestCase):
    def test_anchor_text_is_kept_and_the_target_dropped(self):
        text = "- [Causal layered analysis](https://en.wikipedia.org/wiki/Causal_layered_analysis)\n"
        cleaned = strip_urls(text)
        self.assertIn("Causal layered analysis", cleaned)
        self.assertNotIn("wikipedia.org", cleaned)

    def test_bare_urls_are_dropped(self):
        cleaned = strip_urls("See https://doi.org/10.1108/14636680310698379 for details")
        self.assertIn("See", cleaned)
        self.assertIn("for details", cleaned)
        self.assertNotIn("doi.org", cleaned)


class PageTermTests(unittest.TestCase):
    def test_url_fragments_are_not_indexed(self):
        page = Page(
            id="a.md", wiki="w", label="Alpha", subject=None,
            local=Path("/tmp/a.md"), headings=(),
            links=("https://doi.org/10.1234/x",),
            text="# Alpha\n\n- [Beta gamma](https://example.com/beta-gamma)\n",
        )
        document = document_from_page(page)
        self.assertIn("beta", document.terms)
        for noise in ("http", "https", "doi", "org", "1234"):
            self.assertNotIn(noise, document.terms)
