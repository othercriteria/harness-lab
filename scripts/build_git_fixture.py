"""Build trusted authored Git fixtures from pinned, licensed CPython source.

Only fixture construction uses host Git. Solver repositories are always handled
in isolation. This never executes the vendored code or a model submission.
"""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = Path("/bulk/dlk/local-harness/research/git-integration-001/upstream")
BUILD = Path("/bulk/dlk/local-harness/research/git-integration-001/fixture-build-v3")
STAMP = "2026-01-01T00:00:00+00:00"


def git(repo, *args):
    env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_AUTHOR_NAME": "Fixture Author",
        "GIT_AUTHOR_EMAIL": "author@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture Author",
        "GIT_COMMITTER_EMAIL": "author@example.invalid",
        "GIT_AUTHOR_DATE": STAMP,
        "GIT_COMMITTER_DATE": STAMP,
    }
    return (
        subprocess.check_output(
            ["git", "-C", str(repo), *args], env=env, stderr=subprocess.PIPE
        )
        .decode()
        .strip()
    )


def commit(repo, message):
    git(repo, "add", ".")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


PUBLIC_TESTS = """import io
import unittest
import configparser as cp
import service


class WriteContract(unittest.TestCase):
    def test_safe_roundtrip(self):
        p = cp.ConfigParser()
        p.read_dict({'s': {'z': 'last', 'a': 'first'}})
        out = io.StringIO()
        p.write(out)
        q = cp.ConfigParser()
        q.read_string(out.getvalue())
        self.assertEqual(dict(q['s']), dict(p['s']))

    def test_invalid_key_no_partial_output(self):
        p = cp.ConfigParser()
        p.read_dict({'safe': {'ok': '1'}, 'late': {'bad=key': '2'}})
        out = io.StringIO('prefix')
        out.seek(0, 2)
        with self.assertRaises((cp.Error, ValueError)):
            p.write(out)
        self.assertEqual(out.getvalue(), 'prefix')
        self.assertFalse(out.closed)

    def test_service_failure(self):
        p = cp.ConfigParser()
        p.read_dict({'s': {'bad\\nkey': 'x'}})
        out = io.StringIO()
        result = service.export(p, out)
        self.assertEqual(result, service.INVALID)
        self.assertEqual(out.getvalue(), '')
        self.assertFalse(out.closed)

    def test_per_parser_delimiters(self):
        p = cp.ConfigParser(delimiters=('=>',))
        p.read_dict({'s': {'safe=key': 'value'}})
        out = io.StringIO()
        p.write(out)
        self.assertIn('safe=key', out.getvalue())


if __name__ == '__main__':
    unittest.main()
"""

SERVICE = '''"""Export into a caller-owned stream; parser errors become a status."""
import configparser as cp

OK = True
INVALID = False


def export(parser, stream):
    try:
        parser.write(stream)
    except cp.ParsingError:
        return INVALID
    return OK
'''

POLICY = """# Downstream write-safety policy

This exercise adds a deliberately bounded validation policy, not a guarantee
that every conceivable INI state round-trips. Inspect main's approved fix and
adapt it to the required release(s). The upstream reference describes the base
API; this document and RELEASE.md specify our downstream changes.

Before the first call to the supplied stream's write method, inspect every
stored option key in DEFAULT and every explicit section (including an unnamed
section when enabled). A key is unsafe iff it contains CR or LF, contains any
of this parser instance's configured delimiters as a substring, or matches
this parser instance's SECTCRE using match at position zero. A key is already
normalized by optionxform when stored. Use these exact conditions; values,
section names, leading/trailing whitespace, empty names and full round-trip
validation are outside this change. Configured delimiters are nonempty strings.

If any key is unsafe, raise the release's specified error before writing even
one byte or calling any interpolation before_write hook. Include repr(key) in
the error message; if several keys are invalid, any one may be reported. Leave
parser state, stream position and contents unchanged. Support both RawConfigParser
and ConfigParser. Preflight validation must also work for write-only sinks
without seek/tell/getvalue. Do not close caller-owned streams. No atomicity is
required for later I/O/interpolation errors; preserve their normal propagation.

For safe keys, preserve each release's existing output ordering, delimiter
spacing default, allow_no_value behavior, multiline formatting, unnamed sections,
and interpolation behavior. Keep the existing public signatures. Existing calls
with explicit space_around_delimiters must still work.

service.export(parser, stream) must convert precisely this validation failure
into the release's INVALID status while preserving its existing ParsingError
handling. Other exceptions (including stream OSError) propagate. No stream close.
The release document specifies exception and status differences. Add focused
regression tests on each target branch. Evaluation checks behavior, compatibility,
Git ancestry and unchanged original files outside configparser.py, service.py,
and tests/. Extra test files under tests/ are welcome; supplied tests stay intact.
"""

