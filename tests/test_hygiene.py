"""Enforce the "no machine-specific values" rule from AGENTS.md.

AGENTS.md says:

    No machine-specific values. No absolute paths, no home directories, no
    hostnames in code or fixtures. Configuration arrives through the environment;
    fixtures are synthetic.

This repository is published, so a stray absolute path, a personal hostname or a
token in a fixture would publish somebody's environment. Until this module there
was nothing checking the rule, which made it aspirational.

Scope is exactly what git would publish: every tracked file plus every untracked
file that is not ignored (``git ls-files`` and ``git ls-files --others
--exclude-standard``). When the scan root is not itself a git work tree — the
temporary directories the tests below build — every file under it is walked
instead, with the same skip rules. ``.git/``, ``__pycache__/`` and virtualenv
directories are never entered, and known binary extensions are skipped.

This module is the one path exempt from its own scan: it necessarily contains the
literals it searches for. ``SELF`` is declared explicitly and a test pins the
exemption to exactly one file.

Nothing here reads outside the scan root. ``discover_files`` resolves every
candidate and raises ``ValueError`` rather than following a symlink out of the
tree.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

# Directories that are never published, so never scanned.
SKIP_DIRS = frozenset({
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
})

# Binary payloads are skipped by extension instead of being decoded.
SKIP_EXTENSIONS = frozenset({
    ".pyc", ".pyo", ".so", ".o", ".a", ".dylib", ".dll", ".exe",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tif", ".tiff",
    ".pdf", ".zip", ".gz", ".bz2", ".xz", ".tar", ".woff", ".woff2", ".ttf",
    ".otf", ".eot", ".mp3", ".mp4", ".ogg", ".wav", ".db", ".sqlite",
})


# --- Rule 1: absolute filesystem paths ---------------------------------------
#
# The POSIX prefixes carry a trailing separator and a lookbehind that refuses a
# word character or a dot before them. That keeps a URL path (``/tmp`` after a
# host) and an identifier (``chroot/bin``) from matching, and leaves a relative
# fragment such as ``../tmp/`` alone because it is not absolute. ``~/`` is
# deliberately not matched: it is a shell expansion of the user's own home, the
# way README documents configuration, not a hard-coded absolute location.
_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_.])(?:/home/|/data/|/Users/|/root/|/tmp/)"
    r"|(?<![A-Za-z0-9_])[A-Za-z]:\\"
)


# --- Rule 2: hostnames -------------------------------------------------------
#
# Two conservative shapes are extracted, and nothing else:
#
#   * ``https?://host`` — anything after a scheme, up to the first character
#     that cannot appear in a host (``:`` port, ``/`` path, ``{`` interpolation).
#     An optional ``user:pass@`` prefix is stepped over.
#   * ``www.host`` — a bare www-prefixed host outside those URL matches.
#
# A bare host with no scheme and no ``www.`` (``api.crossref.org`` in prose) is
# NOT extracted: matching free-standing dotted words would fire on every
# filename, version number and sentence-ending abbreviation. A host written
# immediately before an f-string interpolation (``https://site{offset}.example``)
# is built at run time, so there is no literal host to judge and it is skipped —
# a knowing false negative, since the alternative is flagging every f-string
# URL template as a hostname. False negatives are preferred to a guard that
# cries wolf, but every scheme-qualified or www-qualified literal host must be
# on the allowlist below or the scan fails.
_URL_HOST = re.compile(r"https?://(?:[^\s/@]*@)?([A-Za-z0-9][A-Za-z0-9.-]*)")
_BARE_WWW_HOST = re.compile(r"\bwww\.[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]")

# Allowlisted domains, checked as the host itself or any subdomain of it, so
# ``example`` covers both the bare label and the synthetic fixture hosts built
# on it (``shop.example``, ``press.bookshop.example``). Each entry is public,
# holds no personal identity, and exists because something in the tree
# legitimately names it.
ALLOWED_DOMAINS = {
    # Documentation and test names reserved by RFC 2606 / RFC 6761. They can
    # never resolve, so they cannot leak an environment.
    "example.com": "RFC 2606 example domain used throughout the fixtures",
    "example.org": "RFC 2606 example domain used throughout the fixtures",
    "example.net": "RFC 2606 example domain used throughout the fixtures",
    "example": "RFC 6761 reserves the example. TLD for documentation, so hosts like shop.example can never resolve",
    "invalid": "RFC 2606 reserved TLD, guaranteed unresolvable",
    "test": "RFC 2606 reserved TLD used by the scoring fixtures (other.test, elsewhere.test)",

    # Hosts named by the task brief.
    "github.com": "public forge; the repository lives there",
    "raw.githubusercontent.com": "public raw-content host",
    "pypi.org": "public package index",

    # Public reference sources the scoring and fetch tests legitimately name.
    "wikipedia.org": "reference corpus host (en., de. subdomains included)",
    "doi.org": "DOI resolver; dx.doi.org is a subdomain",
    "archive.org": "book resolution source used by wikirc/books.py",
    "openlibrary.org": "book resolution source used by wikirc/books.py",
    "youtube.com": "reference source named by the scoring tests",
    "youtu.be": "reference source named by the scoring tests",
    "wikidata.org": "reference source named by the scoring tests",
    "wikimedia.org": "reference source named by the scoring tests",

    # Additional public hosts the current tree names, none of them personal.
    "w3.org": "RDF/RDFS/OWL vocabulary namespace prefixes in the Turtle fixtures",
    "crossref.org": "the Crossref REST API that wikirc/metadata.py calls",
    "shields.io": "status badge images in README.md",
    "amazon.com": "retailer label in the synthetic book-URL fixtures",
    "amazon.co.uk": "retailer label in the synthetic book-URL fixtures (smile.amazon.co.uk)",
    "penguinrandomhouse.com": "retailer label in the synthetic book-URL fixtures",
}


def allowed_host(host):
    """True when host is the exact allowlisted name or a subdomain of one."""
    host = host.lower().rstrip(".")
    for domain in ALLOWED_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return True
    return False


# --- Rule 3: email addresses -------------------------------------------------
#
# A conservative address shape: local part, ``@``, dotted domain, alphabetic
# TLD of at least two characters. Decoration such as ``@unittest.skip`` has no
# dotted domain and does not match.
_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"
)


# --- Rule 4: credentials -----------------------------------------------------
#
# Marker prefixes are matched as credentials in their own right. A long
# high-entropy run is matched separately: 40+ hex characters (a sha1/sha256 or
# longer digest, which has no other reading in prose), or a 40+ base64 run that
# carries ``+`` or ``=`` padding plus both a digit and an uppercase letter —
# the tighter base64 test keeps long identifiers and URL paths from matching.
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
_CREDENTIAL_MARKERS = (
    re.compile(r"\bghp_[A-Za-z0-9]{8,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bAKIA[0-9A-Z]*\b"),
)
_HEX_BLOB = re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{40,}(?![0-9A-Za-z])")
_B64_BLOB = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}")

# Digests that are fixtures on purpose. Empty today: the tree holds no long
# hex or base64 blob. Add an entry only together with the fixture that needs it
# and a note saying why it cannot be replaced by synthetic text.
ALLOWED_DIGESTS = frozenset()


# --- Rule 5: pod-specific names ----------------------------------------------
#
# A personal Solid pod must never appear, so its storage directory name and its
# hostname shape are named outright. The hostname shape needs at least two
# labels after ``pod.`` so ordinary prose ("the pod. Then") cannot match; the
# remainder is then checked against the same allowlist as rule 2, which lets the
# synthetic ``pod.example.com`` through.
_POD_STORAGE = re.compile(r"\bsolid-data\b")
_POD_HOST = re.compile(r"\bpod\.[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

ABSOLUTE_PATH = "absolute path"
HOSTNAME = "hostname"
EMAIL = "email"
CREDENTIAL = "credential"
POD_HOST = "pod hostname"
POD_STORAGE_NAME = "pod storage literal"


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    kind: str
    text: str

    def render(self):
        return f"{self.path}:{self.line}: {self.kind}: {self.text}"


def _b64_is_secret(candidate):
    if candidate in ALLOWED_DIGESTS:
        return False
    if "+" not in candidate and not candidate.endswith("="):
        return False
    return any(ch.isdigit() for ch in candidate) and any(
        ch.isupper() for ch in candidate
    )


def scan_line(line, path="<text>", lineno=1):
    """Yield every violation on one physical line."""
    reported = []

    for match in _ABSOLUTE_PATH.finditer(line):
        reported.append(Violation(path, lineno, ABSOLUTE_PATH, match.group(0)))

    url_spans = []
    for match in _URL_HOST.finditer(line):
        url_spans.append(match.span())
        host = match.group(1).rstrip(".")
        # ``https://site{offset}.example`` builds its host at run time; there is
        # no literal host to judge, so only the span is recorded.
        if match.end(1) < len(line) and line[match.end(1)] == "{":
            continue
        if not allowed_host(host):
            reported.append(Violation(path, lineno, HOSTNAME, match.group(0)))

    for match in _BARE_WWW_HOST.finditer(line):
        if any(start <= match.start() < end for start, end in url_spans):
            continue
        if not allowed_host(match.group(0)):
            reported.append(Violation(path, lineno, HOSTNAME, match.group(0)))

    for match in _EMAIL.finditer(line):
        reported.append(Violation(path, lineno, EMAIL, match.group(0)))

    for match in _PRIVATE_KEY.finditer(line):
        reported.append(Violation(path, lineno, CREDENTIAL, match.group(0)))

    for pattern in _CREDENTIAL_MARKERS:
        for match in pattern.finditer(line):
            reported.append(Violation(path, lineno, CREDENTIAL, match.group(0)))

    for match in _HEX_BLOB.finditer(line):
        if match.group(0) not in ALLOWED_DIGESTS:
            reported.append(Violation(path, lineno, CREDENTIAL, match.group(0)))

    for match in _B64_BLOB.finditer(line):
        if _b64_is_secret(match.group(0)):
            reported.append(Violation(path, lineno, CREDENTIAL, match.group(0)))

    for match in _POD_STORAGE.finditer(line):
        reported.append(Violation(path, lineno, POD_STORAGE_NAME, match.group(0)))

    for match in _POD_HOST.finditer(line):
        remainder = match.group(0)[len("pod."):]
        if not allowed_host(remainder):
            reported.append(Violation(path, lineno, POD_HOST, match.group(0)))

    # One report per (kind, text, position); the URL and www shapes can overlap.
    seen = set()
    for violation in reported:
        key = (violation.kind, violation.text)
        if key not in seen:
            seen.add(key)
            yield violation


def scan_text(text, path="<text>"):
    """Yield violations in a whole document, one physical line at a time."""
    for lineno, line in enumerate(text.splitlines(), 1):
        yield from scan_line(line, path, lineno)


def _git_output(root, *args):
    completed = subprocess.run(
        ("git", "-C", str(root)) + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    return completed.stdout


def _git_toplevel(root):
    """The work-tree top level of root, or None when git cannot answer."""
    try:
        output = _git_output(root, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.CalledProcessError):
        return None
    decoded = output.decode("utf-8", "replace").strip()
    return Path(decoded).resolve() if decoded else None


def _publishable(path, root):
    """True for a regular file inside root that a public tree would ship."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"refusing to scan outside the root: {path} -> {resolved}")
    relative = resolved.relative_to(root)
    if any(part in SKIP_DIRS for part in relative.parts[:-1]):
        return False
    if path.suffix.lower() in SKIP_EXTENSIONS:
        return False
    return path.is_file()


