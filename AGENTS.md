# wiki-router — working agreement

Rebuilt from scratch, one feature per cycle, tests first. The implementation is
not copied from any earlier version; behaviour is re-derived from tests.

## Rules

- **TDD.** Write the failing test first and run it. Paste the failure. Only then
  implement the minimum that passes.
- **Never commit a knowingly failing test.** A test and its implementation land
  in the same commit.
- **One feature per cycle, one conventional commit per cycle.** No drive-by
  refactors, no unrelated cleanups.
- **Runtime is stdlib only.** No third-party packages, no install step. Dev
  dependencies do not exist: the test runner is `unittest`.
- **No machine-specific values.** No absolute paths, no home directories, no
  hostnames in code or fixtures. Configuration arrives through the environment;
  fixtures are synthetic.
- **Verify before reporting.** `python3 -m unittest discover -s tests` must pass
  in full, not just the new test.

## Cycle workflow

1. **Brief.** The orchestrator states the goal, the failing tests to add,
   acceptance criteria, and the files in scope.
2. **Red.** The implementer adds those tests and shows them failing for the
   intended reason — not an import error, not a typo.
3. **Green.** Minimum implementation. No speculative abstractions.
4. **Verify.** Full suite green. Report the diff and the test output.
5. **Review.** The orchestrator inspects the diff. Out-of-scope changes go back.
6. **Commit.** The orchestrator commits; implementers never commit or push.

## Subagent delegation

- The orchestrating agent delegates each implementation cycle to a subagent.
- Subagents must **not** delegate further and must **not** call task tools.
- A subagent's brief must include the cycle goal, the acceptance criteria, the
  relevant existing files, and an explicit statement of what is out of scope.

## Layout

```
bin/wiki-router      shim: repo root onto sys.path, then wikirc.cli:main
wikirc/config.py     environment loading and validation
wikirc/cli.py        argument parsing and subcommand dispatch
tests/               unittest modules
tests/fixtures/      synthetic corpus and eval fixture
```