BRIEF = """# Backport write-safety to {targets}

The repository is already initialized at /workspace/repo, checked out on
{initial}. Work there using ordinary Git through bash. The frozen local branches
and tags are available without network access. Inspect git log/show/diff and
read_file for targeted source navigation; use whichever tools help.

main contains one approved fix, tagged approved-write-safety. Backport its
behavior to {targets}. Each target must have at least one new commit descending
from its base tag. Preserve the main branch, all base tags and every original
commit. A cherry-pick is allowed; commit messages and exact patch shape are not
prescribed. No merge commits on target histories. Keep changes on the target
branches; the final checked-out target may be either target when there are two.

Start with docs/WRITE_POLICY.md and each target's RELEASE.md. They define the
bounded safety policy and compatibility differences. The 1,400-line parser and
long upstream reference are genuine CPython-derived material, not all required
reading. The fix is supplied to focus work on integration and verification.
{scope}

Run python -m unittest discover -s tests separately on each target after its
final changes. Add focused regression coverage under tests/ and commit it. The
existing supplied tests must remain byte-identical on each branch. Commit all
work; leave the repository clean, with no pending cherry-pick/merge/rebase. Do
not change files outside configparser.py, service.py and tests/ in the repository.
The task.md and repository.bundle outside repo are harness inputs, not deliverables.

Create /workspace/handoff.json (outside repo) with this structure, using full
40-character commit IDs and the branches actually submitted:
{{"branches": {{"{initial}": {{"commit": "FULL_COMMIT_ID",
 "verification_command": "python -m unittest discover -s tests"}}}}}}
Include an entry for every target. Run that command at that final revision before
recording it. In finish_attempt, identify both the handoff file and the observation
IDs for your branch-specific verification (command output should identify branch
and commit). These observations are historical evidence; the outer evaluator
independently checks each submitted revision. A missing or failed check must be
reported honestly rather than described as passing.
"""


def add_fix(text):
    text = text.replace("__all__ = (", '__all__ = ("InvalidWriteError", ', 1)
    marker = "# exception classes\n"
    # Error must already exist before the new subclass declaration.
    marker = "class NoSectionError(Error):"
    text = text.replace(
        marker,
        '''class InvalidWriteError(Error):
    """An option key cannot be safely emitted under the downstream policy."""


'''
        + marker,
        1,
    )
    marker = "        if space_around_delimiters:\n"
    addition = """        for section in (self._defaults, *self._sections.values()):
            for key in section:
                if ("\\r" in key or "\\n" in key
                        or any(d in key for d in self._delimiters)
                        or self.SECTCRE.match(key)):
                    raise InvalidWriteError(f"Unsafe option key: {key!r}")
"""
    assert text.count(marker) == 1
    return text.replace(marker, addition + marker, 1)


