import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest import mock

from wikirc.cli import build_parser, main
from wikirc.fetch import FetchResult

FIXTURES = Path(__file__).parent / "fixtures" / "corpus"


def fetched(url, **overrides):
    fields = {"ok": True, "error": "", "source": "html"}
    fields.update(overrides)
    return replace(FetchResult.disabled(url), **fields)


class ParserTests(unittest.TestCase):
    def test_program_name(self):
        self.assertEqual(build_parser().prog, "wiki-router")


class VersionCommandTests(unittest.TestCase):
    def test_version_json(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["version", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(
            out.getvalue(), '{"version": "0.1.0", "contract": 1}\n'
        )
        self.assertEqual(
            json.loads(out.getvalue()), {"version": "0.1.0", "contract": 1}
        )

    def test_version_plain(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["version"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "wiki-router 0.1.0 (contract 1)\n")


class ConfigCommandTests(unittest.TestCase):
    def test_config_json_prints_loaded_paths(self):
        with tempfile.TemporaryDirectory() as notes, tempfile.TemporaryDirectory() as state:
            environ = {"WIKI_ROUTER_NOTES": notes, "WIKI_ROUTER_HOME": state}
            out = io.StringIO()
            with mock.patch.dict(os.environ, environ, clear=True):
                with redirect_stdout(out):
                    code = main(["config", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out.getvalue()),
            {"notes": notes, "state": state, "podBase": None},
        )

    def test_config_json_reports_pod_base(self):
        pod_base = "https://pod.example.com/pod/notes"
        with tempfile.TemporaryDirectory() as notes, tempfile.TemporaryDirectory() as state:
            environ = {
                "WIKI_ROUTER_NOTES": notes,
                "WIKI_ROUTER_HOME": state,
                "WIKI_ROUTER_POD_BASE": pod_base + "/",
            }
            out = io.StringIO()
            with mock.patch.dict(os.environ, environ, clear=True):
                with redirect_stdout(out):
                    code = main(["config", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["podBase"], pod_base)

    def test_config_plain(self):
        with tempfile.TemporaryDirectory() as notes, tempfile.TemporaryDirectory() as state:
            environ = {"WIKI_ROUTER_NOTES": notes, "WIKI_ROUTER_HOME": state}
            out = io.StringIO()
            with mock.patch.dict(os.environ, environ, clear=True):
                with redirect_stdout(out):
                    code = main(["config"])
        self.assertEqual(code, 0)
        self.assertEqual(
            out.getvalue().splitlines(),
            [f"notes: {notes}", f"state: {state}", "podBase: -"],
        )

    def test_config_without_home_reports_config_error(self):
        err = io.StringIO()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as notes:
            with mock.patch.dict(
                os.environ, {"WIKI_ROUTER_NOTES": notes}, clear=True
            ):
                with redirect_stdout(out), redirect_stderr(err):
                    code = main(["config", "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("WIKI_ROUTER_HOME", err.getvalue())
        self.assertTrue(err.getvalue().startswith("wiki-router: "))

    def test_config_without_environment_reports_notes_first(self):
        err = io.StringIO()
        out = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["config", "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("WIKI_ROUTER_NOTES", err.getvalue())


class BuildCommandTests(unittest.TestCase):
    def _run(self, args, notes, state):
        environ = {
            "WIKI_ROUTER_NOTES": str(notes),
            "WIKI_ROUTER_HOME": str(state),
        }
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, environ, clear=True):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_check_before_any_build_is_stale(self):
        with tempfile.TemporaryDirectory() as state:
            code, out, err = self._run(["build", "--check"], FIXTURES, state)

        self.assertEqual(code, 1)
        self.assertEqual(out, "index is stale\n")
        self.assertEqual(err, "")

    def test_build_then_check_is_up_to_date(self):
        with tempfile.TemporaryDirectory() as state:
            code, out, err = self._run(["build"], FIXTURES, state)
            self.assertEqual(code, 0)
            self.assertEqual(err, "")
            self.assertEqual(
                out,
                f"indexed 7 pages -> {Path(state) / 'index.json'}\n",
            )
            self.assertTrue((Path(state) / "index.json").is_file())

            code, out, err = self._run(["build", "--check"], FIXTURES, state)

        self.assertEqual(code, 0)
        self.assertEqual(out, "index is up to date\n")
        self.assertEqual(err, "")

    def test_build_json_reports_pages_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as state:
            code, out, err = self._run(["build", "--json"], FIXTURES, state)

            payload = json.loads(out)

            self.assertEqual(code, 0)
            self.assertEqual(err, "")
            self.assertEqual(payload["pages"], 7)
            self.assertEqual(len(payload["fingerprint"]), 64)
            self.assertEqual(payload["notes"], str(FIXTURES))
            self.assertFalse(payload["stale"])

            code, out, err = self._run(
                ["build", "--check", "--json"], FIXTURES, state
            )

        checked = json.loads(out)
        self.assertEqual(code, 0)
        self.assertFalse(checked["stale"])
        self.assertEqual(
            sorted(checked),
            ["fingerprint", "generated", "notes", "pages", "stale"],
        )

    def test_build_without_environment_reports_two(self):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["build"])

        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("WIKI_ROUTER_NOTES", err.getvalue())


class RouteCommandTests(unittest.TestCase):
    def _run_with(self, args, notes, state, fetcher):
        environ = {
            "WIKI_ROUTER_NOTES": str(notes),
            "WIKI_ROUTER_HOME": str(state),
        }
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, environ, clear=True):
            with mock.patch(
                "wikirc.cli.fetch", side_effect=fetcher
            ) as patched:
                with redirect_stdout(out), redirect_stderr(err):
                    code = main(args)
        return code, out.getvalue(), err.getvalue(), patched

    def _run(self, args, notes, state, fetcher=None):
        if fetcher is None:
            fetcher = lambda url, **kwargs: fetched(url)
        code, out, err, _ = self._run_with(
            args, notes, state, fetcher
        )
        return code, out, err

    def test_route_json_on_a_built_corpus(self):
        with tempfile.TemporaryDirectory() as state:
            code, _, err = self._run(["build"], FIXTURES, state)
            self.assertEqual(code, 0)
            self.assertEqual(err, "")

            code, out, err = self._run(
                [
                    "route",
                    "https://example.com/watering/",
                    "--no-fetch",
                    "--json",
                ],
                FIXTURES,
                state,
            )

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(payload["contract"], 1)
        self.assertFalse(payload["fetched"]["ok"])
        self.assertEqual(payload["fetched"]["error"], "fetch disabled")
        self.assertEqual(payload["reliability"], "low")
        self.assertTrue(payload["candidates"])
        self.assertNotIn(str(FIXTURES), out)

    def test_route_json_with_a_title_reports_ok(self):
        with tempfile.TemporaryDirectory() as state:
            self._run(["build"], FIXTURES, state)
            code, out, err = self._run(
                [
                    "route",
                    "https://example.com/watering/",
                    "--title",
                    "Watering",
                    "--json",
                ],
                FIXTURES,
                state,
            )

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertTrue(payload["fetched"]["ok"])
        self.assertEqual(payload["fetched"]["title"], "Watering")
        self.assertEqual(payload["fetched"]["error"], "")
        self.assertEqual(payload["reliability"], "ok")

    def test_route_plain_reports_url_title_and_candidates(self):
        with tempfile.TemporaryDirectory() as state:
            self._run(["build"], FIXTURES, state)
            code, out, err = self._run(
                [
                    "route",
                    "https://example.com/watering/",
                    "--title",
                    "Watering",
                ],
                FIXTURES,
                state,
            )

        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(lines[0], "url: https://example.com/watering/")
        self.assertEqual(lines[1], "title: Watering")
        self.assertEqual(lines[2], "reliability: ok")
        self.assertIn("garden/Watering", out)
        self.assertIn("watering.md", out)

    def test_route_top_truncates(self):
        with tempfile.TemporaryDirectory() as state:
            self._run(["build"], FIXTURES, state)
            code, out, _ = self._run(
                ["route", "https://example.com/watering/", "--top", "1", "--json"],
                FIXTURES,
                state,
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["candidates"]), 1)

    def test_route_wiki_filters_candidates(self):
        with tempfile.TemporaryDirectory() as state:
            self._run(["build"], FIXTURES, state)
            code, out, _ = self._run(
                ["route", "https://example.com/chain/", "--wiki", "cycling", "--json"],
                FIXTURES,
                state,
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            {candidate["wiki"] for candidate in json.loads(out)["candidates"]},
            {"cycling"},
        )

    def test_route_exclude_wiki_drops_one_wiki(self):
        with tempfile.TemporaryDirectory() as state:
            self._run(["build"], FIXTURES, state)
            code, out, _ = self._run(
                [
                    "route",
                    "https://example.com/chain/",
                    "--exclude-wiki",
                    "garden",
                    "--json",
                ],
                FIXTURES,
                state,
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            {candidate["wiki"] for candidate in json.loads(out)["candidates"]},
            {"cycling"},
        )

    def test_route_uses_the_fetcher_by_default(self):
        with tempfile.TemporaryDirectory() as state:
            self._run(["build"], FIXTURES, state)
            code, out, err, fetcher = self._run_with(
                ["route", "https://example.com/watering/", "--json"],
                FIXTURES,
                state,
                lambda url, **kwargs: fetched(url, title="Watering"),
            )

        payload = json.loads(out)
        fetcher.assert_called_once_with("https://example.com/watering/")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertTrue(payload["fetched"]["ok"])
        self.assertEqual(payload["fetched"]["source"], "html")
        self.assertEqual(
            payload["final_url"], "https://example.com/watering/"
        )
        self.assertEqual(payload["fetched"]["title"], "Watering")
        self.assertEqual(payload["reliability"], "ok")

    def test_route_no_fetch_does_not_call_the_fetcher(self):
        with tempfile.TemporaryDirectory() as state:
            self._run(["build"], FIXTURES, state)
            code, out, err, fetcher = self._run_with(
                [
                    "route",
                    "https://example.com/watering/",
                    "--no-fetch",
                    "--json",
                ],
                FIXTURES,
                state,
                lambda url, **kwargs: fetched(url),
            )

        payload = json.loads(out)
        fetcher.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertFalse(payload["fetched"]["ok"])
        self.assertEqual(payload["fetched"]["error"], "fetch disabled")

    def test_title_overrides_a_fetched_title(self):
        with tempfile.TemporaryDirectory() as state:
            self._run(["build"], FIXTURES, state)
            code, out, err = self._run(
                [
                    "route",
                    "https://example.com/watering/",
                    "--title",
                    "Watering",
                    "--json",
                ],
                FIXTURES,
                state,
                fetcher=lambda url, **kwargs: fetched(
                    url, title="Just a moment...", title_noisy=True
                ),
            )

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(payload["fetched"]["title"], "Watering")
        self.assertEqual(payload["fetched"]["error"], "")
        self.assertEqual(payload["reliability"], "ok")

    def test_route_without_an_index_reports_one(self):
        with tempfile.TemporaryDirectory() as state:
            code, out, err = self._run(
                ["route", "https://example.com/watering/", "--json"],
                FIXTURES,
                state,
            )

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "routing index missing: run build\n")

    def test_route_with_a_stale_index_warns_and_still_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes = Path(tmp) / "notes"
            shutil.copytree(FIXTURES, notes)
            state = Path(tmp) / "state"
            code, _, _ = self._run(["build"], notes, state)
            self.assertEqual(code, 0)

            page = notes / "garden" / "topics" / "soil.md"
            stamp = 1_700_000_000_000_000_000
            os.utime(page, ns=(stamp, stamp))

            code, out, err = self._run(
                ["route", "https://example.com/watering/", "--json"],
                notes,
                state,
            )

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(err, "warning: index is stale; run build\n")
        self.assertTrue(payload["candidates"])

    def test_route_without_environment_reports_two(self):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["route", "https://example.com/watering/", "--json"])

        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("WIKI_ROUTER_NOTES", err.getvalue())


class EvalCommandTests(unittest.TestCase):
    def _run(self, args, notes, state):
        environ = {
            "WIKI_ROUTER_NOTES": str(notes),
            "WIKI_ROUTER_HOME": str(state),
        }
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, environ, clear=True):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_eval_json_on_the_committed_fixture(self):
        with tempfile.TemporaryDirectory() as state:
            self._run(["build"], FIXTURES, state)
            code, out, err = self._run(["eval", "--json"], FIXTURES, state)

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(payload["total"], 5)
        self.assertEqual(payload["hit_at_1"], 5)
        self.assertEqual(payload["hit_at_top"], 5)
        self.assertEqual(
            Path(payload["fixture"]).resolve(),
            (FIXTURES.parent / "eval.json").resolve(),
        )

    def test_eval_returns_one_when_a_case_misses(self):
        with tempfile.TemporaryDirectory() as state:
            self._run(["build"], FIXTURES, state)
            with tempfile.TemporaryDirectory() as tmp:
                fixture = Path(tmp) / "eval.json"
                fixture.write_text(
                    json.dumps(
                        {
                            "cases": [
                                {
                                    "url": "https://example.com/watering/",
                                    "title": "Watering",
                                    "acceptable": ["garden/nowhere.md"],
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                code, out, err = self._run(
                    ["eval", "--fixture", str(fixture), "--json"],
                    FIXTURES,
                    state,
                )

        payload = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(err, "")
        self.assertEqual(payload["hit_at_top"], 0)
        self.assertEqual(payload["cases"][0]["rank"], 0)

    def test_eval_with_a_missing_fixture_names_the_path(self):
        with tempfile.TemporaryDirectory() as state:
            self._run(["build"], FIXTURES, state)
            with tempfile.TemporaryDirectory() as tmp:
                missing = Path(tmp) / "absent.json"
                code, out, err = self._run(
                    ["eval", "--fixture", str(missing)], FIXTURES, state
                )

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, f"eval fixture not found: {missing}\n")

    def test_eval_text_prints_the_fixture_path_and_summary(self):
        with tempfile.TemporaryDirectory() as state:
            self._run(["build"], FIXTURES, state)
            code, out, err = self._run(["eval"], FIXTURES, state)

        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(out.count("fixture:"), 1)
        self.assertTrue(lines[0].startswith("fixture: "))
        self.assertEqual(
            Path(lines[0].split("fixture: ", 1)[1]).resolve(),
            (FIXTURES.parent / "eval.json").resolve(),
        )
        self.assertIn("ok   #1   https://example.com/watering/", out)
        self.assertEqual(lines[-1], "hit@1 5/5 · hit@5 5/5")

    def test_eval_without_an_index_reports_one(self):
        with tempfile.TemporaryDirectory() as state:
            code, out, err = self._run(["eval"], FIXTURES, state)

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "routing index missing: run build\n")

    def test_eval_without_environment_reports_two(self):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["eval", "--json"])

        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("WIKI_ROUTER_NOTES", err.getvalue())


class AppendCommandTests(unittest.TestCase):
    def _setup(self, tmp):
        notes = tmp / "notes"
        shutil.copytree(FIXTURES, notes)
        return notes, tmp / "state"

    def _build(self, notes, state, pod_base=None):
        environ = {
            "WIKI_ROUTER_NOTES": str(notes),
            "WIKI_ROUTER_HOME": str(state),
        }
        if pod_base is not None:
            environ["WIKI_ROUTER_POD_BASE"] = pod_base
        with mock.patch.dict(os.environ, environ, clear=True):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = main(["build"])
        self.assertEqual(code, 0)

    def _run(self, args, notes, state, fetcher=None, pod_base=None):
        if fetcher is None:

            def fetcher(url, **kwargs):
                return fetched(url, title="Watering")

        environ = {
            "WIKI_ROUTER_NOTES": str(notes),
            "WIKI_ROUTER_HOME": str(state),
        }
        if pod_base is not None:
            environ["WIKI_ROUTER_POD_BASE"] = pod_base
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, environ, clear=True):
            with mock.patch(
                "wikirc.cli.fetch", side_effect=fetcher
            ) as patched:
                with redirect_stdout(out), redirect_stderr(err):
                    code = main(args)
        return code, out.getvalue(), err.getvalue(), patched

    def test_json_dry_run_reports_not_applied_and_leaves_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes, state = self._setup(Path(tmp))
            self._build(notes, state)
            page = notes / "garden" / "watering.md$.txt"
            before = page.read_bytes()

            code, out, err, fetcher = self._run(
                [
                    "append",
                    "https://example.com/new-article",
                    "--page",
                    "watering.md",
                    "--json",
                ],
                notes,
                state,
            )
            after = page.read_bytes()

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(before, after)
        self.assertEqual(
            sorted(payload),
            [
                "already_present",
                "applied",
                "bullet",
                "diff",
                "id",
                "ok",
                "page",
                "section",
            ],
        )
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["already_present"])
        self.assertFalse(payload["applied"])
        self.assertEqual(payload["page"], "garden/watering.md")
        self.assertEqual(payload["id"], "watering.md")
        self.assertEqual(
            payload["bullet"],
            "- [Watering](https://example.com/new-article)",
        )
        self.assertEqual(payload["section"], "Watering")
        self.assertIn(
            "+- [Watering](https://example.com/new-article)", payload["diff"]
        )
        fetcher.assert_called_once_with("https://example.com/new-article")

    def test_apply_writes_once_and_rerun_reports_already_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes, state = self._setup(Path(tmp))
            self._build(notes, state)
            page = notes / "garden" / "watering.md$.txt"
            args = [
                "append",
                "https://example.com/new-article",
                "--page",
                "watering.md",
                "--json",
                "--apply",
            ]

            code, out, err, _ = self._run(args, notes, state)
            text = page.read_text(encoding="utf-8")
            code_again, out_again, err_again, _ = self._run(
                args, notes, state
            )
            after = page.read_text(encoding="utf-8")

        first = json.loads(out)
        second = json.loads(out_again)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertTrue(first["ok"])
        self.assertTrue(first["applied"])
        self.assertIn(first["bullet"], text.splitlines())
        self.assertEqual(text.count(first["bullet"]), 1)
        self.assertEqual(after, text)
        self.assertEqual(code_again, 1)
        self.assertEqual(err_again, "")
        self.assertFalse(second["ok"])
        self.assertTrue(second["already_present"])
        self.assertFalse(second["applied"])

    def test_unknown_page_reports_the_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes, state = self._setup(Path(tmp))
            self._build(notes, state)

            code, out, err, fetcher = self._run(
                [
                    "append",
                    "https://example.com/new-article",
                    "--page",
                    "nope.md",
                    "--json",
                ],
                notes,
                state,
            )

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "page not found: nope.md\n")
        fetcher.assert_not_called()

    def test_page_resolution_accepts_qualified_id_label_and_subject(self):
        pod_base = "https://pod.example.com/pod/notes"
        with tempfile.TemporaryDirectory() as tmp:
            notes, state = self._setup(Path(tmp))
            self._build(notes, state, pod_base=pod_base)

            for query in (
                "garden/watering.md",
                "Watering",
                f"{pod_base}/garden/watering.md",
            ):
                with self.subTest(query=query):
                    code, out, err, _ = self._run(
                        [
                            "append",
                            "https://example.com/new-article",
                            "--page",
                            query,
                            "--json",
                        ],
                        notes,
                        state,
                        pod_base=pod_base,
                    )
                    payload = json.loads(out)
                    self.assertEqual(code, 0)
                    self.assertEqual(err, "")
                    self.assertEqual(payload["id"], "watering.md")
                    self.assertFalse(payload["applied"])

    def test_title_option_wins_and_skips_the_fetcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes, state = self._setup(Path(tmp))
            self._build(notes, state)

            code, out, err, fetcher = self._run(
                [
                    "append",
                    "https://example.com/new-article",
                    "--page",
                    "watering.md",
                    "--title",
                    "Given title",
                    "--json",
                ],
                notes,
                state,
            )

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(
            payload["bullet"],
            "- [Given title](https://example.com/new-article)",
        )
        fetcher.assert_not_called()

    def test_slug_title_is_used_when_the_fetch_has_no_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes, state = self._setup(Path(tmp))
            self._build(notes, state)

            code, out, err, _ = self._run(
                [
                    "append",
                    "https://example.com/new-article",
                    "--page",
                    "watering.md",
                    "--json",
                ],
                notes,
                state,
                fetcher=lambda url, **kwargs: fetched(url),
            )

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(
            payload["bullet"],
            "- [new article](https://example.com/new-article)",
        )

    def test_note_and_section_options_shape_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes, state = self._setup(Path(tmp))
            self._build(notes, state)

            code, out, err, _ = self._run(
                [
                    "append",
                    "https://example.com/new-article",
                    "--page",
                    "watering.md",
                    "--note",
                    "Read later",
                    "--section",
                    "Watering",
                    "--json",
                ],
                notes,
                state,
            )

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(payload["section"], "Watering")
        self.assertEqual(
            payload["bullet"],
            "- [Watering](https://example.com/new-article) — Read later",
        )

    def test_plain_dry_run_prints_bullet_section_and_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes, state = self._setup(Path(tmp))
            self._build(notes, state)

            code, out, err, _ = self._run(
                [
                    "append",
                    "https://example.com/new-article",
                    "--page",
                    "watering.md",
                ],
                notes,
                state,
            )

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("section: Watering", out)
        self.assertIn(
            "bullet: - [Watering](https://example.com/new-article)", out
        )
        self.assertIn("--- a/watering.md", out)
        self.assertIn("+++ b/watering.md", out)
        self.assertNotIn("applied", out)

    def test_append_without_an_index_reports_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes, state = self._setup(Path(tmp))
            code, out, err, _ = self._run(
                [
                    "append",
                    "https://example.com/new-article",
                    "--page",
                    "watering.md",
                    "--json",
                ],
                notes,
                state,
            )

        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "routing index missing: run build\n")

    def test_append_without_environment_reports_two(self):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(
                    [
                        "append",
                        "https://example.com/new-article",
                        "--page",
                        "watering.md",
                        "--json",
                    ]
                )

        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("WIKI_ROUTER_NOTES", err.getvalue())


