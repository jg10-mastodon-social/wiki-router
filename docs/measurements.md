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
