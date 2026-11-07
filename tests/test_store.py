import dataclasses
import json
import math
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from wikirc import store
from wikirc.corpus import Page
from wikirc.score import Document, Query, rank
from wikirc.text import tokenize

FIXTURES = Path(__file__).parent / "fixtures" / "corpus"


def _page(
    id="topics/soil.md",
    wiki="garden",
    label="Soil Care",
    subject=None,
    local=Path("notes") / "garden" / "topics" / "soil.md",
    headings=("Mixing",),
    links=("https://example.com/compost",),
    text="## Mixing\n\nAdd compost in spring.\n",
) -> Page:
    return Page(
        id=id,
        wiki=wiki,
        label=label,
        subject=subject,
        local=local,
        headings=headings,
        links=links,
        text=text,
    )


class SummaryTests(unittest.TestCase):
    def test_first_non_heading_non_empty_line_is_stripped(self):
        text = "# Title\n\n\n## Section\n   The opening line.  \nLater line.\n"

        self.assertEqual(store.summary_of(text), "The opening line.")

    def test_summary_is_truncated_to_160_characters(self):
        line = "x" * 200

        summary = store.summary_of("# Title\n\n" + line + "\n")

        self.assertEqual(summary, "x" * 160)
        self.assertEqual(len(summary), 160)

    def test_headings_only_yield_an_empty_summary(self):
        self.assertEqual(store.summary_of("# One\n\n## Two\n"), "")

    def test_empty_text_yields_an_empty_summary(self):
        self.assertEqual(store.summary_of(""), "")


class DocumentTests(unittest.TestCase):
    def test_document_carries_page_fields_and_summary(self):
        page = _page()

        document = store.document_from_page(page)

        self.assertIsInstance(document, Document)
        self.assertEqual(document.id, "topics/soil.md")
        self.assertEqual(document.wiki, "garden")
        self.assertEqual(document.label, "Soil Care")
        self.assertIsNone(document.subject)
        self.assertEqual(document.headings, page.headings)
        self.assertEqual(document.links, page.links)
        self.assertEqual(document.text, page.text)
        self.assertEqual(document.summary, "Add compost in spring.")

    def test_document_keeps_full_text_in_memory(self):
        page = _page()

        document = store.document_from_page(page)

        self.assertEqual(document.text, page.text)
        self.assertIn("Add compost in spring.", document.text)

    def test_terms_cover_label_headings_and_body(self):
        page = _page()

        document = store.document_from_page(page)

        expected = tokenize(
            " ".join([page.label, *page.headings, page.text])
        )
        self.assertEqual(document.terms, expected)
        for term in ("soil", "care", "mix", "compost", "add"):
            self.assertIn(term, document.terms)

    def test_wiki_comes_from_the_page_field(self):
        page = _page(
            wiki="field notes",
            local=Path("notes") / "garden" / "topics" / "soil.md",
        )

        self.assertEqual(store.document_from_page(page).wiki, "field notes")


class BuildTests(unittest.TestCase):
    def test_toy_corpus_yields_both_wikis_sorted(self):
        payload = store.build(FIXTURES, None)

        self.assertEqual(
            [(document.wiki, document.id) for document in payload.documents],
            [
                ("cycling", "commute.md"),
                ("cycling", "maintenance.md"),
                ("garden", "Pruning tomatoes.md"),
                ("garden", "folder-only.md"),
                ("garden", "topics/soil.md"),
                ("garden", "topics/solar.md"),
                ("garden", "watering.md"),
            ],
        )
        self.assertEqual(payload.pages, len(payload.documents))

    def test_payload_metadata(self):
        payload = store.build(FIXTURES, None)

        self.assertEqual(payload.version, 2)
        parsed = datetime.fromisoformat(payload.generated)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(len(payload.fingerprint), 64)
        int(payload.fingerprint, 16)
        self.assertEqual(payload.notes, str(FIXTURES))

    def test_pod_base_reaches_the_subjects(self):
        payload = store.build(FIXTURES, "https://pod.example.com/pod/notes")

        subjects = [
            document.subject for document in payload.documents
        ]
        self.assertTrue(all(subject is not None for subject in subjects))


class WriteLoadTests(unittest.TestCase):
    def test_write_creates_nested_state_and_leaves_no_temp_file(self):
        payload = store.build(FIXTURES, None)

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "nested" / "state"

            path = store.write(payload, state)

            self.assertEqual(path, state / "index.json")
            self.assertTrue(path.is_file())
            self.assertEqual(
                sorted(entry.name for entry in state.iterdir()),
                ["index.json"],
            )
            self.assertEqual(list(state.rglob("*.tmp")), [])

    def test_load_round_trips_the_payload(self):
        payload = store.build(FIXTURES, "https://pod.example.com/pod/notes")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            store.write(payload, state)

            loaded = store.load(state)

        self.assertEqual(loaded.version, payload.version)
        self.assertEqual(loaded.generated, payload.generated)
        self.assertEqual(loaded.notes, payload.notes)
        self.assertEqual(loaded.fingerprint, payload.fingerprint)
        self.assertEqual(loaded.pages, payload.pages)
        self.assertEqual(
            loaded.documents,
            tuple(
                dataclasses.replace(document, text="")
                for document in payload.documents
            ),
        )
        self.assertIsInstance(loaded.documents, tuple)
        self.assertIsInstance(loaded.documents[0], Document)
        self.assertIsInstance(loaded.documents[0].headings, tuple)
        self.assertIsInstance(loaded.documents[0].links, tuple)

    def test_loaded_documents_drop_the_full_text(self):
        payload = store.build(FIXTURES, None)
        self.assertTrue(all(document.text for document in payload.documents))

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            path = store.write(payload, state)

            serialised = json.loads(path.read_text(encoding="utf-8"))
            loaded = store.load(state)

        self.assertEqual(
            [document.text for document in loaded.documents], [""] * 7
        )
        self.assertTrue(
            all("text" not in item for item in serialised["documents"])
        )

    def test_load_without_an_index_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                store.load(Path(tmp) / "state")


