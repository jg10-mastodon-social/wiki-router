import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from wikirc.cli import build_parser, main


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