def discover_files(root):
    """Every file git would publish under root, sorted by path.

    A git work tree contributes its tracked files plus its untracked,
    non-ignored files. Anything else — the temporary trees the tests build — is
    walked with the same skip rules.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    if _git_toplevel(root) == root:
        names = set()
        for args in (
            ("ls-files", "-z"),
            ("ls-files", "-z", "--others", "--exclude-standard"),
        ):
            for name in _git_output(root, *args).split(b"\0"):
                if name:
                    names.add(name.decode("utf-8", "surrogateescape"))
        candidates = [root / name for name in names]
    else:
        candidates = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            for filename in filenames:
                candidates.append(Path(dirpath) / filename)

    files = [path for path in candidates if _publishable(path, root)]
    return sorted(files, key=lambda path: path.as_posix())


def scan_root(root):
    """Scan every published file under root; return violations sorted by path."""
    root = Path(root).resolve()
    violations = []
    for path in discover_files(root):
        if path.resolve() == SELF:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # An undeclared binary: skipped exactly like the known extensions.
            continue
        violations.extend(scan_text(text, path.relative_to(root).as_posix()))
    return sorted(violations, key=lambda v: (v.path, v.line, v.kind, v.text))


# --- Negative tests: the guard must catch each rule --------------------------
#
# These build their own files in temporary directories. They never read the
# notes tree and never touch the network.


def _write(root, name, text):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _scan(root):
    return scan_root(Path(root))


class CatchesAbsolutePathsTests(unittest.TestCase):
    def test_every_watched_prefix_is_reported(self):
        cases = (
            '/home/alice/notes.md',
            '/data/local/notes.md',
            '/Users/alice/notes',
            '/root/.config/wiki',
            '/tmp/a.md',
            'C:\\Users\\alice\\notes',
        )
        for literal in cases:
            with self.subTest(literal=literal), \
                    tempfile.TemporaryDirectory() as root:
                _write(root, "fixture.md", f"path: {literal}\n")
                violations = _scan(root)
                self.assertEqual(1, len(violations), violations)
                self.assertEqual(ABSOLUTE_PATH, violations[0].kind)
                self.assertEqual(1, violations[0].line)
                self.assertEqual("fixture.md", violations[0].path)
                self.assertTrue(
                    literal.startswith(violations[0].text),
                    f"{violations[0].text!r} is not the matched prefix of {literal!r}",
                )

    def test_relative_and_home_relative_paths_are_not_reported(self):
        with tempfile.TemporaryDirectory() as root:
            _write(
                root,
                "note.md",
                "See ./notes/x.md and ../tmp/y.md and ~/notes and /usr/bin/env\n",
            )
            self.assertEqual([], _scan(root))


class CatchesHostnamesTests(unittest.TestCase):
    def test_personal_and_cloud_hosts_are_reported(self):
        cases = (
            'https://wiki.somebody-else.org/notes',
            'https://alice-macbook.local/wiki',
            'http://192.168.1.10:8080/wiki',
            'https://my-bucket.s3.amazonaws.com/x',
            'https://gist.github.io/private',
            'www.alicedomain.dev',
        )
        for literal in cases:
            with self.subTest(literal=literal), \
                    tempfile.TemporaryDirectory() as root:
                _write(root, "fixture.md", f"link: {literal}\n")
                violations = _scan(root)
                self.assertEqual(1, len(violations), violations)
                self.assertEqual(HOSTNAME, violations[0].kind)
                self.assertTrue(violations[0].text)

    def test_allowlisted_hosts_pass(self):
        text = "\n".join((
            "https://example.com/a",
            "https://www.Example.com/b",
            "https://blog.example.org/c",
            "https://portal.example.net/d",
            "http://example/e",
            "https://github.com/owner/repo",
            "https://raw.githubusercontent.com/owner/repo/main/x",
            "https://pypi.org/project/x",
            "https://en.wikipedia.org/wiki/Solar",
            "https://de.wikipedia.org/wiki/Solar",
            "https://doi.org/10.1234/x",
            "https://dx.doi.org/10.1234/x",
            "https://archive.org/details/x",
            "https://openlibrary.org/isbn/1",
            "https://www.youtube.com/watch?v=x",
            "https://youtu.be/x",
            "https://www.wikidata.org/wiki/Q1",
            "https://commons.wikimedia.org/wiki/File:x",
            "https://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "https://api.crossref.org/works/10.1234/x",
            "https://img.shields.io/badge/x",
            "https://www.amazon.com/dp/0000000000",
            "https://smile.amazon.co.uk/gp/product/0000000000",
            "https://www.penguinrandomhouse.com/books/000000/",
            "https://other.test/elsewhere",
            "https://elsewhere.test/three",
            "https://host.invalid/x",
            "",
        ))
        with tempfile.TemporaryDirectory() as root:
            _write(root, "fixture.md", text)
            self.assertEqual([], _scan(root))

    def test_interpolated_hosts_are_not_literals(self):
        with tempfile.TemporaryDirectory() as root:
            _write(
                root,
                "fixture.md",
                'url = f"https://site{n}.example.com/page/{id}"\n'
                'api = f"https://{host}/wiki/solar"\n',
            )
            self.assertEqual([], _scan(root))


class CatchesEmailsTests(unittest.TestCase):
    def test_email_address_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "fixture.md", "contact: alice.wood@mail-provider.example\n")
            violations = _scan(root)
            self.assertEqual(1, len(violations), violations)
            self.assertEqual(EMAIL, violations[0].kind)
            self.assertEqual("alice.wood@mail-provider.example", violations[0].text)

    def test_decorator_is_not_an_email(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "fixture.py", "@staticmethod\ndef f():\n    pass\n")
            self.assertEqual([], _scan(root))


class CatchesCredentialsTests(unittest.TestCase):
    def test_private_key_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            _write(
                root,
                "id_rsa",
                "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----\n",
            )
            violations = _scan(root)
            self.assertEqual(1, len(violations), violations)
            self.assertEqual(CREDENTIAL, violations[0].kind)
            self.assertIn("PRIVATE KEY", violations[0].text)

    def test_token_prefixes_are_reported(self):
        for literal in (
            "ghp_0123456789abcdefghij",
            "github_pat_11ABCDEFG0123456789",
            "sk-live-0123456789abcdef",
            "AKIAIOSFODNN7EXAMPLE",
        ):
            with self.subTest(literal=literal), \
                    tempfile.TemporaryDirectory() as root:
                _write(root, "config.env", f"TOKEN={literal}\n")
                violations = _scan(root)
                self.assertEqual(1, len(violations), violations)
                self.assertEqual(CREDENTIAL, violations[0].kind)

    def test_long_digest_is_reported(self):
        digest = "ab" * 32  # 64 hex characters, the sha256 shape
        with tempfile.TemporaryDirectory() as root:
            _write(root, "fixture.txt", f"sha256: {digest}\n")
            violations = _scan(root)
            self.assertEqual(1, len(violations), violations)
            self.assertEqual(CREDENTIAL, violations[0].kind)

    def test_long_base64_blob_is_reported(self):
        blob = "AKf8Qm2xTz9Lp4Rv7Wc1Yb6Nd3Hs0Jk5Gu+eQ2sW7Zp=="
        self.assertGreaterEqual(len(blob.rstrip("=")), 40)
        with tempfile.TemporaryDirectory() as root:
            _write(root, "fixture.txt", f"blob: {blob}\n")
            violations = _scan(root)
            self.assertEqual(1, len(violations), violations)
            self.assertEqual(CREDENTIAL, violations[0].kind)

    def test_ordinary_identifiers_are_not_digests(self):
        with tempfile.TemporaryDirectory() as root:
            _write(
                root,
                "fixture.py",
                "respect_existing_links=respect_existing_links\n"
                "test_config_without_home_reports_config_error = 1\n",
            )
            self.assertEqual([], _scan(root))


class CatchesPodNamesTests(unittest.TestCase):
    def test_solid_data_literal_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "note.md", "mirror of the solid-data tree\n")
            violations = _scan(root)
            self.assertEqual(1, len(violations), violations)
            self.assertEqual(POD_STORAGE_NAME, violations[0].kind)

    def test_personal_pod_hostname_is_reported(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "note.md", "stored at pod.somebody-else.org\n")
            violations = _scan(root)
            kinds = {v.kind for v in violations}
            self.assertIn(POD_HOST, kinds, violations)
            self.assertTrue(all(v.text.startswith("pod.") for v in violations))

    def test_synthetic_pod_hostname_passes(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "note.md", "stored at pod.example.com\n")
            self.assertEqual([], _scan(root))


# --- Discovery and confinement ----------------------------------------------


class DiscoveryTests(unittest.TestCase):
    def test_caches_and_binaries_are_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "wikirc/module.py", "x = 1\n")
            _write(root, "__pycache__/module.cpython-313.pyc", "binary")
            _write(root, "wikirc/__pycache__/module.cpython-313.pyc", "binary")
            _write(root, ".venv/lib/site.py", "x = 1\n")
            _write(root, "images/diagram.png", "binary")
            names = {path.name for path in discover_files(Path(root))}
            self.assertEqual({"module.py"}, names)

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_tracked_and_untracked_files_are_discovered(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            subprocess.run(
                ["git", "init", "-q", str(root)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _write(root, "tracked.txt", "one\n")
            _write(root, ".gitignore", "ignored.txt\n")
            _write(root, "new.txt", "two\n")
            _write(root, "ignored.txt", "three\n")
            subprocess.run(
                ["git", "-C", str(root), "add", "tracked.txt", ".gitignore"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["git", "-C", str(root), "-c", "user.email=t@example",
                 "-c", "user.name=T", "commit", "-qm", "init"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            names = {path.name for path in discover_files(root)}
            self.assertIn("tracked.txt", names)
            self.assertIn("new.txt", names)
            self.assertNotIn("ignored.txt", names)

    def test_symlink_outside_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as outside:
            target = _write(outside, "secret.txt", "/home/alice/notes.md\n")
            _write(root, "normal.md", "fine\n")
            os.symlink(target, Path(root) / "escape.txt")
            with self.assertRaises(ValueError):
                discover_files(Path(root))


class RepositoryTests(unittest.TestCase):
    """The real tree. These are the assertions the rule depends on."""

    def test_repository_has_no_machine_specific_values(self):
        violations = scan_root(REPO_ROOT)
        if violations:
            self.fail(
                "machine-specific values found in published files:\n"
                + "\n".join(violation.render() for violation in violations)
            )

    def test_scan_is_bounded_and_confined(self):
        started = time.monotonic()
        violations = scan_root(REPO_ROOT)
        elapsed = time.monotonic() - started

        self.assertIsInstance(violations, list)
        self.assertLess(elapsed, 10.0, "the whole-tree scan should take seconds")

        root = REPO_ROOT.resolve()
        files = discover_files(root)
        self.assertLess(len(files), 200)
        for path in files:
            self.assertTrue(
                path.resolve().is_relative_to(root),
                f"{path} resolves outside the repository",
            )

    def test_only_this_module_is_exempt(self):
        exempt = [path for path in discover_files(REPO_ROOT) if path.resolve() == SELF]
        self.assertEqual([SELF], exempt)
        self.assertEqual("tests/test_hygiene.py", SELF.relative_to(REPO_ROOT).as_posix())


if __name__ == "__main__":
    unittest.main()
