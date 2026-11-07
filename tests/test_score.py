import time
import unittest
from collections.abc import Sequence
from dataclasses import replace

from wikirc.score import (
    Document,
    Query,
    document_frequencies,
    document_norm,
    host_of,
    idf_of,
    normalise_url,
    rank,
    same_site,
)
from wikirc.text import tokenize


class CountingSequence(Sequence):
    """A document sequence that counts every element yielded or indexed."""

    def __init__(self, items):
        self._items = list(items)
        self.accesses = 0

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        for item in self._items:
            self.accesses += 1
            yield item

    def __getitem__(self, index):
        self.accesses += 1
        return self._items[index]


def make_document(
    id="page",
    wiki="garden",
    label="Page",
    subject=None,
    terms=None,
    headings=(),
    links=(),
    text="",
    summary="",
    norm=0.0,
    sites=(),
    link_keys=(),
):
    return Document(
        id=id,
        wiki=wiki,
        label=label,
        subject=subject,
        terms=tokenize("page", bigrams=False) if terms is None else terms,
        headings=headings,
        links=links,
        text=text,
        summary=summary,
        norm=norm,
        sites=sites,
        link_keys=link_keys,
    )


class SlugQueryTests(unittest.TestCase):
    def test_url_path_supplies_query_terms(self):
        document = make_document(
            terms=tokenize("solar power", bigrams=False)
        )
        query = Query(url="https://example.com/canal-solar-power-project/")

        candidates = rank([document], query)

        self.assertEqual(len(candidates), 1)
        self.assertIn("solar", candidates[0].matched)
        self.assertGreater(candidates[0].cosine, 0.0)


class LabelBoostTests(unittest.TestCase):
    def test_exact_label_outranks_body_only_overlap(self):
        exact = make_document(
            id="exact",
            label="Canal Solar Power Project",
            terms=tokenize("solar", bigrams=False),
        )
        body = make_document(
            id="body",
            label="Unrelated Archive",
            terms=tokenize("solar", bigrams=False),
        )
        query = Query(url="https://example.com/canal-solar-power-project/")

        candidates = rank([exact, body], query)

        self.assertEqual(candidates[0].id, "exact")
        self.assertEqual(candidates[0].boosts["label_exact"], 0.5)
        self.assertNotIn("label_exact", candidates[1].boosts)

    def test_label_most_fires_at_sixty_percent(self):
        document = make_document(
            label="Canal Solar Power Systems Guide",
            terms=tokenize("solar", bigrams=False),
        )
        query = Query(url="https://example.com/canal-solar-power/")

        candidate = rank([document], query)[0]

        self.assertEqual(candidate.boosts["label_most"], 0.15)
        self.assertNotIn("label_contains", candidate.boosts)
        self.assertNotIn("label_exact", candidate.boosts)

    def test_label_contains_fires_for_a_single_token(self):
        document = make_document(
            label="Solar Archive",
            terms=tokenize("solar", bigrams=False),
        )
        query = Query(url="https://example.com/solar/")

        candidate = rank([document], query)[0]

        self.assertEqual(candidate.boosts["label_contains"], 0.05)
        self.assertNotIn("label_exact", candidate.boosts)
        self.assertNotIn("label_most", candidate.boosts)

    def test_only_the_most_specific_label_boost_is_present(self):
        document = make_document(
            label="Canal Solar Power Project",
            terms=tokenize("solar", bigrams=False),
        )
        query = Query(url="https://example.com/canal-solar-power-project/")

        candidate = rank([document], query)[0]

        present = {
            "label_exact",
            "label_most",
            "label_contains",
        } & candidate.boosts.keys()
        self.assertEqual(present, {"label_exact"})


