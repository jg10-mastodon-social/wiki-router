import tempfile
import unittest
from pathlib import Path

from wikirc.config import ConfigError, load_config


class LoadConfigTests(unittest.TestCase):
    def test_only_notes_names_home_as_missing(self):
        with tempfile.TemporaryDirectory() as notes:
            environ = {"WIKI_ROUTER_NOTES": notes}
            with self.assertRaises(ConfigError) as caught:
                load_config(environ)
        self.assertEqual(str(caught.exception), "WIKI_ROUTER_HOME is not set")

    def test_only_state_names_notes_as_missing(self):
        with tempfile.TemporaryDirectory() as state:
            environ = {"WIKI_ROUTER_HOME": state}
            with self.assertRaises(ConfigError) as caught:
                load_config(environ)
        self.assertEqual(str(caught.exception), "WIKI_ROUTER_NOTES is not set")

    def test_empty_notes_is_missing(self):
        with tempfile.TemporaryDirectory() as state:
            environ = {"WIKI_ROUTER_NOTES": "", "WIKI_ROUTER_HOME": state}
            with self.assertRaises(ConfigError) as caught:
                load_config(environ)
        self.assertIn("WIKI_ROUTER_NOTES", str(caught.exception))

    def test_both_required_paths_become_paths(self):
        with tempfile.TemporaryDirectory() as notes, tempfile.TemporaryDirectory() as state:
            config = load_config(
                {"WIKI_ROUTER_NOTES": notes, "WIKI_ROUTER_HOME": state}
            )
        self.assertEqual(config.notes, Path(notes))
        self.assertEqual(config.state, Path(state))

    def test_pod_base_absent_is_none(self):
        with tempfile.TemporaryDirectory() as notes, tempfile.TemporaryDirectory() as state:
            config = load_config(
                {"WIKI_ROUTER_NOTES": notes, "WIKI_ROUTER_HOME": state}
            )
        self.assertIsNone(config.pod_base)

    def test_empty_pod_base_is_none(self):
        with tempfile.TemporaryDirectory() as notes, tempfile.TemporaryDirectory() as state:
            config = load_config(
                {
                    "WIKI_ROUTER_NOTES": notes,
                    "WIKI_ROUTER_HOME": state,
                    "WIKI_ROUTER_POD_BASE": "",
                }
            )
        self.assertIsNone(config.pod_base)

    def test_pod_base_trailing_slashes_stripped(self):
        pod_base = "https://pod.example.com/pod/notes"
        with tempfile.TemporaryDirectory() as notes, tempfile.TemporaryDirectory() as state:
            config = load_config(
                {
                    "WIKI_ROUTER_NOTES": notes,
                    "WIKI_ROUTER_HOME": state,
                    "WIKI_ROUTER_POD_BASE": pod_base + "///",
                }
            )
        self.assertEqual(config.pod_base, pod_base)