class PrecomputationTests(unittest.TestCase):
    def test_every_document_carries_its_tf_idf_norm(self):
        payload = store.build(FIXTURES, None)
        total = len(payload.documents)
        frequencies: dict[str, int] = {}
        for document in payload.documents:
            for term in document.terms:
                frequencies[term] = frequencies.get(term, 0) + 1

        def idf(term):
            return math.log((total + 1) / (frequencies.get(term, 0) + 1)) + 1

        for document in payload.documents:
            expected = math.sqrt(
                sum(
                    ((1 + math.log(count)) * idf(term)) ** 2
                    for term, count in document.terms.items()
                    if count > 0
                )
            )
            self.assertGreater(document.norm, 0.0)
            self.assertAlmostEqual(document.norm, expected, places=12)

    def test_links_are_precomputed_into_sites_and_link_keys(self):
        payload = store.build(FIXTURES, None)
        watering = next(
            document
            for document in payload.documents
            if document.id == "watering.md"
        )

        self.assertEqual(watering.sites, ("pod.example.com",))
        self.assertEqual(
            watering.link_keys,
            (
                "https://pod.example.com/pod/notes/garden/seeds.md",
                "https://pod.example.com/pod/notes/garden/watering.md",
            ),
        )

    def test_sites_are_deduplicated_without_losing_order(self):
        page = _page(
            links=(
                "https://example.com/one",
                "https://www.example.com/two",
                "https://elsewhere.test/three",
            )
        )

        document = store.document_from_page(page)

        self.assertEqual(document.sites, ("example.com", "elsewhere.test"))
        self.assertEqual(len(document.link_keys), 3)


class ParityTests(unittest.TestCase):
    def test_rank_matches_when_the_precomputed_fields_are_stripped(self):
        payload = store.build(FIXTURES, None)
        prepared = list(payload.documents)
        stripped = [
            dataclasses.replace(document, norm=0.0, sites=(), link_keys=())
            for document in prepared
        ]
        queries = [
            Query(url="https://example.com/soil-compost/", title="soil compost"),
            Query(
                url="https://pod.example.com/pod/notes/garden/watering.md",
                title="Watering",
            ),
            Query(url="https://example.com/watering/", title="watering"),
            Query(url="https://example.com/cycle-commute/", title="cycle commute"),
            Query(url="https://example.com/", title="solar power panels"),
            Query(url="https://example.com/nothing-matches/"),
        ]

        for query in queries:
            with self.subTest(url=query.url):
                self.assertEqual(
                    rank(prepared, query, top=10),
                    rank(stripped, query, top=10),
                )


class StalenessTests(unittest.TestCase):
    def test_stale_when_the_index_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(store.is_stale(FIXTURES, None, Path(tmp) / "state"))

    def test_fresh_immediately_after_a_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            store.write(store.build(FIXTURES, None), state)

            self.assertFalse(store.is_stale(FIXTURES, None, state))

    def test_touching_a_page_makes_the_index_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes = Path(tmp) / "notes"
            shutil.copytree(FIXTURES, notes)
            state = Path(tmp) / "state"
            store.write(store.build(notes, None), state)
            self.assertFalse(store.is_stale(notes, None, state))

            page = notes / "garden" / "topics" / "soil.md"
            stamp = 1_700_000_000_000_000_000
            os.utime(page, ns=(stamp, stamp))

            self.assertTrue(store.is_stale(notes, None, state))

    def test_moving_the_notes_tree_keeps_the_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "original"
            moved = Path(tmp) / "moved"
            shutil.copytree(FIXTURES, original)

            before = store.fingerprint(original, None)
            original.rename(moved)
            after = store.fingerprint(moved, None)

        self.assertEqual(before, after)

    def test_an_index_written_by_a_previous_version_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            with mock.patch.object(store, "INDEX_VERSION", 1):
                store.write(store.build(FIXTURES, None), state)

            self.assertTrue(store.is_stale(FIXTURES, None, state))

    def test_unreadable_index_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            (state / "index.json").write_text("{not json", encoding="utf-8")

            self.assertTrue(store.is_stale(FIXTURES, None, state))


if __name__ == "__main__":
    unittest.main()