class UsageTests(unittest.TestCase):
    def test_unknown_subcommand_exits_two(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main(["nope"])
        self.assertEqual(caught.exception.code, 2)

    def test_no_subcommand_exits_two(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main([])
        self.assertEqual(caught.exception.code, 2)


class CapabilityCliTests(unittest.TestCase):
    def _run(self, args, notes, state):
        environ = {
            "WIKI_ROUTER_NOTES": str(notes),
            "WIKI_ROUTER_HOME": str(state),
        }
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, environ, clear=True):
            with redirect_stdout(out), redirect_stderr(err):
                code = main(args)
        return code, out.getvalue(), err.getvalue()

    def _fixture(self, directory, cases):
        path = Path(directory) / "eval.json"
        path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
        return path

    def test_a_failing_capability_is_reported_and_still_fails(self):
        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as tmp:
            self._run(["build"], FIXTURES, state)
            fixture = self._fixture(tmp, [
                {"url": "https://example.com/watering/", "title": "Watering",
                 "acceptable": ["garden/watering.md"]},
                {"url": "https://example.com/nothing/", "title": "Nothing",
                 "acceptable": ["garden/absent.md"],
                 "capability": "routing a page that does not exist yet"},
            ])
            code, out, _ = self._run(["eval", "--fixture", str(fixture)], FIXTURES, state)

        self.assertEqual(code, 1)
        self.assertIn("capabilities the fixture covers that are not met:", out)
        self.assertIn("routing a page that does not exist yet", out)
        self.assertIn("covers: routing a page that does not exist yet", out)

    def test_an_unclassified_miss_is_called_out(self):
        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as tmp:
            self._run(["build"], FIXTURES, state)
            fixture = self._fixture(tmp, [
                {"url": "https://example.com/nothing/", "title": "Nothing",
                 "acceptable": ["garden/absent.md"]},
            ])
            code, out, _ = self._run(["eval", "--fixture", str(fixture)], FIXTURES, state)

        self.assertEqual(code, 1)
        self.assertIn("1 unclassified miss(es)", out)

    def test_a_met_capability_is_not_reported_as_unmet(self):
        with tempfile.TemporaryDirectory() as state, tempfile.TemporaryDirectory() as tmp:
            self._run(["build"], FIXTURES, state)
            fixture = self._fixture(tmp, [
                {"url": "https://example.com/watering/", "title": "Watering",
                 "acceptable": ["garden/watering.md"],
                 "capability": "routing an exact label"},
            ])
            code, out, _ = self._run(["eval", "--fixture", str(fixture)], FIXTURES, state)

        self.assertEqual(code, 0)
        self.assertNotIn("are not met", out)
