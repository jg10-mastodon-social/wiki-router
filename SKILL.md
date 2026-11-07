---
name: wiki-router
description: Use when asked to file, route, add or save a URL or link into a markdown wiki, or to find which page a link belongs on. Ranks pages from a precomputed index, then appends the link as one bullet after approval.
---

# Routing a link to a wiki page

Find the page a URL belongs on, then add it as one markdown bullet:

```markdown
- [Page title](https://example.com/article)
```

Routing runs against a **precomputed index**, so the expensive part happens at
build time. At routing time you see only the candidates, their scores and the
evidence; you do not read the wiki.

## 1. Keep the index fresh

```bash
wiki-router build --check   # exit 1 means stale
wiki-router build
```

Rebuild after adding, renaming or editing pages. If the index is stale, `route`
still works but warns on stderr — say so, and rebuild before trusting orderings.

## 2. Rank pages for the URL

```bash
wiki-router route 'https://example.com/article' --json --top 5
```

Options:

- `--context "text"` — the note or paragraph the URL came from. Pass it whenever
  the user supplied surrounding text.
- `--wiki reader` — restrict to one wiki.
- `--exclude-wiki archive` — drop one.
- `--no-fetch` — rank from the URL alone, for paywalled or already-known URLs.
- `--title "…"` — override the fetched title when it is wrong.

Each candidate carries `id`, `wiki`, `label`, `subject`, `score`, `cosine`,
`boosts`, `matched`, `already_linked`, `heading_match`, `suggested_section`,
`headings` and `summary`.

**Check `reliability` first.** When it is `low`, the title could not be
established and the ranks are near-noise: do not reason from the scores. Resolve
the title, pass `--context`, or rerun with `--no-fetch`.

DOIs and archive.org book pages are resolved automatically, so their titles are
usually reliable even when the publisher blocks a direct fetch.

## 3. Judge the candidates

Do not simply take rank 1.

- **Strong** — a label boost (`label_exact`, `label_most`), or `score >= 0.30`
  with at least two meaningful `matched` terms, and `already_linked` false.
- **Medium** — `score` 0.15–0.30 with several matched terms. Show two or three
  options and ask.
- **Weak** — `score < 0.15`, a single generic term, or `already_linked` true.
  Say so, ask, or suggest a new page rather than forcing a match.

Prefer the page whose `label` and `summary` match the *subject* of the URL, not
merely a keyword. `already_linked` means the URL is already on that page: report
it instead of adding a duplicate.

If nothing fits, say so. Do not create pages unasked and do not stretch a weak
match.

## 4. Propose, then append

Show the chosen page, one line of evidence and the exact bullet. **Wait for
explicit approval before writing.**

```bash
# dry run: prints the bullet, the section and a unified diff
wiki-router append 'https://example.com/article' --page garden/watering.md

# after approval
wiki-router append 'https://example.com/article' --page garden/watering.md --apply
```

- `--page` accepts the id (`watering.md`), the wiki-qualified id
  (`garden/watering.md`), the label, or the page's subject URL.
- `--note` appends ` — note` after the link; omit it for a plain bullet.
- `--section` forces a heading. By default the heading whose text best matches
  the title is used, else `Unsorted`, else the end of the body before reference
  definitions.
- Duplicate URLs are refused with exit 1, treating `http`/`https`, `www.`,
  trailing slashes and the `dx.doi.org` alias as the same link.
- URLs containing parentheses (common for DOIs) are angle-bracketed automatically.

Then verify the bullet is in place, that only the intended file changed, and
rebuild the index before the next routing run.

## When writing through a pod instead

If the wiki lives behind a Solid pod and the host running this tool cannot write
it, use `append` as a **dry run only** to obtain the bullet and section, then
apply the change through the pod's own client. Never write the file directly from
two places.
