import unittest

from wikirc.text import STOPWORDS, stem, tokenize


class StemTests(unittest.TestCase):
    def test_trailing_s_is_dropped(self):
        self.assertEqual(stem("repetitions"), "repetition")

    def test_ies_becomes_y(self):
        self.assertEqual(stem("categories"), "category")

    def test_ing_is_dropped_and_doubled_consonant_collapsed(self):
        self.assertEqual(stem("running"), "run")

    def test_ed_is_dropped(self):
        self.assertEqual(stem("processed"), "process")

    def test_short_words_are_untouched(self):
        self.assertEqual(stem("cat"), "cat")
        self.assertEqual(stem("is"), "is")

    def test_stem_never_drops_below_three_characters(self):
        self.assertEqual(stem("sing"), "sing")


class StopwordTests(unittest.TestCase):
    def test_common_word_is_a_stopword(self):
        self.assertIn("the", STOPWORDS)

    def test_content_word_is_not_a_stopword(self):
        self.assertNotIn("water", STOPWORDS)


class TokenizeTests(unittest.TestCase):
    def test_stopwords_removed_and_unigrams_stemmed(self):
        self.assertEqual(
            tokenize("The feeds and the cards", bigrams=False),
            {"feed": 1, "card": 1},
        )

    def test_one_character_tokens_are_dropped(self):
        self.assertEqual(tokenize("a b c ab", bigrams=False), {"ab": 1})

    def test_punctuation_and_digits_split_words(self):
        self.assertEqual(
            tokenize("feed-reader, 2nd card", bigrams=False),
            {"feed": 1, "reader": 1, "2nd": 1, "card": 1},
        )

    def test_bigrams_use_unstemmed_adjacent_words(self):
        counts = tokenize("spaced repetition")

        self.assertEqual(counts["spaced repetition"], 1)

    def test_bigrams_are_omitted_when_disabled(self):
        self.assertEqual(
            tokenize("spaced repetition", bigrams=False),
            {"spac": 1, "repetition": 1},
        )

    def test_non_latin_text_is_tokenised(self):
        self.assertEqual(
            tokenize("Привет мир", bigrams=False),
            {"привет": 1, "мир": 1},
        )


if __name__ == "__main__":
    unittest.main()
