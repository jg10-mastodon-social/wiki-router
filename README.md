# wiki-router

Ranks wiki pages for a URL from a precomputed local index, and adds the link to
the chosen page as one markdown bullet.

The router never crawls a wiki. `build` reads a directory tree once and writes a
derived index; `route` ranks against that index; `append` edits the page.

## What it needs from you

| Variable | Purpose |
|---|---|
| `WIKI_ROUTER_NOTES` | Root of the wiki tree. Each wiki is a subdirectory containing `label-index.ttl`. |
| `WIKI_ROUTER_HOME` | State directory for `index.json`. Created on first build. |
| `WIKI_ROUTER_POD_BASE` | Optional. Canonical base URL for page links, e.g. `https://pod.example.com/pod/notes`. Without it, pages are identified by their relative id. |

No defaults: running without the required variables is an error that names the
missing variable, because a wrong guess here silently produces wrong answers.

## Usage

```bash
python3 -m wikirc --help
```

`bin/wiki-router` is a thin shim that does the same thing from the checkout.

## Tests

```bash
python3 -m unittest discover -s tests
```

Stdlib only, no install step. The fixtures are a toy corpus; they are examples of
the index format, not a sample of anyone's notes.