class LinkAndHeadingTests(unittest.TestCase):
    def test_same_domain_boost_ignores_www_prefix(self):
        document = make_document(
            label="Archive",
            terms=tokenize("solar", bigrams=False),
            links=("https://www.example.com/other",),
        )
        query = Query(url="https://example.com/solar/")

        candidate = rank([document], query)[0]

        self.assertEqual(candidate.boosts["same_domain"], 0.1)
        self.assertFalse(candidate.already_linked)

    def test_already_linked_is_a_flag_not_a_boost(self):
        document = make_document(
            label="Archive",
            terms=tokenize("solar", bigrams=False),
            links=("https://example.com/solar/#top",),
        )
        query = Query(url="https://example.com/solar/")

        candidate = rank([document], query)[0]

        self.assertTrue(candidate.already_linked)
        self.assertNotIn("already_linked", candidate.boosts)
        self.assertEqual(candidate.score, candidate.cosine)

    def test_heading_match_sets_flag_and_boost(self):
        document = make_document(
            label="Archive",
            terms=tokenize("solar", bigrams=False),
            headings=("Solar power",),
        )
        query = Query(url="https://example.com/solar/")

        candidate = rank([document], query)[0]

        self.assertTrue(candidate.heading_match)
        self.assertEqual(candidate.boosts["heading_match"], 0.05)
        self.assertEqual(candidate.suggested_section, "Solar power")


class SuggestedSectionTests(unittest.TestCase):
    def test_heading_with_most_overlap_wins(self):
        document = make_document(
            label="Archive",
            terms=tokenize("solar power", bigrams=False),
            headings=("Solar energy", "Solar power"),
        )
        query = Query(url="https://example.com/solar-power/")

        candidate = rank([document], query)[0]

        self.assertEqual(candidate.suggested_section, "Solar power")

    def test_ties_go_to_the_earliest_heading(self):
        document = make_document(
            label="Archive",
            terms=tokenize("solar", bigrams=False),
            headings=("Solar basics", "Solar guide"),
        )
        query = Query(url="https://example.com/solar/")

        candidate = rank([document], query)[0]

        self.assertEqual(candidate.suggested_section, "Solar basics")

    def test_no_overlap_suggests_nothing(self):
        document = make_document(
            label="Archive",
            terms=tokenize("water", bigrams=False),
            headings=("Watering",),
        )
        query = Query(url="https://example.com/solar/")

        candidate = rank([document], query)[0]

        self.assertIsNone(candidate.suggested_section)


class ScoreTests(unittest.TestCase):
    def test_score_is_cosine_plus_boosts(self):
        document = make_document(
            label="Canal Solar Power Project",
            terms=tokenize("solar power", bigrams=False),
            headings=("Solar power",),
            links=("https://example.com/elsewhere",),
        )
        query = Query(url="https://example.com/canal-solar-power-project/")

        candidate = rank([document], query)[0]

        self.assertTrue(candidate.boosts)
        self.assertAlmostEqual(
            candidate.score,
            candidate.cosine + sum(candidate.boosts.values()),
            places=4,
        )


class OrderingTests(unittest.TestCase):
    def test_ties_break_by_ascending_id(self):
        documents = [
            make_document(id="b", label="Archive", terms=tokenize("solar", bigrams=False)),
            make_document(id="a", label="Archive", terms=tokenize("solar", bigrams=False)),
        ]
        query = Query(url="https://example.com/solar/")

        candidates = rank(documents, query)

        self.assertEqual([item.id for item in candidates], ["a", "b"])

    def test_rare_term_outranks_a_term_in_every_document(self):
        common_one = make_document(
            id="common-one", label="Archive", terms={"common": 1}
        )
        common_two = make_document(
            id="common-two", label="Archive", terms={"common": 1}
        )
        rare = make_document(id="rare", label="Archive", terms={"rare": 1})
        query = Query(url="https://example.com/", title="common rare")

        candidates = rank([common_one, common_two, rare], query)

        self.assertEqual(candidates[0].id, "rare")


class LimitTests(unittest.TestCase):
    def test_top_truncates_and_zero_returns_empty(self):
        documents = [
            make_document(id=str(index), terms=tokenize("solar", bigrams=False))
            for index in range(4)
        ]
        query = Query(url="https://example.com/solar/")

        self.assertEqual(len(rank(documents, query, top=2)), 2)
        self.assertEqual(rank(documents, query, top=0), [])

    def test_no_query_terms_returns_empty(self):
        document = make_document(terms=tokenize("solar", bigrams=False))
        query = Query(url="https://example.com/")

        self.assertEqual(rank([document], query), [])


