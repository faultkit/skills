"""Unit tests for the runner's pure functions. Standard library only."""

import contextlib
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


class PlatformTests(unittest.TestCase):
    def test_linux_x86_64_maps_to_amd64(self):
        self.assertEqual(rf.platform_key("Linux", "x86_64"), ("linux", "amd64"))

    def test_darwin_arm64(self):
        self.assertEqual(rf.platform_key("Darwin", "arm64"), ("darwin", "arm64"))

    def test_unsupported_platform_raises_with_list(self):
        with self.assertRaises(rf.UnsupportedPlatform) as ctx:
            rf.platform_key("Windows", "AMD64")
        self.assertIn("linux/amd64", str(ctx.exception))

    def test_asset_name_strips_v(self):
        self.assertEqual(rf.asset_name("v0.1.2", "linux", "amd64"), "faultkit_0.1.2_linux_amd64.tar.gz")


class ChecksumTests(unittest.TestCase):
    NAME = "faultkit_0.1.2_linux_amd64.tar.gz"

    def test_matching_checksum_passes(self):
        data = b"binary"
        digest = hashlib.sha256(data).hexdigest()
        rf.verify_checksum(data, f"{digest}  {self.NAME}\n", self.NAME)

    def test_mismatch_raises_with_both_digests(self):
        data = b"binary"
        with self.assertRaises(rf.ChecksumMismatch) as ctx:
            rf.verify_checksum(data, "0" * 64 + f"  {self.NAME}\n", self.NAME)
        self.assertIn(hashlib.sha256(data).hexdigest(), str(ctx.exception))
        self.assertIn("0" * 64, str(ctx.exception))

    def test_missing_entry_raises(self):
        with self.assertRaises(rf.ChecksumMismatch):
            rf.verify_checksum(b"x", "abc  other.tar.gz\n", self.NAME)


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
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertIsNone(rf.read_fired(self.write(text)))
        self.assertIsNone(rf.read_fired(Path("/nonexistent/r.json")))

    def test_evidence_state_keeps_crashes_and_missing_reports_apart(self):
        self.assertEqual(rf.evidence_state(2, None), "error: faultkit exited 2")
        self.assertEqual(rf.evidence_state(4, 3), "error: faultkit exited 4")
        self.assertEqual(rf.evidence_state(0, None), rf.REPORT_ERROR)
        self.assertEqual(rf.evidence_state(3, None), rf.REPORT_ERROR)
        self.assertEqual(rf.evidence_state(0, 1), "invariant proven under fault")
        self.assertEqual(rf.evidence_state(1, 0), "invalid evidence: nothing was injected")


class ResolveTests(unittest.TestCase):
    def _resolve(self, **overrides):
        kwargs = dict(
            explicit=None, env={}, which=lambda _: None, source=None,
            cache_dir=Path("/c"), version="v0.1.2", downloader=lambda *a: Path("/d"),
        )
        kwargs.update(overrides)
        return rf.resolve_binary(**kwargs)

    def test_explicit_wins(self):
        self.assertEqual(self._resolve(explicit="/x/faultkit", env={"FAULTKIT": "/y"}, which=lambda _: "/z"), Path("/x/faultkit"))

    def test_env_beats_path(self):
        self.assertEqual(self._resolve(env={"FAULTKIT": "/y"}, which=lambda _: "/z"), Path("/y"))

    def test_path_beats_download(self):
        self.assertEqual(self._resolve(which=lambda _: "/z"), Path("/z"))

    def test_download_is_last(self):
        calls = []

        def downloader(version, cache_dir):
            calls.append((version, cache_dir))
            return Path("/d")

        self.assertEqual(self._resolve(downloader=downloader), Path("/d"))
        self.assertEqual(calls, [("v0.1.2", Path("/c"))])


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


class ManifestTests(unittest.TestCase):
    def load(self, data, links=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_text(json.dumps(data))
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
            "no invariants": {"version": 1, "invariants": []},
            "bad id": {"version": 1, "invariants": [entry(id="Not A Slug")]},
            "duplicate id": {"version": 1, "invariants": [entry(), entry()]},
            "no invariant text": {"version": 1, "invariants": [entry(invariant="")]},
            "config and scenario": {"version": 1, "invariants": [entry(scenario="llm-api-degraded")]},
            "neither config nor scenario": {"version": 1, "invariants": [entry(config=None)]},
            "empty scenario": {"version": 1, "invariants": [entry(config=None, scenario="")]},
            "gate as a string": {"version": 1, "invariants": [entry(gate="node --test")]},
            "empty gate": {"version": 1, "invariants": [entry(gate=[])]},
            "unknown mode": {"version": 1, "invariants": [entry(mode="docker")]},
            "base_url as a string": {"version": 1, "invariants": [entry(base_url="yes")]},
            "absolute config": {"version": 1, "invariants": [entry(config="/etc/hosts")]},
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

    def test_unreadable_manifest_is_a_manifest_error(self):
        with self.assertRaises(rf.ManifestError):
            rf.load_manifest(Path("/nonexistent/manifest.json"))


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
        manifest.write_text(json.dumps({"version": 1, "invariants": [entry()]}))
        with mock.patch.dict(os.environ, {"FAKE_NO_REPORT": "1", "FAKE_EXIT": "0"}):
            code, out = self.main(["--manifest", str(manifest), "--reports-dir", str(self.tmp / "reports")])
        self.assertEqual(code, rf.EXIT_INTERNAL)
        self.assertIn(rf.REPORT_ERROR, out.split("=== prove-all ===")[1])


if __name__ == "__main__":
    unittest.main()
