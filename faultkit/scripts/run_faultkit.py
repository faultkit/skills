#!/usr/bin/env python3
"""Acquire faultkit, run one scenario against a target command, evaluate the proof.

Standard library only. Prints a proof block on stdout and exits with faultkit's
own exit code so shells and CI can branch on it:

    0  invariant proven under fault (faults fired > 0, target passed)
    1  silent failure confirmed     (faults fired > 0, target failed)
    2  faultkit internal error
    3  invalid evidence             (no fault fired; the target never reached faultkit)
    4  usage error

With --manifest, runs every invariant in .faultkit/invariants/manifest.json,
prints a proof block per invariant and a summary, and exits with the worst
result: 2 if any errored, else 3 if any injected nothing, else 1 if any
silent failure was confirmed, else 0. A bad manifest exits 4.

Binary resolution, first match wins: --faultkit-bin, $FAULTKIT, faultkit on
PATH, --faultkit-source (go build), then a checksum-verified download of the
pinned release into the cache directory.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional

# Bumped deliberately, never resolved from "latest". faultkit's own supply-chain
# rule asks for roughly ten days of cooldown before adopting a new release.
PINNED_VERSION = "v0.1.2"
RELEASES_URL = "https://github.com/faultkit/faultkit/releases/download"
DEFAULT_CACHE = Path.home() / ".cache" / "faultkit"

PLATFORMS = {
    ("linux", "x86_64"): ("linux", "amd64"),
    ("linux", "amd64"): ("linux", "amd64"),
    ("linux", "aarch64"): ("linux", "arm64"),
    ("linux", "arm64"): ("linux", "arm64"),
    ("darwin", "x86_64"): ("darwin", "amd64"),
    ("darwin", "arm64"): ("darwin", "arm64"),
}

EXIT_OK, EXIT_TARGET_FAILED, EXIT_INTERNAL, EXIT_FAULT_NOT_FIRED, EXIT_USAGE = 0, 1, 2, 3, 4
MODES = ("auto", "proxy", "ebpf")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

ANSI = {"reset": "\033[0m", "bold": "\033[1m", "green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m", "magenta": "\033[35m"}
STATE_COLOR = [
    ("invariant proven under fault", "green"),
    ("silent failure confirmed", "red"),
    ("invalid evidence", "yellow"),
    ("error", "magenta"),
]


class UnsupportedPlatform(Exception):
    """No faultkit release exists for this operating system and architecture."""


class ChecksumMismatch(Exception):
    """The downloaded archive does not match the release's checksums.txt."""


class ManifestError(Exception):
    """The invariant manifest is unreadable or an entry is malformed."""


def platform_key(system: Optional[str] = None, machine: Optional[str] = None) -> tuple[str, str]:
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    try:
        return PLATFORMS[(system, machine)]
    except KeyError:
        supported = ", ".join(sorted({f"{o}/{a}" for o, a in PLATFORMS.values()}))
        raise UnsupportedPlatform(
            f"{system}/{machine} has no faultkit release; supported: {supported}"
        ) from None


def asset_name(version: str, os_name: str, arch: str) -> str:
    return f"faultkit_{version.lstrip('v')}_{os_name}_{arch}.tar.gz"


def verify_checksum(data: bytes, checksums_txt: str, name: str) -> None:
    expected = None
    for line in checksums_txt.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == name:
            expected = parts[0]
    actual = hashlib.sha256(data).hexdigest()
    if expected is None:
        raise ChecksumMismatch(f"{name} is not listed in checksums.txt (actual sha256 {actual})")
    if expected != actual:
        raise ChecksumMismatch(f"sha256 mismatch for {name}: expected {expected}, actual {actual}")


def _fetch(url: str) -> bytes:
    # The host is fixed to GitHub releases and the version is pinned; nothing
    # user-controlled reaches this URL.
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
        return response.read()


def download(version: str, cache_dir: Path) -> Path:
    os_name, arch = platform_key()
    target = cache_dir / version / "faultkit"
    if target.exists():
        return target
    name = asset_name(version, os_name, arch)
    base = f"{RELEASES_URL}/{version}"
    archive = _fetch(f"{base}/{name}")
    verify_checksum(archive, _fetch(f"{base}/checksums.txt").decode(), name)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        member = next(m for m in tar.getmembers() if m.isfile() and m.name.rstrip("/").endswith("faultkit"))
        source = tar.extractfile(member)
        if source is None:
            raise ChecksumMismatch(f"{name} contains no faultkit binary")
        with source, target.open("wb") as dst:
            shutil.copyfileobj(source, dst)
    target.chmod(0o755)
    return target


def build_from_source(source: Path, cache_dir: Path) -> Path:
    target = cache_dir / "source-build" / "faultkit"
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["go", "build", "-mod=vendor", "-o", str(target), "./cmd/faultkit"],
        cwd=source,
        check=True,
    )
    return target