class CandidateMetadataTests(unittest.TestCase):
    def test_candidate_carries_headings_and_summary(self):
        document = make_document(
            headings=("Solar power", "Panels"),
            summary="The opening line.",
        )
        query = Query(url="https://example.com/solar/")

        candidate = rank([document], query)[0]

        self.assertEqual(candidate.headings, ("Solar power", "Panels"))
        self.assertEqual(candidate.summary, "The opening line.")


class MatchedTests(unittest.TestCase):
    def test_matched_is_sorted_and_capped_at_eight(self):
        terms = {
            name: 1
            for name in (
                "alpha",
                "beta",
                "gamma",
                "delta",
                "epsilon",
                "zeta",
                "eta",
                "theta",
                "iota",
            )
        }
        document = make_document(terms=terms)
        query = Query(
            url="https://example.com/",
            title="iota theta eta zeta epsilon delta gamma beta alpha",
        )

        candidate = rank([document], query)[0]

        self.assertEqual(len(candidate.matched), 8)
        self.assertEqual(list(candidate.matched), sorted(candidate.matched))
        self.assertEqual(
            candidate.matched,
            ("alpha", "beta", "delta", "epsilon", "eta", "gamma", "iota", "theta"),
        )


class UrlHelperTests(unittest.TestCase):
    def test_normalise_url_lowercases_scheme_and_host(self):
        self.assertEqual(
            normalise_url("HTTPS://Example.COM/Path/#frag"),
            "https://example.com/Path",
        )

    def test_normalise_url_drops_trailing_slash_but_keeps_root(self):
        self.assertEqual(
            normalise_url("https://example.com/a/"), "https://example.com/a"
        )
        self.assertEqual(
            normalise_url("https://example.com/"), "https://example.com/"
        )

    def test_normalise_url_keeps_the_query_string(self):
        self.assertEqual(
            normalise_url("https://example.com/a/?b=1#c"),
            "https://example.com/a?b=1",
        )

    def test_host_of_strips_www(self):
        self.assertEqual(host_of("https://www.Example.com/x"), "example.com")

    def test_same_site_compares_bare_hosts(self):
        self.assertTrue(
            same_site("https://example.com/a", "https://www.example.com/b")
        )
        self.assertFalse(
            same_site("https://example.com/a", "https://example.org/b")
        )


class PrecomputedFieldTests(unittest.TestCase):
    def test_a_precomputed_norm_replaces_the_computed_one(self):
        documents = [
            make_document(id="a", terms={"solar": 1}),
            make_document(id="b", terms={"water": 1}),
        ]
        query = Query(url="https://example.com/", title="solar")

        single = rank([replace(documents[0], norm=1.0), documents[1]], query)[0]
        double = rank(
            [replace(documents[0], norm=2.0), documents[1]], query
        )[0]

        self.assertGreater(single.cosine, 0.0)
        self.assertAlmostEqual(single.cosine, double.cosine * 2.0, places=3)

    def test_precomputed_sites_and_link_keys_win_over_the_links(self):
        document = make_document(
            terms={"solar": 1},
            links=("https://example.com/elsewhere",),
            sites=("other.test",),
            link_keys=("https://other.test/elsewhere",),
        )

        candidate = rank(
            [document], Query(url="https://example.com/solar/")
        )[0]

        self.assertNotIn("same_domain", candidate.boosts)
        self.assertFalse(candidate.already_linked)

    def test_precomputed_link_data_supplies_the_same_domain_boost(self):
        document = make_document(
            terms={"solar": 1},
            sites=("example.com",),
            link_keys=("https://example.com/elsewhere",),
        )

        candidate = rank(
            [document], Query(url="https://example.com/solar/")
        )[0]

        self.assertEqual(candidate.boosts["same_domain"], 0.1)
        self.assertFalse(candidate.already_linked)

    def test_linking_only_the_query_url_is_not_another_site(self):
        url = "https://example.com/solar/"
        document = make_document(terms={"solar": 1}, links=(url,))

        candidate = rank([document], Query(url=url))[0]

        self.assertTrue(candidate.already_linked)
        self.assertNotIn("same_domain", candidate.boosts)

    def test_a_link_elsewhere_is_not_another_link_on_the_query_host(self):
        url = "https://example.com/solar/"
        document = make_document(
            terms={"solar": 1},
            links=(url, "https://other.test/elsewhere"),
            sites=("example.com", "other.test"),
            link_keys=(
                "https://example.com/solar",
                "https://other.test/elsewhere",
            ),
        )
        query = Query(url=url)

        prepared = rank([document], query)[0]
        stripped = rank(
            [replace(document, norm=0.0, sites=(), link_keys=())], query
        )[0]

        self.assertTrue(prepared.already_linked)
        self.assertNotIn("same_domain", prepared.boosts)
        self.assertEqual(prepared, stripped)

    def test_a_second_link_on_the_query_host_is_another_site(self):
        url = "https://example.com/solar/"
        document = make_document(
            terms={"solar": 1},
            links=(url, "https://example.com/elsewhere"),
            sites=("example.com",),
            link_keys=(
                "https://example.com/solar",
                "https://example.com/elsewhere",
            ),
        )

        candidate = rank([document], Query(url=url))[0]

        self.assertTrue(candidate.already_linked)
        self.assertEqual(candidate.boosts["same_domain"], 0.1)


