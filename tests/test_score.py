import unittest

from wikirc.score import (
    Document,
    Query,
    host_of,
    normalise_url,
    rank,
    same_site,
)
from wikirc.text import tokenize


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


if __name__ == "__main__":
    unittest.main()
