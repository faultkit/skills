"""Unit tests for the runner's pure functions. Standard library only."""

import contextlib
import dataclasses
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "faultkit" / "scripts"))

import run_faultkit as rf  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "values"


class ProofTests(unittest.TestCase):
    def test_fired_count_counts_only_fired_events(self):
        report = {"events": [{"fired": True}, {"fired": False}, {"fired": True}]}
        self.assertEqual(rf.fired_count(report), 2)

    def test_fired_count_handles_missing_events(self):
        self.assertEqual(rf.fired_count({}), 0)

    def test_proof_states(self):
        self.assertEqual(rf.proof_state(3, 0), "invalid evidence: nothing was injected")
        self.assertEqual(rf.proof_state(1, 6), "silent failure confirmed")
        self.assertEqual(rf.proof_state(0, 1), "invariant proven under fault")
        self.assertEqual(rf.proof_state(2, 0), "error: faultkit exited 2")

    def test_passing_target_with_nothing_fired_is_invalid(self):
        self.assertEqual(rf.proof_state(0, 0), "invalid evidence: nothing was injected")


class ReportTests(unittest.TestCase):
    def write(self, text):
        path = Path(tempfile.mkdtemp()) / "r.json"
        path.write_text(text)
        return path

    def test_a_report_v1_file_counts_fired_events(self):
        path = self.write(json.dumps({"schema": rf.REPORT_SCHEMA, "events": [{"fired": True}, {"fired": False}, {"fired": 1}]}))
        self.assertEqual(rf.read_fired(path), 1)

    def test_missing_or_malformed_reports_read_as_none(self):
        cases = {
            "not json": "{",
            "not an object": "[]",
            "no schema": json.dumps({"events": [{"fired": True}]}),
            "another schema": json.dumps({"schema": "other", "events": []}),
            "events not a list": json.dumps({"schema": rf.REPORT_SCHEMA, "events": {"fired": True}}),
            "events is 0": json.dumps({"schema": rf.REPORT_SCHEMA, "events": 0}),
            "events is an empty string": json.dumps({"schema": rf.REPORT_SCHEMA, "events": ""}),
            "events is false": json.dumps({"schema": rf.REPORT_SCHEMA, "events": False}),
            "events is an empty object": json.dumps({"schema": rf.REPORT_SCHEMA, "events": {}}),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertIsNone(rf.read_fired(self.write(text)))
        self.assertIsNone(rf.read_fired(Path("/nonexistent/r.json")))

    def test_absent_or_null_events_count_as_zero_fired(self):
        self.assertEqual(rf.read_fired(self.write(json.dumps({"schema": rf.REPORT_SCHEMA}))), 0)
        self.assertEqual(rf.read_fired(self.write(json.dumps({"schema": rf.REPORT_SCHEMA, "events": None}))), 0)

    def test_evidence_state_keeps_crashes_and_missing_reports_apart(self):
        self.assertEqual(rf.evidence_state(2, None), "error: faultkit exited 2")
        self.assertEqual(rf.evidence_state(4, 3), "error: faultkit exited 4")
        self.assertEqual(rf.evidence_state(0, None), rf.REPORT_ERROR)
        self.assertEqual(rf.evidence_state(3, None), rf.REPORT_ERROR)
        self.assertEqual(rf.evidence_state(0, 1), "invariant proven under fault")
        self.assertEqual(rf.evidence_state(1, 0), "invalid evidence: nothing was injected")


class ResolveTests(unittest.TestCase):
    def _resolve(self, **overrides):
        kwargs = dict(explicit=None, env_bin=None, which=lambda _: None, source=None, cache_dir=Path("/c"), system="linux")
        kwargs.update(overrides)
        return rf.resolve_binary(**kwargs)

    def test_explicit_wins(self):
        self.assertEqual(self._resolve(explicit="/x/faultkit", env_bin="/y", which=lambda _: "/z"), Path("/x/faultkit"))

    def test_env_beats_path(self):
        self.assertEqual(self._resolve(env_bin="/y", which=lambda _: "/z"), Path("/y"))

    def test_path_beats_source(self):
        self.assertEqual(self._resolve(which=lambda _: "/z", source="/src"), Path("/z"))

    def test_source_builds_when_nothing_is_installed(self):
        with mock.patch.object(rf, "build_from_source", return_value=Path("/built")) as build:
            self.assertEqual(self._resolve(source="/src"), Path("/built"))
        build.assert_called_once_with(Path("/src"), Path("/c"))

    def test_nothing_installed_raises_with_install_commands(self):
        with self.assertRaises(rf.FaultkitNotFound) as ctx:
            self._resolve()
        self.assertIn("brew install faultkit/tap/faultkit", str(ctx.exception))
        self.assertIn("yay -S faultkit-bin", str(ctx.exception))


class InstallHintTests(unittest.TestCase):
    def test_macos_gets_homebrew_and_no_aur(self):
        hint = rf.install_hint("darwin")
        self.assertIn("brew install faultkit/tap/faultkit", hint)
        self.assertNotIn("yay", hint)

    def test_every_platform_gets_the_pinned_go_install_and_the_install_page(self):
        for system in ("darwin", "linux", "windows"):
            hint = rf.install_hint(system)
            self.assertIn(f"go install github.com/faultkit/faultkit/cmd/faultkit@v{rf.FAULTKIT_VERSION}", hint)
            self.assertIn(rf.INSTALL_PAGE, hint)

    def test_no_hint_pipes_a_download_into_a_shell(self):
        for system in ("darwin", "linux", "windows"):
            hint = rf.install_hint(system)
            self.assertNotIn("curl", hint)
            self.assertNotIn("| sh", hint)


class VersionTests(unittest.TestCase):
    def test_parses_the_first_line_of_faultkit_version(self):
        self.assertEqual(rf.parse_version("faultkit 0.1.3\ncommit: f7874e6\n"), "0.1.3")
        self.assertEqual(rf.parse_version("faultkit v0.2.0-rc.1\n"), "0.2.0")

    def test_unparseable_output_is_unknown(self):
        self.assertIsNone(rf.parse_version("Error: unknown command\n"))
        self.assertIsNone(rf.parse_version("faultkit dev\n"))

    def test_older_than_compares_numerically(self):
        self.assertTrue(rf.older_than("0.1.2", "0.1.3"))
        self.assertFalse(rf.older_than("0.1.3", "0.1.3"))
        self.assertFalse(rf.older_than("0.1.10", "0.1.3"))


class ColorTests(unittest.TestCase):
    def test_auto_follows_tty(self):
        self.assertTrue(rf.use_color("auto", isatty=True, env={}))
        self.assertFalse(rf.use_color("auto", isatty=False, env={}))

    def test_no_color_wins_over_tty(self):
        self.assertFalse(rf.use_color("auto", isatty=True, env={"NO_COLOR": "1"}))

    def test_force_color_wins_over_pipe(self):
        self.assertTrue(rf.use_color("auto", isatty=False, env={"FORCE_COLOR": "1"}))

    def test_always_and_never(self):
        self.assertTrue(rf.use_color("always", isatty=False, env={"NO_COLOR": "1"}))
        self.assertFalse(rf.use_color("never", isatty=True, env={"FORCE_COLOR": "1"}))

    def test_proof_block_keeps_state_strings_with_and_without_color(self):
        plain = rf.render_proof("s.yaml", "proxy", 1, 1, "silent failure confirmed", "r.json", color=False)
        self.assertIn("proof state:   silent failure confirmed", plain)
        self.assertNotIn("\033[", plain)
        painted = rf.render_proof("s.yaml", "proxy", 1, 0, "invariant proven under fault", "r.json", color=True)
        self.assertIn("invariant proven under fault", painted)
        self.assertIn("\033[32m", painted)  # green for proven
        invalid = rf.render_proof("s.yaml", "proxy", 0, 3, "invalid evidence: nothing was injected", "r.json", color=True)
        self.assertIn("\033[33m", invalid)  # yellow for invalid

    def test_not_generated_has_its_own_colour(self):
        self.assertEqual(rf.state_color(rf.NOT_GENERATED), "dim")


class ArgTests(unittest.TestCase):
    def test_split_target_after_double_dash(self):
        ns, target = rf.parse_args(["--config", "s.yaml", "--report", "r.json", "--base-url", "--", "node", "--test", "t.mjs"])
        self.assertEqual(target, ["node", "--test", "t.mjs"])
        self.assertTrue(ns.base_url)

    def test_color_flag_parses(self):
        ns, _ = rf.parse_args(["--config", "s.yaml", "--report", "r.json", "--color", "always", "--", "true"])
        self.assertEqual(ns.color, "always")

    def test_missing_target_is_usage_error(self):
        with self.assertRaises(SystemExit):
            rf.parse_args(["--config", "s.yaml", "--report", "r.json"])

    def test_builtin_scenario_replaces_config(self):
        ns, _ = rf.parse_args(["--scenario", "llm-api-degraded", "--report", "r.json", "--", "true"])
        self.assertEqual(ns.scenario, "llm-api-degraded")

    def test_config_and_scenario_are_exclusive(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            rf.parse_args(["--config", "s.yaml", "--scenario", "x", "--report", "r.json", "--", "true"])

    def test_manifest_needs_no_target(self):
        ns, target = rf.parse_args(["--manifest", "m.json"])
        self.assertEqual((ns.manifest, target), ("m.json", []))

    def test_manifest_rejects_per_run_flags(self):
        for extra in (["--config", "s.yaml"], ["--base-url"], ["--", "true"]):
            with self.subTest(extra=extra), self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                rf.parse_args(["--manifest", "m.json", *extra])

    def test_values_needs_manifest(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            rf.parse_args(["--values", "v.md", "--config", "s.yaml", "--report", "r.json", "--", "true"])
        ns, _ = rf.parse_args(["--manifest", "m.json", "--values", "v.md"])
        self.assertEqual(ns.values, "v.md")


def sha256_of(text):
    return hashlib.sha256(text.encode()).hexdigest()


def entry(**overrides):
    base = {"id": "no-auto-route", "invariant": "never auto-route a guess", "config": "no-auto-route.yaml", "gate": ["node", "--test"]}
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def gap(**overrides):
    base = {
        "id": "human-approval",
        "invariant": "every refund over the limit has a recorded approval",
        "fault_status": "not_generated",
        "fault_reason": "no injectable boundary",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def write_scenario(directory):
    """The scenario file entry()'s default "config" points at, so existence checks pass."""
    (directory / "no-auto-route.yaml").write_text("experiments: []\n")


class ManifestTests(unittest.TestCase):
    def load(self, data, links=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps(data))
            write_scenario(Path(tmp))
            for name, target in (links or {}).items():
                (Path(tmp) / name).symlink_to(target)
            return rf.load_manifest(path)

    def test_v1_entries_load_as_generated(self):
        manifest = self.load({"version": 1, "invariants": [entry(), entry(id="second", config=None, scenario="llm-api-degraded")]})
        self.assertEqual(manifest.version, 1)
        self.assertEqual([e["id"] for e in manifest.entries], ["no-auto-route", "second"])
        self.assertEqual([e["fault_status"] for e in manifest.entries], ["generated", "generated"])

    def test_v2_manifest_loads_both_statuses(self):
        manifest = self.load({"version": 2, "invariants": [entry(fault_status="generated"), gap()]})
        self.assertEqual(manifest.version, 2)
        self.assertEqual([e["fault_status"] for e in manifest.entries], ["generated", "not_generated"])

    def test_not_generated_may_keep_a_gate(self):
        manifest = self.load({"version": 2, "invariants": [gap(gate=["pytest", "-q"])]})
        self.assertEqual(manifest.entries[0]["gate"], ["pytest", "-q"])

    def test_invalid_manifests_are_rejected(self):
        cases = {
            "unknown version": {"version": 7, "invariants": [entry()]},
            "version as a boolean": {"version": True, "invariants": [entry()]},
            "no invariants": {"version": 1, "invariants": []},
            "bad id": {"version": 1, "invariants": [entry(id="Not A Slug")]},
            "id with a trailing newline": {"version": 1, "invariants": [entry(id="no-auto-route\n")]},
            "duplicate id": {"version": 1, "invariants": [entry(), entry()]},
            "no invariant text": {"version": 1, "invariants": [entry(invariant="")]},
            "config and scenario": {"version": 1, "invariants": [entry(scenario="llm-api-degraded")]},
            "neither config nor scenario": {"version": 1, "invariants": [entry(config=None)]},
            "empty scenario": {"version": 1, "invariants": [entry(config=None, scenario="")]},
            "whitespace-only scenario": {"version": 1, "invariants": [entry(config=None, scenario="   ")]},
            "gate as a string": {"version": 1, "invariants": [entry(gate="node --test")]},
            "empty gate": {"version": 1, "invariants": [entry(gate=[])]},
            "unknown mode": {"version": 1, "invariants": [entry(mode="docker")]},
            "base_url as a string": {"version": 1, "invariants": [entry(base_url="yes")]},
            "shape as a number": {"version": 1, "invariants": [entry(shape=5)]},
            "absolute config": {"version": 1, "invariants": [entry(config="/etc/hosts")]},
            "whitespace-only config": {"version": 1, "invariants": [entry(config="   ")]},
            "config escaping the directory": {"version": 1, "invariants": [entry(config="../outside.yaml")]},
            "fault_status in v1": {"version": 1, "invariants": [entry(fault_status="generated")]},
            "v2 without fault_status": {"version": 2, "invariants": [entry()]},
            "v2 unknown fault_status": {"version": 2, "invariants": [entry(fault_status="skipped")]},
            "not_generated with config": {"version": 2, "invariants": [gap(config="x.yaml")]},
            "not_generated with scenario": {"version": 2, "invariants": [gap(scenario="llm-api-degraded")]},
            "not_generated without reason": {"version": 2, "invariants": [gap(fault_reason=None)]},
            "not_generated with a blank reason": {"version": 2, "invariants": [gap(fault_reason="  ")]},
            "not_generated with a bad gate": {"version": 2, "invariants": [gap(gate="pytest")]},
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(rf.ManifestError):
                self.load(data)

    def test_config_symlink_out_of_the_directory_is_rejected(self):
        with self.assertRaises(rf.ManifestError):
            self.load({"version": 1, "invariants": [entry(config="link.yaml")]}, links={"link.yaml": "/etc/hosts"})

    def test_config_resolving_to_the_manifest_directory_itself_is_rejected(self):
        for config in (".", "./", "a/.."):
            with self.subTest(config=config), self.assertRaises(rf.ManifestError) as ctx:
                self.load({"version": 1, "invariants": [entry(config=config)]})
            self.assertIn("must stay inside", str(ctx.exception))

    def test_a_nonexistent_config_file_is_rejected(self):
        with self.assertRaises(rf.ManifestError) as ctx:
            self.load({"version": 1, "invariants": [entry(config="missing.yaml")]})
        self.assertIn("scenario file missing.yaml does not exist", str(ctx.exception))

    def test_unreadable_manifest_is_a_manifest_error(self):
        with self.assertRaises(rf.ManifestError):
            rf.load_manifest(Path("/nonexistent/manifest.json"))


class ManifestV3Tests(unittest.TestCase):
    SCENARIO = "experiments: []\n"

    def load(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            (Path(tmp) / "registry").mkdir()
            (Path(tmp) / "registry" / "openai-503@1.0.0.yaml").write_text(self.SCENARIO)
            write_scenario(Path(tmp))
            path.write_text(json.dumps(data))
            return rf.load_manifest(path)

    def source(self, **overrides):
        base = {"registry": "faultkit", "id": "openai-503", "version": "1.0.0", "sha256": sha256_of(self.SCENARIO)}
        base.update(overrides)
        return base

    def test_v3_fields_load(self):
        manifest = self.load({
            "version": 3,
            "values": ".faultkit/values.md",
            "registry": {"url": "https://github.com/faultkit/registry", "ref": "a" * 40},
            "invariants": [
                entry(fault_status="generated", outcome="UO-1"),
                entry(id="vendored", fault_status="generated", config="registry/openai-503@1.0.0.yaml", source=self.source()),
                gap(outcome="UO-2"),
            ],
        })
        self.assertEqual((manifest.version, manifest.values), (3, ".faultkit/values.md"))
        self.assertEqual(manifest.registry["ref"], "a" * 40)
        self.assertEqual([e.get("outcome") for e in manifest.entries], ["UO-1", None, "UO-2"])

    def test_invalid_v3_manifests_are_rejected(self):
        cases = {
            "outcome in v2": {"version": 2, "invariants": [entry(fault_status="generated", outcome="UO-1")]},
            "values in v2": {"version": 2, "values": "v.md", "invariants": [entry(fault_status="generated")]},
            "source in v1": {"version": 1, "invariants": [entry(source={})]},
            "registry in v1": {"version": 1, "registry": {}, "invariants": [entry()]},
            "v3 without fault_status": {"version": 3, "invariants": [entry()]},
            "outcome without a dash": {"version": 3, "invariants": [entry(fault_status="generated", outcome="UO1")]},
            "outcome with a trailing newline": {"version": 3, "invariants": [entry(fault_status="generated", outcome="UO-1\n")]},
            "absolute values path": {"version": 3, "values": "/etc/values.md", "invariants": [entry(fault_status="generated")]},
            "registry over http": {"version": 3, "registry": {"url": "http://example.com", "ref": "a" * 40}, "invariants": [entry(fault_status="generated")]},
            "registry on a branch": {"version": 3, "registry": {"url": "https://github.com/faultkit/registry", "ref": "main"}, "invariants": [entry(fault_status="generated")]},
            "registry ref with a trailing newline": {"version": 3, "registry": {"url": "https://github.com/faultkit/registry", "ref": "a" * 40 + "\n"}, "invariants": [entry(fault_status="generated")]},
            "source on not_generated": {"version": 3, "invariants": [gap(source=self.source())]},
            "source on a builtin": {"version": 3, "invariants": [entry(fault_status="generated", config=None, scenario="llm-api-degraded", source=self.source())]},
            "source without semver": {"version": 3, "invariants": [entry(fault_status="generated", config="registry/openai-503@1.0.0.yaml", source=self.source(version="1.0"))]},
            "source version with a trailing newline": {"version": 3, "invariants": [entry(fault_status="generated", config="registry/openai-503@1.0.0.yaml", source=self.source(version="1.0.0\n"))]},
            "source sha256 mismatch": {"version": 3, "invariants": [entry(fault_status="generated", config="registry/openai-503@1.0.0.yaml", source=self.source(sha256="0" * 64))]},
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(rf.ManifestError):
                self.load(data)


class OutcomeCheckTests(unittest.TestCase):
    VALUES = "## Business value\nv\n\n## Unacceptable outcomes\n- UO-1: a\n- UO-2: b\n"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def manifest(self, *entries, values=None):
        return rf.Manifest(version=3, entries=list(entries), values=values)

    def test_resolution_order(self):
        (self.tmp / ".faultkit").mkdir()
        (self.tmp / ".faultkit" / "values.md").write_text(self.VALUES)
        m = self.manifest(values="docs/values.md")
        self.assertEqual(rf.resolve_values("x.md", m, self.tmp), Path("x.md"))
        self.assertEqual(rf.resolve_values(None, m, self.tmp), self.tmp / "docs" / "values.md")
        self.assertEqual(rf.resolve_values(None, self.manifest(), self.tmp), self.tmp / ".faultkit" / "values.md")
        self.assertIsNone(rf.resolve_values(None, self.manifest(), self.tmp / "elsewhere"))

    def test_manifest_values_path_must_stay_inside_the_repository(self):
        outside = self.manifest(values="../outside.md")
        with self.assertRaises(rf.ManifestError) as ctx:
            rf.resolve_values(None, outside, self.tmp)
        self.assertIn("must stay inside", str(ctx.exception))
        inside = self.manifest(values="docs/values.md")
        self.assertEqual(rf.resolve_values(None, inside, self.tmp), self.tmp / "docs" / "values.md")

    def test_declared_outcomes_pass(self):
        path = self.tmp / "values.md"
        path.write_text(self.VALUES)
        values = rf.check_outcomes(self.manifest({"id": "a", "outcome": "UO-2"}, {"id": "b"}), path)
        self.assertEqual([o.id for o in values.outcomes], ["UO-1", "UO-2"])

    def test_an_undeclared_outcome_is_an_error(self):
        path = self.tmp / "values.md"
        path.write_text(self.VALUES)
        with self.assertRaises(rf.ManifestError):
            rf.check_outcomes(self.manifest({"id": "a", "outcome": "UO-3"}), path)

    def test_a_dangling_outcome_is_an_error(self):
        with self.assertRaises(rf.ManifestError) as ctx:
            rf.check_outcomes(self.manifest({"id": "a", "outcome": "UO-1"}), self.tmp / "missing.md")
        self.assertIn("dangling outcome reference", str(ctx.exception))
        with self.assertRaises(rf.ManifestError):
            rf.check_outcomes(self.manifest({"id": "a", "outcome": "UO-1"}), None)

    def test_no_outcomes_and_no_file_means_no_values(self):
        self.assertIsNone(rf.check_outcomes(self.manifest({"id": "a"}), self.tmp / "missing.md"))
        self.assertIsNone(rf.check_outcomes(self.manifest({"id": "a"}), None))


class CommandTests(unittest.TestCase):
    def test_config_entry(self):
        cmd = rf.build_command(Path("/fk"), config="c.yaml", report="r.json", base_url=True, provider="openai", verbose=True, target=["node", "--test"])
        self.assertEqual(cmd, ["/fk", "run", "--config", "c.yaml", "--report", "r.json", "--mode", "auto", "--base-url", "--provider", "openai", "--verbose", "--", "node", "--test"])

    def test_builtin_entry(self):
        cmd = rf.build_command(Path("/fk"), scenario="llm-api-degraded", report="r.json", target=["pytest"])
        self.assertEqual(cmd[:4], ["/fk", "run", "--scenario", "llm-api-degraded"])


class AggregateTests(unittest.TestCase):
    PROVEN, SILENT = "invariant proven under fault", "silent failure confirmed"
    INVALID, ERROR = "invalid evidence: nothing was injected", "error: faultkit exited 2"

    def test_all_proven_is_ok(self):
        self.assertEqual(rf.aggregate_exit([self.PROVEN, self.PROVEN]), rf.EXIT_OK)

    def test_one_silent_failure_fails_the_run(self):
        self.assertEqual(rf.aggregate_exit([self.PROVEN, self.SILENT]), rf.EXIT_TARGET_FAILED)

    def test_invalid_evidence_outranks_a_silent_failure(self):
        self.assertEqual(rf.aggregate_exit([self.SILENT, self.INVALID]), rf.EXIT_FAULT_NOT_FIRED)

    def test_error_outranks_everything(self):
        self.assertEqual(rf.aggregate_exit([self.INVALID, self.ERROR, self.SILENT]), rf.EXIT_INTERNAL)

    def test_summary_lists_every_invariant(self):
        text = rf.render_summary([("a", 6, 1, self.SILENT), ("bb", 2, 0, self.PROVEN)], color=False)
        self.assertIn("a              6     1  silent failure confirmed", text)
        self.assertIn("bb             2     0  invariant proven under fault", text)

    def test_not_generated_never_changes_the_exit(self):
        self.assertEqual(rf.aggregate_exit([self.PROVEN, rf.NOT_GENERATED]), rf.EXIT_OK)
        self.assertEqual(rf.aggregate_exit([rf.NOT_GENERATED]), rf.EXIT_OK)

    def test_summary_prints_dashes_when_nothing_ran(self):
        text = rf.render_summary([("a", 6, 1, self.SILENT), ("gap", None, None, rf.NOT_GENERATED)], color=False)
        self.assertIn("gap" + " " * 12 + "-" + " " * 5 + "-  fault not generated", text)


# A stand-in faultkit: writes a report/v1 file with one fired event unless
# $FAKE_NO_REPORT is set, and exits with $FAKE_EXIT.
FAKE_FAULTKIT = """#!/bin/sh
[ "$1" = version ] && { echo "faultkit ${FAKE_VERSION:-0.1.3}"; exit 0; }
while [ $# -gt 0 ]; do
  case $1 in --report) shift; [ -n "$FAKE_NO_REPORT" ] || printf '{"schema":"faultkit.dev/report/v1","events":[{"fired":true}]}' > "$1";; --) break;; esac
  shift
done
exit "${FAKE_EXIT:-1}"
"""


@unittest.skipIf(os.name != "posix", "fake faultkit is a shell script")
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fake = self.tmp / "faultkit"
        self.fake.write_text(FAKE_FAULTKIT)
        self.fake.chmod(0o755)

    def main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = rf.main(["--faultkit-bin", str(self.fake), "--color", "never", *argv])
        return code, out.getvalue()

    def test_single_run_creates_the_report_directory(self):
        report = self.tmp / "missing" / "dir" / "r.json"
        code, out = self.main(["--config", "s.yaml", "--report", str(report), "--", "true"])
        self.assertEqual(code, 1)
        self.assertTrue(report.exists())
        self.assertIn("faults fired:  1", out)
        self.assertIn("silent failure confirmed", out)

    def test_manifest_runs_every_invariant(self):
        manifest = self.tmp / ".faultkit" / "invariants" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        write_scenario(manifest.parent)
        manifest.write_text(json.dumps({"version": 1, "invariants": [entry(), entry(id="second")]}))
        reports = self.tmp / "reports"
        code, out = self.main(["--manifest", str(manifest), "--reports-dir", str(reports)])
        self.assertEqual(code, rf.EXIT_TARGET_FAILED)
        self.assertEqual(sorted(p.name for p in reports.iterdir()), ["no-auto-route.report.json", "second.report.json"])
        self.assertIn(str(manifest.parent / "no-auto-route.yaml"), out)
        self.assertIn("=== prove-all ===", out)

    def test_bad_manifest_is_a_usage_error(self):
        manifest = self.tmp / "manifest.json"
        manifest.write_text("{}")
        code, _ = self.main(["--manifest", str(manifest)])
        self.assertEqual(code, rf.EXIT_USAGE)

    def test_v2_manifest_never_runs_not_generated_entries(self):
        manifest = self.tmp / ".faultkit" / "invariants" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        write_scenario(manifest.parent)
        manifest.write_text(json.dumps({"version": 2, "invariants": [entry(fault_status="generated"), gap()]}))
        reports = self.tmp / "reports"
        code, out = self.main(["--manifest", str(manifest), "--reports-dir", str(reports)])
        self.assertEqual(code, rf.EXIT_TARGET_FAILED)
        self.assertEqual([p.name for p in reports.iterdir()], ["no-auto-route.report.json"])
        self.assertIn("fault not generated: no injectable boundary", out)
        self.assertIn("fault not generated", out.split("=== prove-all ===")[1])

    def test_a_stale_report_never_stands_in_for_a_missing_one(self):
        report = self.tmp / "r.json"
        report.write_text(json.dumps({"schema": rf.REPORT_SCHEMA, "events": [{"fired": True}]}))
        with mock.patch.dict(os.environ, {"FAKE_NO_REPORT": "1", "FAKE_EXIT": "0"}):
            code, out = self.main(["--config", "s.yaml", "--report", str(report), "--", "true"])
        self.assertEqual(code, rf.EXIT_INTERNAL)
        self.assertFalse(report.exists())
        self.assertIn("faults fired:  -", out)
        self.assertIn(rf.REPORT_ERROR, out)

    def test_a_manifest_run_without_a_report_is_an_error(self):
        manifest = self.tmp / ".faultkit" / "invariants" / "manifest.json"
        manifest.parent.mkdir(parents=True)
        write_scenario(manifest.parent)
        manifest.write_text(json.dumps({"version": 1, "invariants": [entry()]}))
        with mock.patch.dict(os.environ, {"FAKE_NO_REPORT": "1", "FAKE_EXIT": "0"}):
            code, out = self.main(["--manifest", str(manifest), "--reports-dir", str(self.tmp / "reports")])
        self.assertEqual(code, rf.EXIT_INTERNAL)
        self.assertIn(rf.REPORT_ERROR, out.split("=== prove-all ===")[1])

    def test_a_dangling_outcome_is_a_usage_error(self):
        manifest = self.tmp / "manifest.json"
        write_scenario(self.tmp)
        manifest.write_text(json.dumps({"version": 3, "invariants": [entry(fault_status="generated", outcome="UO-1")]}))
        code, _ = self.main(["--manifest", str(manifest), "--values", str(self.tmp / "missing.md")])
        self.assertEqual(code, rf.EXIT_USAGE)

    def test_a_bad_values_file_is_a_usage_error(self):
        manifest = self.tmp / "manifest.json"
        write_scenario(self.tmp)
        manifest.write_text(json.dumps({"version": 3, "invariants": [entry(fault_status="generated", outcome="UO-1")]}))
        values = self.tmp / "values.md"
        values.write_text("## Business value\nv\n")
        code, _ = self.main(["--manifest", str(manifest), "--values", str(values)])
        self.assertEqual(code, rf.EXIT_USAGE)

    def test_the_outcomes_table_follows_prove_all(self):
        manifest = self.tmp / "manifest.json"
        write_scenario(self.tmp)
        manifest.write_text(json.dumps({"version": 3, "invariants": [entry(fault_status="generated", outcome="UO-1"), gap()]}))
        values = self.tmp / "values.md"
        values.write_text("## Business value\nv\n\n## Unacceptable outcomes\n- UO-1: a\n- UO-2: b\n")
        code, out = self.main(["--manifest", str(manifest), "--values", str(values), "--reports-dir", str(self.tmp / "reports")])
        self.assertEqual(code, rf.EXIT_TARGET_FAILED)
        after = out.split("=== prove-all ===")[1]
        self.assertIn("=== outcomes ===", after)
        self.assertIn("declared 2, covered 1, uncovered 1, unlinked invariants 1", after)

    def test_no_values_file_means_no_outcomes_table(self):
        manifest = self.tmp / "manifest.json"
        write_scenario(self.tmp)
        manifest.write_text(json.dumps({"version": 1, "invariants": [entry()]}))
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            _, out = self.main(["--manifest", str(manifest), "--reports-dir", str(self.tmp / "reports")])
        finally:
            os.chdir(cwd)
        self.assertNotIn("=== outcomes ===", out)

    def test_a_missing_values_file_is_a_usage_error_with_no_linked_outcome(self):
        manifest = self.tmp / "manifest.json"
        write_scenario(self.tmp)
        manifest.write_text(json.dumps({"version": 1, "invariants": [entry()]}))
        code, _ = self.main(["--manifest", str(manifest), "--values", str(self.tmp / "missing.md")])
        self.assertEqual(code, rf.EXIT_USAGE)

    def test_a_source_sha256_mismatch_never_invokes_faultkit(self):
        (self.tmp / "registry").mkdir()
        (self.tmp / "registry" / "openai-503@1.0.0.yaml").write_text("experiments: []\n")
        manifest = self.tmp / "manifest.json"
        manifest.write_text(json.dumps({
            "version": 3,
            "invariants": [entry(
                fault_status="generated", config="registry/openai-503@1.0.0.yaml",
                source={"registry": "faultkit", "id": "openai-503", "version": "1.0.0", "sha256": "0" * 64},
            )],
        }))
        reports = self.tmp / "reports"
        code, _ = self.main(["--manifest", str(manifest), "--reports-dir", str(reports)])
        self.assertEqual(code, rf.EXIT_USAGE)
        self.assertFalse(reports.exists())

    def test_v1_manifest_with_an_implicit_values_file_shows_every_outcome_uncovered(self):
        manifest = self.tmp / "manifest.json"
        write_scenario(self.tmp)
        manifest.write_text(json.dumps({"version": 1, "invariants": [entry(), entry(id="second")]}))
        (self.tmp / ".faultkit").mkdir()
        (self.tmp / ".faultkit" / "values.md").write_text(
            "## Business value\nv\n\n## Unacceptable outcomes\n- UO-1: a\n- UO-2: b\n"
        )
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            _, out = self.main(["--manifest", str(manifest), "--reports-dir", str(self.tmp / "reports")])
        finally:
            os.chdir(cwd)
        after = out.split("=== prove-all ===")[1]
        self.assertIn("=== outcomes ===", after)
        self.assertEqual(after.count(rf.NO_INVARIANT), 2)
        self.assertIn("declared 2, covered 0, uncovered 2, unlinked invariants 2", after)

    def test_missing_faultkit_exits_2_and_prints_install_commands(self):
        err = io.StringIO()
        with mock.patch.object(rf.shutil, "which", return_value=None), mock.patch.dict(os.environ) as env, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            env.pop("FAULTKIT", None)
            code = rf.main(["--color", "never", "--config", "s.yaml", "--report", str(self.tmp / "r.json"), "--", "true"])
        self.assertEqual(code, rf.EXIT_INTERNAL)
        self.assertIn("faultkit is not installed", err.getvalue())
        self.assertIn("brew install faultkit/tap/faultkit", err.getvalue())

    def test_a_faultkit_older_than_the_minimum_stops_before_running(self):
        report = self.tmp / "r.json"
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"FAKE_VERSION": "0.1.2"}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = rf.main(["--faultkit-bin", str(self.fake), "--color", "never", "--config", "s.yaml", "--report", str(report), "--", "true"])
        self.assertEqual(code, rf.EXIT_INTERNAL)
        self.assertFalse(report.exists())
        self.assertIn("is older than 0.1.3", err.getvalue())
        self.assertIn(str(self.fake), err.getvalue())

    def test_a_faultkit_bin_that_cannot_run_exits_2(self):
        report = self.tmp / "r.json"
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = rf.main(["--faultkit-bin", str(self.tmp / "nope"), "--color", "never", "--config", "s.yaml", "--report", str(report), "--", "true"])
        self.assertEqual(code, rf.EXIT_INTERNAL)
        self.assertIn("cannot run faultkit at", err.getvalue())
        self.assertFalse(report.exists())

    def test_a_faultkit_that_prints_dev_skips_the_version_check(self):
        with mock.patch.dict(os.environ, {"FAKE_VERSION": "dev"}):
            code, out = self.main(["--config", "s.yaml", "--report", str(self.tmp / "r.json"), "--", "true"])
        self.assertEqual(code, rf.EXIT_TARGET_FAILED)
        self.assertIn("silent failure confirmed", out)


class OutcomeTableTests(unittest.TestCase):
    PROVEN, SILENT = "invariant proven under fault", "silent failure confirmed"
    INVALID, ERROR = "invalid evidence: nothing was injected", "error: faultkit exited 2"

    def values(self, *ids):
        return rf.Values(business_value="v", outcomes=[rf.Outcome(i, f"text of {i}") for i in ids])

    def test_worst_state_follows_the_severity_order(self):
        self.assertEqual(rf.worst_state([self.PROVEN, self.SILENT]), self.SILENT)
        self.assertEqual(rf.worst_state([self.SILENT, self.INVALID]), self.SILENT)
        self.assertEqual(rf.worst_state([self.PROVEN, rf.NOT_GENERATED]), rf.NOT_GENERATED)
        self.assertEqual(rf.worst_state([self.INVALID, rf.NOT_GENERATED]), self.INVALID)
        self.assertEqual(rf.worst_state([self.PROVEN, self.ERROR, self.SILENT]), self.ERROR)

    def test_the_table_covers_every_declared_outcome(self):
        entries = [{"id": "paid", "outcome": "UO-1"}, {"id": "route", "outcome": "UO-2"}, {"id": "charge", "outcome": "UO-2"}, {"id": "loose"}]
        states = {"paid": self.PROVEN, "route": self.PROVEN, "charge": self.SILENT, "loose": self.PROVEN}
        lines = rf.render_outcomes(self.values("UO-1", "UO-2", "UO-3"), entries, states, color=False).splitlines()
        width = len(self.PROVEN)
        self.assertEqual(lines, [
            "=== outcomes ===",
            "outcome  " + "worst state".ljust(width) + "  invariants",
            "UO-1     " + self.PROVEN.ljust(width) + "  paid",
            "UO-2     " + self.SILENT.ljust(width) + "  route",
            " " * 9 + " " * width + "  charge",
            "UO-3     " + "no invariant yet".ljust(width) + "  -",
            "declared 3, covered 2, uncovered 1, unlinked invariants 1",
        ])

    def test_outcomes_are_listed_in_id_order(self):
        text = rf.render_outcomes(self.values("UO-12", "UO-2"), [], {}, color=False)
        self.assertLess(text.index("UO-2 "), text.index("UO-12"))

    def test_an_outcome_covered_only_by_a_not_generated_entry_is_covered(self):
        lines = rf.render_outcomes(self.values("UO-1"), [{"id": "gap", "outcome": "UO-1"}], {"gap": rf.NOT_GENERATED}, color=False).splitlines()
        self.assertTrue(lines[2].startswith("UO-1     " + rf.NOT_GENERATED))
        self.assertEqual(lines[-1], "declared 1, covered 1, uncovered 0, unlinked invariants 0")

    def test_inferred_values_get_a_different_header(self):
        values = rf.Values(business_value="v", outcomes=[rf.Outcome("UO-1", "t")], inferred=True)
        lines = rf.render_outcomes(values, [], {}, color=False).splitlines()
        self.assertEqual(lines[0], "=== outcomes (inferred) ===")


class ValuesTests(unittest.TestCase):
    def test_valid_fixtures_parse_to_their_json(self):
        for md in sorted((FIXTURES / "valid").glob("*.md")):
            with self.subTest(md.name):
                values = rf.parse_values(md.read_text(encoding="utf-8"), "values.md")
                expected = json.loads(md.with_suffix(".json").read_text(encoding="utf-8"))
                self.assertEqual(dataclasses.asdict(values), expected)

    def test_invalid_fixtures_name_the_line(self):
        for md in sorted((FIXTURES / "invalid").glob("*.md")):
            with self.subTest(md.name):
                with self.assertRaises(rf.ValuesError) as ctx:
                    rf.parse_values(md.read_text(encoding="utf-8"), "values.md")
                self.assertEqual(str(ctx.exception), md.with_suffix(".error").read_text(encoding="utf-8").strip())

    def test_fixture_sets_are_complete(self):
        self.assertEqual(len(list((FIXTURES / "valid").glob("*.md"))), 7)
        self.assertEqual(len(list((FIXTURES / "invalid").glob("*.md"))), 13)

    def test_crlf_reads_like_lf(self):
        text = (FIXTURES / "valid" / "full.md").read_text(encoding="utf-8")
        self.assertEqual(rf.parse_values(text.replace("\n", "\r\n")), rf.parse_values(text))

    def test_a_blank_outcome_text_is_not_an_outcome(self):
        with self.assertRaises(rf.ValuesError):
            rf.parse_values("## Business value\nv\n## Unacceptable outcomes\n- UO-1:  \n")

    def test_load_values_names_the_file(self):
        path = Path(tempfile.mkdtemp()) / "values.md"
        path.write_text("## Business value\n\n## Unacceptable outcomes\n- UO-1: x\n", encoding="utf-8")
        with self.assertRaises(rf.ValuesError) as ctx:
            rf.load_values(path)
        self.assertTrue(str(ctx.exception).startswith(f"{path}:1: "))

    def test_unreadable_values_file_is_a_values_error(self):
        with self.assertRaises(rf.ValuesError):
            rf.load_values(Path("/nonexistent/values.md"))


if __name__ == "__main__":
    unittest.main()
