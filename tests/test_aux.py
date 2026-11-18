"""Report the auxiliary maps the router loaded, and refuse an unprovisioned one.

A state directory holds the routing index and two optional maps: synonyms and
redirects. Both are provisioned by hand, and a directory holding only the index
used to score silently with neither, so a synonym expansion and a redirect
simply vanished from the report. These tests pin the report that says which maps
were loaded, and the flag that refuses to score when one is absent.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from wikirc.cli import main
from wikirc.redirects import REDIRECTS_FILE
from wikirc.synonyms import SYNONYMS_FILE

FIXTURES = Path(__file__).parent / "fixtures" / "corpus"

SYNONYMS = {"foresight": "futures"}
REDIRECTS = {"garden/retired.md": "garden/watering.md"}


class AuxTestCase(unittest.TestCase):
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

    def _provision(self, tmp, synonyms=True, redirects=True):
        """Build the index, then write only the aux files asked for."""
        state = Path(tmp) / "state"
        code, _, err = self._run(["build"], FIXTURES, state)
        self.assertEqual(code, 0, err)
        if synonyms:
            (state / SYNONYMS_FILE).write_text(
                json.dumps(SYNONYMS), encoding="utf-8"
            )
        if redirects:
            (state / REDIRECTS_FILE).write_text(
                json.dumps(REDIRECTS), encoding="utf-8"
            )
        return state


class AuxReportTests(AuxTestCase):
    def test_both_files_present_report_loaded_in_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._provision(tmp)
            code, out, err = self._run(["eval", "--json"], FIXTURES, state)

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(
            payload["aux"], {"synonyms": "loaded", "redirects": "loaded"}
        )
        self.assertEqual(payload["hit_at_top"], 5)

    def test_both_files_present_report_loaded_in_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._provision(tmp)
            code, out, err = self._run(["eval"], FIXTURES, state)

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("synonyms loaded", out)
        self.assertIn("redirects loaded", out)
        self.assertEqual(out.splitlines()[-1], "hit@1 5/5 · hit@5 5/5")

    def test_only_synonyms_present_reports_redirects_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._provision(tmp, redirects=False)
            code, out, err = self._run(["eval", "--json"], FIXTURES, state)

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(
            payload["aux"], {"synonyms": "loaded", "redirects": "missing"}
        )
        self.assertEqual(payload["hit_at_top"], 5)

    def test_only_synonyms_present_names_redirects_missing_in_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._provision(tmp, redirects=False)
            code, out, err = self._run(["eval"], FIXTURES, state)

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("redirects missing", out)
        self.assertNotIn("synonyms missing", out)

    def test_only_redirects_present_reports_synonyms_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._provision(tmp, synonyms=False)
            code, out, err = self._run(["eval", "--json"], FIXTURES, state)

        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(
            payload["aux"], {"synonyms": "missing", "redirects": "loaded"}
        )

    def test_only_redirects_present_names_synonyms_missing_in_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._provision(tmp, synonyms=False)
            code, out, err = self._run(["eval"], FIXTURES, state)

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("synonyms missing", out)
        self.assertNotIn("redirects missing", out)

    def test_neither_present_still_scores_without_the_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._provision(tmp, synonyms=False, redirects=False)
            code, out, err = self._run(["eval"], FIXTURES, state)

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("synonyms missing", out)
        self.assertIn("redirects missing", out)
        self.assertIn("hit@1 5/5 · hit@5 5/5", out)


class RequireAuxTests(AuxTestCase):
    def test_a_missing_file_refuses_to_score_and_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._provision(tmp, redirects=False)
            code, out, err = self._run(
                ["eval", "--require-aux"], FIXTURES, state
            )

        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(len(err.splitlines()), 1)
        self.assertIn(REDIRECTS_FILE, err)
        self.assertNotIn(SYNONYMS_FILE, err)

    def test_both_missing_are_named_on_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._provision(tmp, synonyms=False, redirects=False)
            code, out, err = self._run(
                ["eval", "--require-aux"], FIXTURES, state
            )

        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(len(err.splitlines()), 1)
        self.assertIn(SYNONYMS_FILE, err)
        self.assertIn(REDIRECTS_FILE, err)

    def test_both_present_scores_and_prints_the_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._provision(tmp)
            code, out, err = self._run(
                ["eval", "--require-aux"], FIXTURES, state
            )

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("hit@1 5/5 · hit@5 5/5", out)

    def test_a_json_run_refuses_the_same_way(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = self._provision(tmp, synonyms=False)
            code, out, err = self._run(
                ["eval", "--require-aux", "--json"], FIXTURES, state
            )

        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn(SYNONYMS_FILE, err)


if __name__ == "__main__":
    unittest.main()
