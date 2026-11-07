# wiki-router

![No maintenance intended](https://img.shields.io/badge/no_maintenance_intended-orange) ![Code quality: TDD vibe coded](https://img.shields.io/badge/code_quality-TDD_vibe_coded-orange)

Ranks wiki pages for a URL from a precomputed local index and adds the link to
the chosen page as one markdown bullet.

It never crawls a wiki. `build` reads a directory tree once and writes a derived
index; `route` ranks against that index; `append` edits the page.

## Requirements

Python 3.10 or newer. Nothing else: no third-party packages, no install step, no
service.

## Configuration

| Variable | Required | Purpose |
|---|---|---|
| `WIKI_ROUTER_NOTES` | yes | Root of the wiki tree. Each wiki is a subdirectory containing `label-index.ttl`. |
| `WIKI_ROUTER_HOME` | yes | State directory for `index.json`. Created on first build. |
| `WIKI_ROUTER_POD_BASE` | no | Canonical base URL for page links, e.g. `https://pod.example.com/pod/notes`. Without it, pages are identified by their relative id only. |

There are no defaults for the two required variables. A missing one is an error
that names it, because a wrong guess here silently produces wrong answers.

```bash
export WIKI_ROUTER_NOTES=~/notes
export WIKI_ROUTER_HOME=~/.local/share/wiki-router
export WIKI_ROUTER_POD_BASE=https://pod.example.com/pod/notes
```

## Usage

`bin/wiki-router` is a shim; `python3 -m wikirc` does the same thing from the
checkout. Every command accepts `--json`.

```bash
wiki-router config --json          # what this process will actually use
wiki-router build                  # write the index
wiki-router build --check          # exit 1 when stale
wiki-router route https://example.com/article --json
wiki-router route https://example.com/article --context "surrounding text"
wiki-router eval --fixture my-decisions.json
wiki-router append https://example.com/article --page watering.md
wiki-router append https://example.com/article --page watering.md --apply
```

### A wiki

Any directory under `WIKI_ROUTER_NOTES` that contains a `label-index.ttl` is a
wiki. The index maps pages to labels and accepts prefixed or full-IRI predicates,
absolute or percent-encoded relative subjects, and comma/semicolon
continuations. A page stored with a storage suffix (`card.md$.txt`) resolves as
`card.md`.

Pages are markdown. Headings, outbound links and body text are indexed; a link
list page is reachable by the domains it cites.

## The route payload

`route --json` prints, and nothing else:

```jsonc
{
  "contract": 1,                 // bumped only on an incompatible change
  "url": "…",
  "final_url": "…",              // after redirects
  "fetched": {
    "ok": true, "title": "…", "description": "", "source": "crossref",
    "creator": "", "date": "", "isbn": "", "canonical": "",
    "title_noisy": false, "error": ""
  },
  "reliability": "ok",           // "low" when the title could not be established
  "candidates": [
    {
      "id": "watering.md", "wiki": "garden", "label": "Watering",
      "subject": "https://pod.example.com/pod/notes/garden/watering.md",
      "score": 0.8629, "cosine": 0.4329,
      "boosts": {"label_exact": 0.5}, "matched": ["watering"],
      "already_linked": false, "heading_match": true,
      "suggested_section": "Watering", "headings": ["Watering"],
      "summary": "Water deeply once a week."
    }
  ]
}
```

Candidates that score zero are omitted. When `reliability` is `low`, treat the
order as noise: establish the title first (see below) or pass `--context`.

DOIs resolve through Crossref, archive.org details pages through their metadata
API, and any book page carrying a checksum-valid ISBN — on a bookseller host or
under a `/books/` path — through Open Library. A publisher that answers 403 no
longer poisons the title. An ordinary page that merely cites an ISBN is left
alone.

## Evaluation

`eval` replays recorded decisions and exits non-zero unless every case lands in
the top N, so a regression fails a command rather than needing inspection.

```json
{
  "cases": [
    {
      "url": "https://example.com/article",
      "title": "Article",
      "acceptable": ["garden/watering.md"],
      "context": "optional",
      "note": "optional"
    }
  ]
}
```

`acceptable` may list every page a person would accept; a case passes when any
of them lands in the top N. Entries may be wiki-relative (`watering.md`) or
wiki-qualified (`garden/watering.md`).

A case may name the capability it exists to cover:

```json
{ "url": "…", "title": "…", "acceptable": ["garden/watering.md"],
  "capability": "routing a DOI to the consolidated topic page" }
```

That is a statement of intent, not a diagnosis, so it stays true however the case
fails. `eval` groups failing cases under those statements and prints the
capabilities the fixture covers that are not met, which is a description of what
the router cannot do yet rather than a list of runners-up. A failure with no
statement is counted separately as unclassified, and any failure still exits
non-zero: the statement explains a failure, it does not excuse it.

### Synonyms

Scoring is lexical, so a link that names a subject differently from the page that
covers it never matches. A synonym map states the vocabulary of a corpus:

```json
// $WIKI_ROUTER_HOME/synonyms.json
{ "foresight": "futures", "causal layered analysis": "futures" }
```

Phrases are allowed and the longest match wins, so `causal layered analysis` is
not also expanded as `causal layered`. Expansion applies to the query — title,
description and context — and leaves the original words in place, so a phrase
stays evidence in its own right. It does not touch the index, which means
changing the map never invalidates a build. `--synonyms PATH` overrides the
default location.

### Redirected pages

When content moves between pages, the old page keeps enough of the original
wording to outrank its replacement, and ranking cannot know that. A redirect
file states the move:

```json
// $WIKI_ROUTER_HOME/wiki_redirects.json
{ "notes/alpha.md": "topics/alpha.md" }
```

A candidate whose page is a redirect source is reported as its target, keeping
the score it earned, with `"redirected": true` and `redirectedFrom`. A target the
corpus does not contain is ignored rather than invented. The file is optional,
`--redirects PATH` overrides its location, and `eval` applies the same map so
recorded decisions follow the migration.

The fixture committed here is an example over the toy corpus. Real decisions
belong outside the repository; pass them with `--fixture`. `eval` prints which
fixture it used, so an example run cannot be mistaken for a real one.

Metadata resolution has its own offline evals under `tests/fixtures/metadata/`,
replayed by `tests/metadata_eval.py` with recorded payloads and no network.

## Tests

```bash
python3 -m unittest discover -s tests
```

Stdlib only. No test touches the network: HTTP is injected, and metadata evals
serve recorded payloads. The committed corpus is a toy example of the format, not
a sample of anyone's notes.

## Layout

```
bin/wiki-router     shim: repository root onto sys.path, then wikirc.cli:main
wikirc/cli.py       argument parsing and dispatch
wikirc/config.py    environment loading and validation
wikirc/index.py     label-index parsing
wikirc/corpus.py    wiki discovery, page resolution, text extraction
wikirc/text.py      stopwords, stemming, tokenising
wikirc/score.py     tf-idf ranking and boosts
wikirc/store.py     index build, fingerprint, persistence
wikirc/router.py    route payload assembly
wikirc/fetch.py     fetch orchestration and HTML extraction
wikirc/http.py      HTTP transport
wikirc/result.py    the FetchResult type
wikirc/metadata.py  DOI resolution through Crossref
wikirc/books.py     archive.org and Open Library resolution
wikirc/append.py    bullet planning and application
wikirc/evaluate.py  fixture replay
```

## Licence

MIT. See `LICENSE`.
