STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "me",
        "more",
        "most",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
    }
)

_DOUBLED_CONSONANTS = ("bb", "dd", "gg", "mm", "nn", "pp", "rr", "tt")


def stem(word: str) -> str:
    if len(word) < 4:
        return word

    result = word
    if result.endswith("ies") and len(word) > 4:
        result = result[:-3] + "y"
    elif result.endswith("sses"):
        result = result[:-2]
    elif result.endswith("s") and not result.endswith(("ss", "us", "is")):
        result = result[:-1]

    before_suffix = result
    if result.endswith("ing") and len(result) - 3 >= 3:
        result = result[:-3]
    elif result.endswith("ed") and len(result) - 2 >= 3:
        result = result[:-2]

    if result.endswith(_DOUBLED_CONSONANTS):
        result = result[:-1]

    if len(result) < 3:
        return before_suffix
    return result


def tokenize(text: str, bigrams: bool = True) -> dict[str, int]:
    cleaned = "".join(
        char if char.isalnum() else " " for char in text.lower()
    )
    tokens = [
        token
        for token in cleaned.split()
        if len(token) >= 2 and token not in STOPWORDS
    ]

    counts: dict[str, int] = {}
    for token in tokens:
        key = stem(token)
        counts[key] = counts.get(key, 0) + 1

    if bigrams:
        for first, second in zip(tokens, tokens[1:]):
            key = f"{first} {second}"
            counts[key] = counts.get(key, 0) + 1

    return counts