class DocumentFrequencyTests(unittest.TestCase):
    def test_counts_documents_per_term(self):
        documents = [
            make_document(id="a", terms={"solar": 2, "panel": 1}),
            make_document(id="b", terms={"solar": 1}),
            make_document(id="c", terms={"water": 1}),
        ]

        frequencies = document_frequencies(documents)

        self.assertEqual(frequencies["solar"], 2)
        self.assertEqual(frequencies["panel"], 1)
        self.assertEqual(frequencies["water"], 1)
        self.assertNotIn("wind", frequencies)


class RankingCostTests(unittest.TestCase):
    def test_document_frequencies_makes_a_single_pass(self):
        documents = [
            make_document(
                id=f"doc{index:04d}",
                terms={
                    f"term{(index * 3 + offset) % 120}": 1 for offset in range(90)
                },
            )
            for index in range(40)
        ]
        counted = CountingSequence(documents)
        query = Query(url="https://example.com/term0/")

        rank(counted, query)

        self.assertLess(counted.accesses, 10 * len(documents))

    def test_ranking_1200_prepared_documents_finishes_quickly(self):
        documents = [
            make_document(
                id=f"doc{index:04d}",
                terms={
                    **{f"term{offset}": 1 for offset in range(10)},
                    **{
                        f"unique{index}-{offset}": 1 for offset in range(60)
                    },
                },
                links=tuple(
                    f"https://site{offset % 12}.example.com/page/{index}"
                    for offset in range(8)
                ),
            )
            for index in range(1200)
        ]
        idf = idf_of(documents)
        documents = [
            replace(
                document,
                norm=document_norm(document.terms, idf),
                sites=tuple(
                    dict.fromkeys(host_of(link) for link in document.links)
                ),
                link_keys=tuple(
                    dict.fromkeys(
                        normalise_url(link) for link in document.links
                    )
                ),
            )
            for document in documents
        ]
        query = Query(
            url="https://example.com/term0/", title="term1 term2"
        )

        started = time.perf_counter()
        candidates = rank(documents, query)
        elapsed = time.perf_counter() - started

        self.assertTrue(candidates)
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()


class BodyQueryTests(unittest.TestCase):
    def _doc(self, page_id, text):
        return Document(id=page_id, wiki="w", label=page_id, subject=None,
                        terms=tokenize(text), headings=(), links=(), text="", summary="")

    def test_body_terms_become_query_terms(self):
        docs = [self._doc("a.md", "futures scenarios methods")]
        rows = rank(docs, Query(url="https://example.com/x", title="Untitled",
                                body="causal layered analysis of futures"), top=3)
        self.assertEqual(rows[0].id, "a.md")
        self.assertIn("future", rows[0].matched)

    def test_a_title_match_outweighs_a_body_match(self):
        docs = [
            self._doc("title.md", "alpha beta gamma"),
            self._doc("body.md", "delta epsilon zeta"),
        ]
        rows = rank(docs, Query(url="https://example.com/x", title="alpha",
                                body="delta"), top=3)
        self.assertEqual(rows[0].id, "title.md")