def resolve_binary(
    explicit: Optional[str],
    env: dict,
    which: Callable[[str], Optional[str]],
    source: Optional[str],
    cache_dir: Path,
    version: str,
    downloader: Callable[[str, Path], Path],
) -> Path:
    if explicit:
        return Path(explicit)
    if env.get("FAULTKIT"):
        return Path(env["FAULTKIT"])
    found = which("faultkit")
    if found:
        return Path(found)
    if source:
        return build_from_source(Path(source), cache_dir)
    return downloader(version, cache_dir)


def load_manifest(path: Path) -> list[dict]:
    """Read and validate .faultkit/invariants/manifest.json; see faultkit-execution.md."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from None
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ManifestError(f'{path}: expected an object with "version": 1')
    entries = data.get("invariants")
    if not isinstance(entries, list) or not entries:
        raise ManifestError(f'{path}: "invariants" must be a non-empty list')
    seen = set()
    for i, e in enumerate(entries):
        where = f"{path}: invariants[{i}]"
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not SLUG.match(e["id"]):
            raise ManifestError(f'{where}: "id" must be a kebab-case slug')
        if e["id"] in seen:
            raise ManifestError(f'{where}: duplicate id {e["id"]}')
        seen.add(e["id"])
        if not isinstance(e.get("invariant"), str) or not e["invariant"].strip():
            raise ManifestError(f'{where}: "invariant" must state the invariant')
        if ("config" in e) == ("scenario" in e):
            raise ManifestError(f'{where}: set exactly one of "config" (a scenario file) or "scenario" (a builtin)')
        gate = e.get("gate")
        if not isinstance(gate, list) or not gate or not all(isinstance(a, str) and a for a in gate):
            raise ManifestError(f'{where}: "gate" must be the test command as a non-empty list of strings')
        if e.get("mode", "auto") not in MODES:
            raise ManifestError(f'{where}: "mode" must be one of {", ".join(MODES)}')
        if not isinstance(e.get("base_url", False), bool) or not isinstance(e.get("provider", ""), str):
            raise ManifestError(f'{where}: "base_url" must be true or false and "provider" a string')
    return entries


def build_command(
    binary: Path, *, report: str, target: list[str], config: Optional[str] = None,
    scenario: Optional[str] = None, mode: str = "auto", base_url: bool = False,
    provider: Optional[str] = None, verbose: bool = False,
) -> list[str]:
    command = [str(binary), "run"]
    command += ["--config", config] if config else ["--scenario", str(scenario)]
    command += ["--report", report, "--mode", mode]
    if base_url:
        command.append("--base-url")
    if provider:
        command += ["--provider", provider]
    if verbose:
        command.append("--verbose")
    return command + ["--", *target]


def run_one(command: list[str], report: Path) -> tuple[int, int]:
    """Run faultkit and count fired faults. Returns (exit code, faults fired)."""
    report.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(command)
    try:
        with report.open(encoding="utf-8") as handle:
            return completed.returncode, fired_count(json.load(handle))
    except (OSError, ValueError) as exc:
        # Counting 0 makes the proof state "invalid evidence", never a false pass.
        print(f"warning: could not read report {report}: {exc}; counting 0 faults fired", file=sys.stderr)
        return completed.returncode, 0


def fired_count(report: dict) -> int:
    return sum(1 for event in report.get("events") or [] if event.get("fired"))


def proof_state(exit_code: int, fired: int) -> str:
    nothing_injected = exit_code == EXIT_FAULT_NOT_FIRED or (
        fired == 0 and exit_code in (EXIT_OK, EXIT_TARGET_FAILED)
    )
    if nothing_injected:
        return "invalid evidence: nothing was injected"
    if exit_code == EXIT_TARGET_FAILED:
        return "silent failure confirmed"
    if exit_code == EXIT_OK:
        return "invariant proven under fault"
    return f"error: faultkit exited {exit_code}"


def aggregate_exit(states: list[str]) -> int:
    """Worst result across invariants. Invalid evidence outranks a confirmed failure."""
    if any(s.startswith("error") for s in states):
        return EXIT_INTERNAL
    if any(s.startswith("invalid evidence") for s in states):
        return EXIT_FAULT_NOT_FIRED
    if "silent failure confirmed" in states:
        return EXIT_TARGET_FAILED
    return EXIT_OK


def use_color(mode: str, isatty: bool, env: dict) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    if env.get("NO_COLOR"):
        return False
    if env.get("FORCE_COLOR"):
        return True
    return isatty


def paint(text: str, color: str, enabled: bool) -> str:
    return f"{ANSI[color]}{text}{ANSI['reset']}" if enabled else text


def state_color(state: str) -> str:
    return next(c for prefix, c in STATE_COLOR if state.startswith(prefix))


def render_proof(scenario: str, mode: str, fired: int, exit_code: int, state: str, report: str, color: bool) -> str:
    return "\n".join(
        [
            paint("=== proof ===", "bold", color),
            f"scenario:      {scenario}",
            f"mode:          {mode}",
            f"faults fired:  {paint(str(fired), 'green' if fired else 'yellow', color)}",
            f"target exit:   {exit_code}",
            f"proof state:   {paint(state, state_color(state), color)}",
            f"report:        {report}",
        ]
    )


def render_summary(rows: list[tuple[str, int, int, str]], color: bool) -> str:
    """rows: (invariant id, faults fired, target exit, proof state)."""
    width = max(len("invariant"), *(len(row[0]) for row in rows))
    lines = [paint("=== run-all ===", "bold", color), f"{'invariant':<{width}}  fired  exit  proof state"]
    for ident, fired, exit_code, state in rows:
        lines.append(f"{ident:<{width}}  {fired:>5}  {exit_code:>4}  {paint(state, state_color(state), color)}")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    if "--" in argv:
        split = argv.index("--")
        own, target = argv[:split], argv[split + 1:]
    else:
        own, target = argv, []
    parser = argparse.ArgumentParser(
        prog="run_faultkit.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", help="scenario YAML file")
    parser.add_argument("--scenario", help="builtin scenario name, instead of --config")
    parser.add_argument("--report", help="where faultkit writes its JSON report")
    parser.add_argument("--manifest", help="run every invariant in this manifest instead of one scenario")
    parser.add_argument(
        "--reports-dir", default=".faultkit/reports",
        help="with --manifest: where each invariant's report is written (default .faultkit/reports)",
    )
    parser.add_argument("--faultkit-bin", help="explicit faultkit binary")
    parser.add_argument("--faultkit-source", help="faultkit source tree to build with go")
    parser.add_argument(
        "--faultkit-version", default=PINNED_VERSION,
        help=f"release to download when nothing else resolves (default {PINNED_VERSION})",
    )
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    parser.add_argument(
        "--base-url", action="store_true",
        help="inject *_BASE_URL instead of HTTPS_PROXY (Node fetch, filtered subprocesses)",
    )
    parser.add_argument("--provider", help="limit failure modes to one provider")
    parser.add_argument("--mode", default="auto", choices=MODES)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--color", default="auto", choices=["auto", "always", "never"],
        help="colour the proof block (auto: when stdout is a terminal; NO_COLOR and FORCE_COLOR are honoured)",
    )
    ns = parser.parse_args(own)
    if ns.manifest:
        if ns.config or ns.scenario or ns.report or target or ns.base_url or ns.provider or ns.mode != "auto":
            parser.error("--manifest sets scenario, report, mode, and target per invariant; drop the other run flags")
        return ns, target
    if bool(ns.config) == bool(ns.scenario):
        parser.error("set exactly one of --config or --scenario (or use --manifest)")
    if not ns.report:
        parser.error("--report is required")
    if not target:
        parser.error("missing target command after --")
    return ns, target


def run_all(ns: argparse.Namespace, entries: list[dict], binary: Path, color: bool) -> int:
    manifest_dir = Path(ns.manifest).parent
    rows = []
    for e in entries:
        print(paint(f"=== invariant: {e['id']} ===", "bold", color), flush=True)
        print(e["invariant"], flush=True)
        config = str(manifest_dir / e["config"]) if "config" in e else None
        report = Path(ns.reports_dir) / f"{e['id']}.report.json"
        mode = e.get("mode", "auto")
        command = build_command(
            binary, report=str(report), target=e["gate"], config=config, scenario=e.get("scenario"),
            mode=mode, base_url=e.get("base_url", False), provider=e.get("provider"), verbose=ns.verbose,
        )
        exit_code, fired = run_one(command, report)
        state = proof_state(exit_code, fired)
        print(render_proof(
            config or e["scenario"], "base-url" if e.get("base_url") else mode,
            fired, exit_code, state, str(report), color,
        ), flush=True)
        rows.append((e["id"], fired, exit_code, state))
    print(render_summary(rows, color), flush=True)
    return aggregate_exit([row[3] for row in rows])


def main(argv: Optional[list[str]] = None) -> int:
    ns, target = parse_args(sys.argv[1:] if argv is None else argv)
    entries = []
    if ns.manifest:
        try:
            entries = load_manifest(Path(ns.manifest))
        except ManifestError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
    try:
        binary = resolve_binary(
            ns.faultkit_bin, dict(os.environ), shutil.which, ns.faultkit_source,
            Path(ns.cache_dir), ns.faultkit_version, download,
        )
    except (UnsupportedPlatform, ChecksumMismatch, subprocess.CalledProcessError, OSError) as exc:
        print(f"error: could not obtain faultkit: {exc}", file=sys.stderr)
        return EXIT_INTERNAL

    color = use_color(ns.color, sys.stdout.isatty(), dict(os.environ))
    if ns.manifest:
        return run_all(ns, entries, binary, color)

    command = build_command(
        binary, report=ns.report, target=target, config=ns.config, scenario=ns.scenario,
        mode=ns.mode, base_url=ns.base_url, provider=ns.provider, verbose=ns.verbose,
    )
    exit_code, fired = run_one(command, Path(ns.report))
    print(render_proof(
        ns.config or ns.scenario, "base-url" if ns.base_url else ns.mode, fired, exit_code,
        proof_state(exit_code, fired), ns.report, color,
    ), flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
