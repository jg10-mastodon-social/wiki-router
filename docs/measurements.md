# Measurements

Numbers only. The corpora used for parity runs are private and are not named
here; what is recorded is the method, the scale, and the outcome.

## 2026-11-07 — parity against the previous implementation

Method: both routers built an index over the same corpus, then replayed the same
recorded decisions. `hit@1` counts cases whose expected page ranked first;
`hit@5` counts cases where it appeared anywhere in the top five.

| Corpus | Pages | Cases | This router | Previous |
|---|---|---|---|---|
| 3 wikis (subset of a real notes tree) | 351 | 16 | hit@1 16/16, hit@5 16/16 | hit@1 16/16, hit@5 16/16 |

Top-1 agreement was complete. The two models disagreed on runner-up ordering in
10 of 16 cases, and the previous implementation consistently promoted pages whose
only signal was a cited link.

Corpus handling differed once: this router indexed a page whose filename contains
several dots, which the previous implementation silently skipped (351 vs 350).

## 2026-11-07 — synthetic hypothesis corpus

Four hypotheses were tested against a hand-built corpus where each case isolates
one suspected weakness. This router scored 5/6, the previous 3/6.

Two hypotheses were refuted:

- **Field weighting.** A page carrying the topic in a heading lost to a page
  repeating it in body text, in *both* implementations. Weighting title and
  headings more heavily would not have changed the outcome.
- **Generic-host boosts.** The suspected false boost from citing a generic host
  was not what decided the case: `same_domain` already ignores a link that is the
  query URL itself.

## 2026-11-07 — live fetches the eval cannot see

Eval fixtures supply their own titles, so they cannot detect a bad fetch. Two
live URLs exposed failures:

| Input | Symptom | Expected behaviour |
|---|---|---|
| A DOI URL | publisher returns `HTTP 403`, title falls back to the slug (`ffo2 61`), `reliability: low` | resolve the title through Crossref |
| An archive.org book page | title is page chrome, and the top candidate was a different page than the recorded decision | resolve title and author through archive.org metadata and Open Library |

This is the measured case for adding metadata resolution before any further
ranking work.

## 2026-11-07 — filed versus unfiled corpora

Every earlier comparison replayed the fixture against the corpus as filed, where
the expected page already contains the case URL. Sixteen of seventeen expected
pages were in that state. That measures re-filing, not routing.

`tools/unfiled_corpus.py` removes every line containing a fixture URL, so the
corpus is in the state the router actually faces: a link nobody has seen.

| Corpus | Pages | This router hit@1 / hit@5 | Previous hit@1 / hit@5 |
|---|---|---|---|
| as filed | 5,495 | 12/17 · 17/17 | 17/17 · 17/17 |
| unfiled | 5,495 | **7/17 · 11/17** | **4/17 · 6/17** |

The previous implementation's perfect score was largely the already-linked boost
plus the answer page carrying the link's own words. With the link removed the
rebuild is ahead on both measures.

Remaining misses are concentrated where a short concept note from the dominant
collection is a defensible answer alongside the page the fixture names: a query
about a topic covered in both places ranks the concept note first. Those cases
say as much about single-page `acceptable` sets as about ranking.

## 2026-11-07 — both resolved

Re-measured after metadata resolution landed, same inputs:

| Input | Before | After |
|---|---|---|
| DOI URL | `reliability: low`, title from the slug, publisher `HTTP 403` | `reliability: ok`, `source: crossref`, real title, author and year |
| archive.org book page | page-chrome title, top candidate was the wrong page | `source: openlibrary`, clean title, author and ISBN, top candidate is the recorded page |

Both are covered by offline eval fixtures, so a regression fails a test rather
than needing a live check.