def main():
    BUILD.mkdir(parents=True, exist_ok=False)
    upstream = (UPSTREAM / "configparser.py").read_text()
    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in UPSTREAM.iterdir()
        if p.is_file()
    }
    for variant in ("smoke", "dual"):
        task = ROOT / "tasks" / ("git-config-backport-" + variant)
        public = task / "public"
        public.mkdir(parents=True, exist_ok=True)
        repo = BUILD / variant
        repo.mkdir()
        git(repo, "init", "-b", "main")
        (repo / "docs").mkdir()
        (repo / "tests").mkdir()
        (repo / "configparser.py").write_text(upstream)
        shutil.copyfile(
            UPSTREAM / "configparser.rst", repo / "docs/upstream-configparser.rst"
        )
        shutil.copyfile(UPSTREAM / "LICENSE", repo / "LICENSE")
        (repo / ".gitignore").write_text("__pycache__/\n*.py[cod]\n")
        (repo / "service.py").write_text(SERVICE)
        (repo / "tests/test_write.py").write_text(PUBLIC_TESTS)
        (repo / "docs/WRITE_POLICY.md").write_text(POLICY)
        (repo / "RELEASE.md").write_text(
            "# Main / stable compatibility\n\nValidation raises configparser.InvalidWriteError, a subclass of configparser.Error.\nservice statuses: OK is True, INVALID is False. Preserve insertion order and the\nwrite method default space_around_delimiters=True.\n"
        )
        (repo / "PROVENANCE.md").write_text(
            "CPython v3.13.0 source and documentation; PSF license in LICENSE.\nhttps://github.com/python/cpython/tree/v3.13.0\nAuthored downstream exercise: branch histories, write policy, service and tests.\nPinned input SHA256:\n"
            + json.dumps(hashes, indent=2)
            + "\n"
        )
        base = commit(
            repo, "Import pinned CPython parser and downstream export service"
        )
        refs = {}
        git(repo, "switch", "-c", "release/stable")
        if variant == "dual":
            text = upstream.replace(
                "        if space_around_delimiters:\n",
                "        # Stable exports deliberately sort option names within each section.\n        if space_around_delimiters:\n",
                1,
            )
            text = text.replace(
                "for key, value in section_items:",
                "for key, value in sorted(section_items):",
            )
            (repo / "configparser.py").write_text(text)
            (repo / "RELEASE.md").write_text(
                "# Stable compatibility\n\nValidation raises configparser.InvalidWriteError, a subclass of configparser.Error.\nservice statuses: OK is True, INVALID is False. Sort option names within each\nsection; retain section insertion order. Preserve the write method default\nspace_around_delimiters=True.\n"
            )
            commit(repo, "Stable: sort emitted option names for deterministic export")
        refs["release/stable"] = git(repo, "rev-parse", "HEAD")
        git(repo, "tag", "base-stable")
        if variant == "dual":
            git(repo, "switch", "-c", "release/legacy", base)
            text = upstream.replace(
                "def write(self, fp, space_around_delimiters=True):",
                "def write(self, fp, space_around_delimiters=False):",
            )
            text = text.replace(
                "        if space_around_delimiters:\n",
                "        # Legacy defaults to compact output; preserve this entry point.\n        if space_around_delimiters:\n",
                1,
            )
            text = text.replace("_write_section", "_emit_section")
            text = text.replace(
                "write(fp, space_around_delimiters=True)",
                "write(fp, space_around_delimiters=False)",
            )
            text = text.replace(
                "`space_around_delimiters` is True (the default), delimiters",
                "`space_around_delimiters` is True (legacy default: False), delimiters",
            )
            text = text.replace(
                "If `space_around_delimiters` is True (the default), delimiters",
                "If `space_around_delimiters` is True (legacy default: False), delimiters",
            )
            (repo / "configparser.py").write_text(text)
            (repo / "service.py").write_text(
                SERVICE.replace("OK = True\nINVALID = False", "OK = 0\nINVALID = 2")
            )
            (repo / "RELEASE.md").write_text(
                "# Legacy compatibility\n\nValidation raises exactly built-in ValueError (not a subclass). The parser still\nexposes its existing Error classes; keep the old API. service statuses: OK is\ninteger 0, INVALID is integer 2. Preserve insertion order and the write method\ndefault space_around_delimiters=False. Its internal section writer was renamed\n_emit_section in this release. Both explicit spacing choices still work.\n"
            )
            commit(
                repo, "Legacy: compact output and numeric service status compatibility"
            )
            refs["release/legacy"] = git(repo, "rev-parse", "HEAD")
            git(repo, "tag", "base-legacy")
        git(repo, "switch", "main")
        (repo / "configparser.py").write_text(add_fix(upstream))
        (repo / "service.py").write_text(
            SERVICE.replace(
                "except cp.ParsingError:",
                "except (cp.ParsingError, cp.InvalidWriteError):",
            )
        )
        approved = commit(
            repo, "Preflight all option keys before writing; report invalid exports"
        )
        git(repo, "tag", "approved-write-safety")
        git(
            repo,
            "bundle",
            "create",
            str(public / "repository.bundle"),
            "--branches",
            "--tags",
        )
        initial = "release/stable"
        targets = (
            "release/stable"
            if variant == "smoke"
            else "release/stable and release/legacy"
        )
        scope = (
            "This is the clean single-backport rung: no release-specific conflict is intended."
            if variant == "smoke"
            else "This is the adaptation rung: keep each release's ordering, spacing, error and\nstatus contract. Copying main wholesale would discard required release behavior."
        )
        (public / "task.md").write_text(
            BRIEF.format(initial=initial, targets=targets, scope=scope)
        )
        metadata = {
            "id": task.name,
            "version": 1,
            "kind": "git-backport",
            "split": "development",
            "maturity": "draft",
            "fixture_validation": "isolated-only",
            "entrypoint": "public/task.md",
            "git_repository": {
                "bundle": "repository.bundle",
                "directory": "repo",
                "initial_branch": initial,
                "branches": refs,
                "main": approved,
                "tags": {
                    "base-stable": refs[initial],
                    "approved-write-safety": approved,
                    **(
                        {"base-legacy": refs["release/legacy"]}
                        if variant == "dual"
                        else {}
                    ),
                },
            },
            "provenance": {
                "upstream_tag": "v3.13.0",
                "sha256": hashes,
                "url": "https://github.com/python/cpython/tree/v3.13.0",
                "scope": "Pinned parser/docs; authored downstream task, histories and policy.",
            },
            "human_duration": {"minutes": None, "status": "Uncalibrated"},
            "admission_status": "Draft; blind review and independent solution pending",
        }
        (task / "task.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(task.name, (public / "repository.bundle").stat().st_size, refs)


if __name__ == "__main__":
    main()
