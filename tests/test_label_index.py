import dataclasses
import unittest
from pathlib import Path

from wikirc.index import LabelEntry, LabelIndexError, load_label_index, parse_label_index

RDFS = "<http://www.w3.org/2000/01/rdf-schema#>"
PREFIX = f"@prefix rdfs: {RDFS} .\n"


class ParseLabelIndexTests(unittest.TestCase):
    def test_prefixed_predicate_with_relative_subject(self):
        text = PREFIX + '\n<Pruning%20Tomatoes.md> rdfs:label "Pruning Tomatoes" .\n'

        entries = parse_label_index(text)

        self.assertEqual(
            entries,
            [
                LabelEntry(
                    ref="Pruning%20Tomatoes.md",
                    labels=("Pruning Tomatoes",),
                    comment=None,
                )
            ],
        )

    def test_full_iri_predicate_without_prefix_declaration(self):
        text = '<daily%20planner.md> <http://www.w3.org/2000/01/rdf-schema#label> "Daily Planner".\n'

        entries = parse_label_index(text)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].ref, "daily%20planner.md")
        self.assertEqual(entries[0].labels, ("Daily Planner",))

    def test_absolute_subject_preserved_verbatim(self):
        text = PREFIX + (
            "<https://pod.example.com/pod/notes/garden/tomatoes.md> "
            'rdfs:label "Card" .\n'
        )

        entries = parse_label_index(text)

        self.assertEqual(
            entries[0].ref, "https://pod.example.com/pod/notes/garden/tomatoes.md"
        )

    def test_comma_separated_labels_are_all_kept_in_order(self):
        text = PREFIX + '<!thing.md> rdfs:label "One", "Two" .\n'

        entries = parse_label_index(text)

        self.assertEqual(entries[0].labels, ("One", "Two"))

    def test_semicolon_continuation_captures_comment(self):
        text = PREFIX + (
            '<!/a page.md> rdfs:label "/Path-like label", "Real Label" '
            '; rdfs:comment "Grouped under a folder" .\n'
        )

        entries = parse_label_index(text)

        self.assertEqual(
            entries,
            [
                LabelEntry(
                    ref="!/a page.md",
                    labels=("/Path-like label", "Real Label"),
                    comment="Grouped under a folder",
                )
            ],
        )

    def test_unrelated_predicate_yields_no_entry(self):
        text = PREFIX + (
            '<notes.md> rdfs:category "Misc" .\n'
            '<other.md> rdfs:label "Other" .\n'
        )

        entries = parse_label_index(text)

        self.assertEqual([entry.ref for entry in entries], ["other.md"])

    def test_escaped_quotes_and_backslashes_are_unescaped(self):
        text = PREFIX + (
            '<quoted.md> rdfs:label "She said \\"hi\\"" .\n'
            '<path.md> rdfs:label "a\\\\b" .\n'
        )

        entries = parse_label_index(text)

        self.assertEqual(
            [entry.labels[0] for entry in entries],
            ['She said "hi"', "a\\b"],
        )

    def test_blank_lines_and_comment_lines_are_ignored(self):
        text = (
            "\n"
            "# this whole line is a comment\n"
            + PREFIX
            + "\n"
            '   # indented comment mentioning rdfs:label "Nope" .\n'
            '<kept.md> rdfs:label "Kept" .\n'
            "\n"
        )

        entries = parse_label_index(text)

        self.assertEqual([entry.ref for entry in entries], ["kept.md"])

    def test_unterminated_string_raises(self):
        text = PREFIX + '<broken.md> rdfs:label "no closing quote .\n'

        with self.assertRaises(LabelIndexError) as caught:
            parse_label_index(text)

        self.assertIn("terminated", str(caught.exception).lower())

    def test_missing_terminating_dot_raises(self):
        text = PREFIX + '<broken.md> rdfs:label "Fine"\n'

        with self.assertRaises(LabelIndexError) as caught:
            parse_label_index(text)

        self.assertIn(".", str(caught.exception))

    def test_entry_is_frozen(self):
        entry = LabelEntry(ref="a.md", labels=("A",), comment=None)

        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.ref = "b.md"


class LoadLabelIndexTests(unittest.TestCase):
    FIXTURE = Path(__file__).parent / "fixtures" / "parsing" / "label-index.ttl"

    def test_load_matches_parse_on_same_text(self):
        text = self.FIXTURE.read_text(encoding="utf-8")

        self.assertEqual(load_label_index(self.FIXTURE), parse_label_index(text))

    def test_fixture_contains_relative_and_absolute_subjects(self):
        entries = load_label_index(self.FIXTURE)

        self.assertEqual(
            [entry.ref for entry in entries],
            [
                "Pruning%20Tomatoes.md",
                "https://pod.example.com/pod/notes/garden/tomatoes.md",
            ],
        )


if __name__ == "__main__":
    unittest.main()
