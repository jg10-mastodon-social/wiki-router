import json
import unittest

from wikirc import CONTRACT
from wikirc.router import fetched_block, route_payload
from wikirc.score import Document, Query, rank
from wikirc.text import tokenize

PAYLOAD_KEYS = [
    "contract",
    "url",
    "final_url",
    "fetched",
    "reliability",
    "candidates",
]
FETCHED_KEYS = [
    "ok",
    "title",
    "description",
    "source",
    "creator",
    "date",
    "isbn",
    "canonical",
    "title_noisy",
    "error",
]
CANDIDATE_KEYS = [
    "id",
    "wiki",
    "label",
    "subject",
    "score",
    "cosine",
    "boosts",
    "matched",
    "already_linked",
    "heading_match",
    "suggested_section",
    "headings",
    "summary",
]


def make_document(
    id="topics/soil.md",
    wiki="garden",
    label="Soil care",
    subject=None,
    terms=None,
    headings=("Mixing",),
    links=(),
    summary="Add compost in spring.",
):
    return Document(
        id=id,
        wiki=wiki,
        label=label,
        subject=subject,
        terms=tokenize("soil care compost mix", bigrams=False)
        if terms is None
        else terms,
        headings=headings,
        links=links,
        text="",
        summary=summary,
    )


def documents():
    return [
        make_document(),
        make_document(
            id="topics/solar.md",
            label="Solar",
            terms=tokenize("solar panel", bigrams=False),
            headings=("Panels",),
            summary="Panel notes.",
        ),
        make_document(
            id="commute.md",
            wiki="cycling",
            label="Commute",
            terms=tokenize("commute riverside route", bigrams=False),
            headings=(),
            summary="The riverside route is quiet.",
        ),
    ]


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


class FetchedBlockTests(unittest.TestCase):
    def test_defaults_describe_a_fetch_that_did_not_happen(self):
        block = fetched_block("https://example.com/watering/")

        self.assertEqual(list(block), FETCHED_KEYS)
        self.assertFalse(block["ok"])
        self.assertEqual(block["description"], "")
        self.assertEqual(block["source"], "")
        self.assertEqual(block["creator"], "")
        self.assertEqual(block["date"], "")
        self.assertEqual(block["isbn"], "")
        self.assertEqual(block["canonical"], "")
        self.assertFalse(block["title_noisy"])
        self.assertEqual(block["error"], "")

    def test_supplied_title_is_used_as_is(self):
        block = fetched_block(
            "https://example.com/watering/", title="Watering"
        )

        self.assertEqual(block["title"], "Watering")

    def test_description_and_error_pass_through(self):
        block = fetched_block(
            "https://example.com/watering/",
            description="A note",
            error="fetch disabled",
        )

        self.assertEqual(block["description"], "A note")
        self.assertEqual(block["error"], "fetch disabled")

    def test_missing_title_falls_back_to_the_slug_text(self):
        block = fetched_block(
            "https://example.com/canal-solar-power-project/"
        )

        self.assertEqual(block["title"], "canal solar power project")

    def test_slug_title_decodes_and_replaces_separators(self):
        block = fetched_block("https://example.com/my_page%20notes.html")

        self.assertEqual(block["title"], "my page notes html")

    def test_title_is_never_empty(self):
        block = fetched_block("https://example.com/")

        self.assertTrue(block["title"])


class PayloadShapeTests(unittest.TestCase):
    def test_payload_has_exactly_the_documented_keys(self):
        payload = route_payload(documents(), "https://example.com/soil/")

        self.assertEqual(list(payload), PAYLOAD_KEYS)
        self.assertEqual(list(payload["fetched"]), FETCHED_KEYS)
        self.assertEqual(payload["contract"], CONTRACT)
        self.assertEqual(CONTRACT, 1)

    def test_url_and_final_url_are_the_input_url(self):
        payload = route_payload(documents(), "https://example.com/soil/")

        self.assertEqual(payload["url"], "https://example.com/soil/")
        self.assertEqual(payload["final_url"], "https://example.com/soil/")

    def test_payload_serialises_without_a_local_key(self):
        payload = route_payload(documents(), "https://example.com/soil/")

        encoded = json.dumps(payload)

        self.assertNotIn('"local"', encoded)
        self.assertEqual(set(_keys(payload)) & {"local", "local_path"}, set())


class ReliabilityTests(unittest.TestCase):
    def test_no_fetch_is_low_reliability(self):
        payload = route_payload(documents(), "https://example.com/soil/")
        self.assertFalse(payload["fetched"]["ok"])
        self.assertEqual(payload["reliability"], "low")

    def test_no_fetch_error_passes_through(self):
        payload = route_payload(
            documents(),
            "https://example.com/soil/",
            fetch_error="fetch disabled",
        )
        self.assertEqual(payload["fetched"]["error"], "fetch disabled")

    def test_supplied_title_with_fetch_is_ok(self):
        payload = route_payload(
            documents(),
            "https://example.com/soil/",
            title="Soil care",
            fetch_ok=True,
        )

        self.assertTrue(payload["fetched"]["ok"])
        self.assertEqual(payload["fetched"]["title"], "Soil care")
        self.assertEqual(payload["reliability"], "ok")


class CandidateTests(unittest.TestCase):
    def test_candidates_carry_headings_and_summary(self):
        payload = route_payload(documents(), "https://example.com/soil/")

        candidate = payload["candidates"][0]

        self.assertEqual(list(candidate), CANDIDATE_KEYS)
        self.assertEqual(candidate["headings"], ["Mixing"])
        self.assertEqual(candidate["summary"], "Add compost in spring.")

    def test_top_truncates_the_candidate_list(self):
        corpus = [
            make_document(id="a"),
            make_document(
                id="b",
                label="Soil notes",
                terms=tokenize("soil notes", bigrams=False),
            ),
            make_document(
                id="c",
                label="Solar",
                terms=tokenize("solar", bigrams=False),
            ),
        ]

        payload = route_payload(corpus, "https://example.com/soil/", top=1)

        self.assertEqual(len(payload["candidates"]), 1)

    def test_zero_score_candidates_are_dropped_but_rank_keeps_them(self):
        payload = route_payload(documents(), "https://example.com/soil/")

        self.assertEqual(
            [candidate["id"] for candidate in payload["candidates"]],
            ["topics/soil.md"],
        )
        self.assertEqual(
            len(rank(documents(), Query(url="https://example.com/soil/"))),
            3,
        )

    def test_no_match_yields_an_empty_candidate_list(self):
        payload = route_payload(
            documents(), "https://example.com/unknown-topic/"
        )

        self.assertEqual(payload["candidates"], [])

    def test_wiki_filters_before_ranking(self):
        payload = route_payload(
            documents(), "https://example.com/commute/", wiki="cycling"
        )

        self.assertEqual(
            [candidate["wiki"] for candidate in payload["candidates"]],
            ["cycling"],
        )

    def test_exclude_wiki_drops_one_wiki(self):
        payload = route_payload(
            documents(),
            "https://example.com/commute/",
            exclude_wiki="garden",
        )

        self.assertEqual(
            [candidate["wiki"] for candidate in payload["candidates"]],
            ["cycling"],
        )


if __name__ == "__main__":
    unittest.main()
