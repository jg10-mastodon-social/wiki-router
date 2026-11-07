import shutil
import tempfile
import unittest
from pathlib import Path

from wikirc.append import (
    apply,
    choose_section,
    existing_links,
    link_key,
    markdown_link,
    plan_append,
)
from wikirc.corpus import Page, discover_wikis

FIXTURES = Path(__file__).parent / "fixtures" / "corpus"


def pages_under(root):
    return {
        f"{wiki.name}/{page.id}": page
        for wiki in discover_wikis(root)
        for page in wiki.pages
    }


def manual_page(directory, text, page_id="notes.md"):
    path = Path(directory) / page_id
    path.write_text(text, encoding="utf-8")
    return Page(
        id=page_id,
        wiki="tmp",
        label="Notes",
        subject=None,
        local=path,
        headings=(),
        links=(),
        text="",
    )


def previous_non_blank(lines, index):
    for position in range(index - 1, -1, -1):
        if lines[position].strip():
            return lines[position]
    return ""


class WritableCase(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.tmp = Path(self._temporary.name)
        self.notes = self.tmp / "notes"
        shutil.copytree(FIXTURES, self.notes)
        self.pages = pages_under(self.notes)

    def page(self, key="garden/watering.md"):
        return self.pages[key]


class MarkdownLinkTests(unittest.TestCase):
    def test_plain_link(self):
        self.assertEqual(
            markdown_link("Watering", "https://example.com/watering"),
            "[Watering](https://example.com/watering)",
        )

    def test_title_whitespace_is_collapsed(self):
        self.assertEqual(
            markdown_link("  Pruning   tomatoes\nweekly ", "https://example.com/x"),
            "[Pruning tomatoes weekly](https://example.com/x)",
        )

    def test_doi_parentheses_are_angle_bracketed(self):
        self.assertEqual(
            markdown_link("A paper", "https://doi.org/10.1000/182(3)"),
            "[A paper](<https://doi.org/10.1000/182(3)>)",
        )

    def test_spaces_are_angle_bracketed(self):
        self.assertEqual(
            markdown_link("A page", "https://example.com/a page"),
            "[A page](<https://example.com/a page>)",
        )


class LinkKeyTests(unittest.TestCase):
    def test_scheme_www_and_trailing_slash_are_ignored(self):
        self.assertEqual(
            link_key("http://www.Example.com/Path/"),
            ("example.com", "/Path", ""),
        )
        self.assertEqual(
            link_key("http://www.Example.com/Path/"),
            link_key("https://example.com/Path"),
        )

    def test_percent_encoded_slash_matches(self):
        self.assertEqual(
            link_key("https://example.com/a%2Fb"),
            link_key("https://example.com/a/b"),
        )

    def test_dx_doi_aliases_doi(self):
        self.assertEqual(
            link_key("https://dx.doi.org/10.1000/182"),
            link_key("http://doi.org/10.1000/182"),
        )

    def test_query_is_part_of_the_key(self):
        self.assertEqual(
            link_key("https://example.com/a?x=1"),
            ("example.com", "/a", "x=1"),
        )
        self.assertNotEqual(
            link_key("https://example.com/a?x=1"),
            link_key("https://example.com/a"),
        )

    def test_invalid_url_returns_itself(self):
        self.assertEqual(link_key("tools.md"), ("", "tools.md", ""))


class ExistingLinksTests(unittest.TestCase):
    def test_finds_markdown_targets_and_bare_urls(self):
        text = (
            "See [one](https://example.com/one), "
            "a bare https://example.com/two. "
            "And [doi](<https://doi.org/10.1000/182(3)>). "
            "Also [tool](tools.md) and https://example.com/three, done"
        )
        self.assertEqual(
            existing_links(text),
            [
                "https://example.com/one",
                "https://example.com/two",
                "https://doi.org/10.1000/182(3)",
                "tools.md",
                "https://example.com/three",
            ],
        )

    def test_no_links_is_empty(self):
        self.assertEqual(existing_links("# Title\n\nJust prose."), [])


class ChooseSectionTests(unittest.TestCase):
    TEXT = (
        "# Page\n"
        "\n"
        "## Watering\n"
        "\n"
        "Some text.\n"
        "\n"
        "## Pruning tomatoes\n"
        "\n"
        "More.\n"
        "\n"
        "## Unsorted\n"
        "\n"
        "Bits.\n"
    )

    def test_best_heading_by_title_tokens(self):
        self.assertEqual(
            choose_section(self.TEXT, "Pruning tomatoes"), "Pruning tomatoes"
        )

    def test_explicit_request_wins_case_insensitively(self):
        self.assertEqual(
            choose_section(self.TEXT, "Pruning tomatoes", "watering"), "Watering"
        )

    def test_closest_requested_heading_is_preferred(self):
        self.assertEqual(
            choose_section(self.TEXT, "Anything at all", "water"), "Watering"
        )

    def test_falls_back_to_unsorted(self):
        self.assertEqual(
            choose_section(self.TEXT, "Nothing matches here"), "Unsorted"
        )

    def test_falls_back_to_end_of_body(self):
        text = "# Page\n\n## Other\n\ntext\n"
        self.assertEqual(choose_section(text, "Nothing matches here"), "")


class PlanAppendTests(WritableCase):
    def test_bullet_without_note(self):
        plan = plan_append(self.page(), "New link", "https://example.com/x")
        self.assertEqual(plan.bullet, "- [New link](https://example.com/x)")

    def test_bullet_with_note(self):
        plan = plan_append(
            self.page(), "New link", "https://example.com/x", note="Read later"
        )
        self.assertEqual(
            plan.bullet, "- [New link](https://example.com/x) — Read later"
        )

    def test_duplicate_is_reported_not_planned(self):
        page = self.page()
        before = page.local.read_bytes()
        plan = plan_append(
            page,
            "Watering",
            "http://pod.example.com/pod/notes/garden/watering.md/",
        )
        self.assertFalse(plan.ok)
        self.assertTrue(plan.already_present)
        self.assertEqual(plan.reason, "already-present")
        self.assertEqual(
            plan.bullet,
            "- [Watering]"
            "(http://pod.example.com/pod/notes/garden/watering.md/)",
        )
        self.assertEqual(page.local.read_bytes(), before)

    def test_duplicate_is_found_from_the_full_file_not_page_text(self):
        page = manual_page(
            self.tmp, "# Notes\n\nSee https://example.com/present.\n"
        )
        plan = plan_append(page, "Present", "https://example.com/present")
        self.assertTrue(plan.already_present)

    def test_diff_contains_the_bullet_and_untouched_lines(self):
        plan = plan_append(self.page(), "Watering", "https://example.com/new")
        self.assertTrue(plan.ok)
        self.assertEqual(plan.reason, "")
        self.assertTrue(plan.diff.startswith("--- "))
        self.assertIn("\n+++ ", plan.diff)
        self.assertIn(f"+{plan.bullet}", plan.diff)
        self.assertIn(" ##### Detail", plan.diff)
        self.assertIn(" ###### Last", plan.diff)


class InsertionTests(WritableCase):
    def test_inserts_before_the_next_heading_of_the_same_or_higher_level(self):
        text = (
            "# Page\n"
            "\n"
            "## Watering\n"
            "\n"
            "Some text.\n"
            "\n"
            "### Detail\n"
            "\n"
            "Detail text.\n"
            "\n"
            "## Other\n"
            "\n"
            "Other text.\n"
        )
        page = manual_page(self.tmp, text)
        plan = plan_append(
            page,
            "New link",
            "https://example.com/new",
            section="Watering",
        )
        apply(plan, page)

        lines = page.local.read_text(encoding="utf-8").splitlines()
        bullet = lines.index("- [New link](https://example.com/new)")
        watering = lines.index("## Watering")
        detail = lines.index("### Detail")
        other = lines.index("## Other")
        self.assertLess(watering, bullet)
        self.assertLess(detail, bullet)
        self.assertLess(bullet, other)
        self.assertEqual(previous_non_blank(lines, bullet), "Detail text.")

    def test_never_inserts_after_a_reference_definition_block(self):
        text = (
            "# Notes\n"
            "\n"
            "## Links\n"
            "\n"
            "Some prose.\n"
            "\n"
            "[1]: https://example.com/one\n"
            "[2]: https://example.com/two\n"
            "\n"
            "## Next\n"
            "\n"
            "More.\n"
        )
        page = manual_page(self.tmp, text)
        plan = plan_append(
            page,
            "New link",
            "https://example.com/new",
            section="Links",
        )
        apply(plan, page)

        lines = page.local.read_text(encoding="utf-8").splitlines()
        bullet = lines.index("- [New link](https://example.com/new)")
        self.assertEqual(previous_non_blank(lines, bullet), "Some prose.")
        self.assertLess(bullet, lines.index("[1]: https://example.com/one"))

    def test_end_of_body_stays_before_trailing_references(self):
        text = (
            "# Notes\n"
            "\n"
            "Some prose.\n"
            "\n"
            "[1]: https://example.com/one\n"
            "[2]: https://example.com/two\n"
        )
        page = manual_page(self.tmp, text)
        plan = plan_append(page, "New link", "https://example.com/new")
        self.assertEqual(plan.section, "")
        apply(plan, page)

        lines = page.local.read_text(encoding="utf-8").splitlines()
        bullet = lines.index("- [New link](https://example.com/new)")
        self.assertEqual(previous_non_blank(lines, bullet), "Some prose.")
        self.assertLess(bullet, lines.index("[1]: https://example.com/one"))


class ApplyTests(WritableCase):
    def test_apply_writes_and_planning_alone_does_not(self):
        page = self.page()
        original = page.local.read_bytes()

        plan = plan_append(page, "Watering", "https://example.com/new")
        self.assertEqual(page.local.read_bytes(), original)

        self.assertIsNone(apply(plan, page))
        updated = page.local.read_text(encoding="utf-8")
        self.assertNotEqual(page.local.read_bytes(), original)
        self.assertIn(plan.bullet, updated.splitlines())
        for line in original.decode("utf-8").splitlines():
            self.assertIn(line, updated.splitlines())

    def test_apply_refuses_a_rejected_plan(self):
        page = self.page()
        original = page.local.read_bytes()
        plan = plan_append(
            page, "Watering", "https://pod.example.com/pod/notes/garden/watering.md"
        )
        self.assertFalse(plan.ok)

        apply(plan, page)
        self.assertEqual(page.local.read_bytes(), original)
