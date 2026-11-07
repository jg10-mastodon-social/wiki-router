# wiki-router

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
