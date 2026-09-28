#!/usr/bin/env python3
"""Acquire faultkit, run one scenario against a target command, evaluate the proof.

Standard library only. Prints a proof block on stdout and exits with faultkit's
own exit code so shells and CI can branch on it:

    0  invariant proven under fault (faults fired > 0, target passed)
    1  silent failure confirmed     (faults fired > 0, target failed)
    2  faultkit internal error
    3  invalid evidence             (no fault fired; the target never reached faultkit)
    4  usage error

A missing or malformed report is "error: report missing or malformed" and
exits 2: a run counts as evidence only through faultkit's report/v1 file.

With --manifest, runs every invariant in .faultkit/invariants/manifest.json
(versions 1, 2, and 3), prints a proof block per invariant and a summary, and
exits with the worst result: 2 if any errored, else 3 if any injected
nothing, else 1 if any silent failure was confirmed, else 0. An entry with
fault_status "not_generated" never runs and never changes the exit code.
A bad manifest exits 4.

With a values file (--values, else the manifest's "values", else
.faultkit/values.md when it exists), every entry's "outcome" must be
declared in it; a bad values file or a dangling outcome exits 4.

Binary resolution, first match wins: --faultkit-bin, $FAULTKIT, faultkit on
PATH, --faultkit-source (go build), then a checksum-verified download of the
pinned release into the cache directory.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

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
PINNED_VERSION = "v0.1.3"
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

FAULT_STATUS = ("generated", "not_generated")
NOT_GENERATED = "fault not generated"
NO_INVARIANT = "no invariant yet"
# Worst first. States are matched by prefix, as in STATE_COLOR.
SEVERITY = ("error", "silent failure confirmed", "invalid evidence", "fault not generated", "invariant proven under fault")

V3_TOP = ("values", "registry")
V3_ENTRY = ("outcome", "source")
OUTCOME_ID = re.compile(r"^UO-\d+$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")

REPORT_SCHEMA = "faultkit.dev/report/v1"
REPORT_ERROR = "error: report missing or malformed"

VALUES_DEFAULT = Path(".faultkit") / "values.md"
INFERRED_MARKER = "<!-- inferred by faultkit; not declared by a person -->"
OUTCOME_LINE = re.compile(r"^- (UO-\d+): (.+)$")
FRONTMATTER_KEY = re.compile(r"^([A-Za-z_][\w-]*):(.*)$")
FRONTMATTER_ITEM = re.compile(r"^\s*- (.+)$")
SECTIONS = {"business value": "Business value", "unacceptable outcomes": "Unacceptable outcomes", "out of scope": "Out of scope"}

ANSI = {"reset": "\033[0m", "bold": "\033[1m", "green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m", "magenta": "\033[35m", "dim": "\033[2m"}
STATE_COLOR = [
    ("invariant proven under fault", "green"),
    ("silent failure confirmed", "red"),
    ("invalid evidence", "yellow"),
    ("error", "magenta"),
    ("fault not generated", "dim"),
    ("no invariant yet", "dim"),
]


class UnsupportedPlatform(Exception):
    """No faultkit release exists for this operating system and architecture."""


class ChecksumMismatch(Exception):
    """The downloaded archive does not match the release's checksums.txt."""


class ManifestError(Exception):
    """The invariant manifest is unreadable or an entry is malformed."""


@dataclass
class Manifest:
    """A validated invariant manifest. Every entry carries fault_status; v1 entries read as "generated"."""

    version: int
    entries: list[dict]
    values: Optional[str] = None
    registry: Optional[dict] = None


class ValuesError(Exception):
    """The values file breaks the grammar in references/values.md."""


@dataclass
class Outcome:
    id: str
    text: str


@dataclass
class Values:
    """A parsed .faultkit/values.md; see references/values.md."""

    business_value: str
    outcomes: list[Outcome]
    out_of_scope: list[str] = field(default_factory=list)
    workflow: Optional[str] = None
    domains: list[str] = field(default_factory=list)
    owner: Optional[str] = None
    inferred: bool = False


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


def _argv(value) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(a, str) and a for a in value)


def _check_config(manifest_dir: Path, config, where: str) -> None:
    """A scenario file is relative and resolves, symlinks included, inside the manifest's directory."""
    if not isinstance(config, str) or not config or Path(config).is_absolute():
        raise ManifestError(f'{where}: "config" must be a path relative to the manifest')
    base = manifest_dir.resolve()
    target = (manifest_dir / config).resolve()
    if target != base and base not in target.parents:
        raise ManifestError(f'{where}: "config" must stay inside {manifest_dir}')


def _check_generated(e: dict, where: str, manifest_dir: Path) -> None:
    if ("config" in e) == ("scenario" in e):
        raise ManifestError(f'{where}: set exactly one of "config" (a scenario file) or "scenario" (a builtin)')
    if "config" in e:
        _check_config(manifest_dir, e["config"], where)
    elif not isinstance(e["scenario"], str) or not e["scenario"]:
        raise ManifestError(f'{where}: "scenario" must name a builtin')
    if not _argv(e.get("gate")):
        raise ManifestError(f'{where}: "gate" must be the test command as a non-empty list of strings')


def _check_not_generated(e: dict, where: str) -> None:
    if "config" in e or "scenario" in e:
        raise ManifestError(f'{where}: a not_generated invariant has no "config" or "scenario"')
    reason = e.get("fault_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ManifestError(f'{where}: a not_generated invariant needs "fault_reason"')
    if "gate" in e and not _argv(e["gate"]):
        raise ManifestError(f'{where}: "gate" must be the test command as a non-empty list of strings')


def _check_source(e: dict, where: str, manifest_dir: Path) -> None:
    """A vendored registry scenario: its provenance, and its file's sha256, checked offline."""
    source = e["source"]
    if e["fault_status"] != "generated" or "config" not in e:
        raise ManifestError(f'{where}: "source" belongs to a generated entry with a "config" file')
    fields_ok = isinstance(source, dict) and all(
        isinstance(source.get(k), str) and source[k] for k in ("registry", "id", "version", "sha256")
    )
    if not fields_ok or not SLUG.match(source["id"]) or not SEMVER.match(source["version"]) or not SHA256_HEX.match(source["sha256"]):
        raise ManifestError(f'{where}: "source" needs "registry", a kebab-case "id", a semver "version", and a hex "sha256"')
    try:
        actual = hashlib.sha256((manifest_dir / e["config"]).read_bytes()).hexdigest()
    except OSError as exc:
        raise ManifestError(f'{where}: cannot read "config" to check "source.sha256": {exc}') from None
    if actual != source["sha256"]:
        raise ManifestError(f'{where}: "config" has sha256 {actual}, not "source.sha256" {source["sha256"]}')


def load_manifest(path: Path) -> Manifest:
    """Read and validate .faultkit/invariants/manifest.json; see faultkit-execution.md."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from None
    if not isinstance(data, dict) or data.get("version") not in (1, 2, 3):
        raise ManifestError(f'{path}: "version" must be 1, 2, or 3')
    version = data["version"]
    for name in V3_TOP:
        if name in data and version < 3:
            raise ManifestError(f'{path}: "{name}" needs "version": 3')
    values = data.get("values")
    if values is not None and (not isinstance(values, str) or not values or Path(values).is_absolute()):
        raise ManifestError(f'{path}: "values" must be a path relative to the repository root')
    registry = data.get("registry")
    if registry is not None and (
        not isinstance(registry, dict)
        or not str(registry.get("url", "")).startswith("https://")
        or not COMMIT_SHA.match(str(registry.get("ref", "")))
    ):
        raise ManifestError(f'{path}: "registry" needs an https "url" and a 40-hex commit "ref"')
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
        for name in V3_ENTRY:
            if name in e and version < 3:
                raise ManifestError(f'{where}: "{name}" needs "version": 3')
        if "outcome" in e and (not isinstance(e["outcome"], str) or not OUTCOME_ID.match(e["outcome"])):
            raise ManifestError(f'{where}: "outcome" must look like UO-1')
        if version == 1:
            if "fault_status" in e:
                raise ManifestError(f'{where}: "fault_status" needs "version": 2')
            e["fault_status"] = "generated"
        elif e.get("fault_status") not in FAULT_STATUS:
            raise ManifestError(f'{where}: "fault_status" must be "generated" or "not_generated"')
        if e["fault_status"] == "not_generated":
            _check_not_generated(e, where)
        else:
            _check_generated(e, where, path.parent)
        if "source" in e:
            _check_source(e, where, path.parent)
        if e.get("mode", "auto") not in MODES:
            raise ManifestError(f'{where}: "mode" must be one of {", ".join(MODES)}')
        if not isinstance(e.get("base_url", False), bool) or not isinstance(e.get("provider", ""), str):
            raise ManifestError(f'{where}: "base_url" must be true or false and "provider" a string')
    return Manifest(version=version, entries=entries, values=values, registry=registry)


def _uncomment(lines: list[str]) -> list[str]:
    """Each line with its HTML comments removed, including comments that span lines."""
    out, inside = [], False
    for line in lines:
        kept, rest = "", line
        while rest:
            if inside:
                end = rest.find("-->")
                rest, inside = ("", True) if end < 0 else (rest[end + 3:], False)
            else:
                start = rest.find("<!--")
                if start < 0:
                    kept, rest = kept + rest, ""
                else:
                    kept, rest, inside = kept + rest[:start], rest[start + 4:], True
        out.append(kept)
    return out


def _scalar(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def _frontmatter(lines: list[str], source: str) -> tuple[dict, dict, int]:
    """Optional frontmatter: (keys, the line number of each key, index of the first line after it)."""
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None or lines[first].strip() != "---":
        return {}, {}, 0
    keys, key_lines, key = {}, {}, None
    for i in range(first + 1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            return keys, key_lines, i + 1
        if not line.strip():
            continue
        pair, item = FRONTMATTER_KEY.match(line), FRONTMATTER_ITEM.match(line)
        if pair:
            key, raw = pair.group(1), pair.group(2).strip()
            key_lines[key] = i + 1
            if raw.startswith("[") and raw.endswith("]"):
                keys[key] = [_scalar(part) for part in raw[1:-1].split(",") if part.strip()]
            else:
                keys[key] = _scalar(raw) if raw else []
        elif item and key is not None and isinstance(keys[key], list):
            keys[key].append(_scalar(item.group(1)))
        else:
            raise ValuesError(f'{source}:{i + 1}: frontmatter line is not "key: value" or "- item"')
    raise ValuesError(f"{source}:{first + 1}: frontmatter is not closed with ---")


def parse_values(text: str, source: str = "values.md") -> Values:
    """Parse a values file by the grammar in references/values.md. Errors name the line."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = _uncomment(raw)
    keys, key_lines, start = _frontmatter(lines, source)
    sections: dict[str, tuple[int, list[tuple[int, str]]]] = {}
    current = None
    for i in range(start, len(lines)):
        line = lines[i]
        if line.startswith("## "):
            current = SECTIONS.get(line[3:].strip().lower())
            if current in sections:
                raise ValuesError(f'{source}:{i + 1}: duplicate section "## {current}"')
            if current:
                sections[current] = (i + 1, [])
        elif current:
            sections[current][1].append((i + 1, line))
    for name in ("Business value", "Unacceptable outcomes"):
        if name not in sections:
            raise ValuesError(f'{source}:1: missing "## {name}" section')
    head, body = sections["Business value"]
    business_value = "\n".join(line for _, line in body).strip()
    if not business_value:
        raise ValuesError(f'{source}:{head}: "## Business value" is empty')
    head, body = sections["Unacceptable outcomes"]
    outcomes, seen = [], set()
    for number, line in body:
        match = OUTCOME_LINE.match(line)
        if not match or not match.group(2).strip():
            continue
        if match.group(1) in seen:
            raise ValuesError(f"{source}:{number}: duplicate outcome id {match.group(1)}")
        seen.add(match.group(1))
        outcomes.append(Outcome(match.group(1), match.group(2).strip()))
    if not outcomes:
        raise ValuesError(f'{source}:{head}: "## Unacceptable outcomes" has no "- UO-n: text" line')
    out_of_scope = [
        line[2:].strip() for _, line in sections.get("Out of scope", (0, []))[1]
        if line.startswith("- ") and line[2:].strip()
    ]
    for name in ("workflow", "owner"):
        if isinstance(keys.get(name), list):
            raise ValuesError(f'{source}:{key_lines[name]}: frontmatter "{name}" must be a string')
    domains = keys.get("domains", [])
    return Values(
        business_value=business_value,
        outcomes=outcomes,
        out_of_scope=out_of_scope,
        workflow=keys.get("workflow"),
        domains=[domains] if isinstance(domains, str) else domains,
        owner=keys.get("owner"),
        inferred=raw[0].strip() == INFERRED_MARKER,
    )


def load_values(path: Path) -> Values:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValuesError(f"cannot read {path}: {exc}") from None
    return parse_values(text, str(path))


def resolve_values(explicit: Optional[str], manifest: Manifest, cwd: Path) -> Optional[Path]:
    """--values, else the manifest's "values", else .faultkit/values.md when it exists, else None."""
    if explicit:
        return Path(explicit)
    if manifest.values:
        return cwd / manifest.values
    default = cwd / VALUES_DEFAULT
    return default if default.exists() else None


def check_outcomes(manifest: Manifest, values_path: Optional[Path]) -> Optional[Values]:
    """Load the values file and check every entry's "outcome" against it. None when there is no file."""
    linked = [e for e in manifest.entries if "outcome" in e]
    if values_path is None or not values_path.exists():
        if linked:
            where = f" at {values_path}" if values_path else ""
            raise ManifestError(
                f'dangling outcome reference: {linked[0]["id"]} names {linked[0]["outcome"]}, but no values file was found{where}'
            )
        return None
    values = load_values(values_path)
    declared = {outcome.id for outcome in values.outcomes}
    for e in linked:
        if e["outcome"] not in declared:
            raise ManifestError(f'{e["id"]}: outcome {e["outcome"]} is not declared in {values_path}')
    return values


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


def run_one(command: list[str], report: Path) -> tuple[int, Optional[int]]:
    """Run faultkit. Returns (exit code, faults fired); fired is None when no valid report was written."""
    report.parent.mkdir(parents=True, exist_ok=True)
    # A report left by an earlier run must never stand in for this one.
    report.unlink(missing_ok=True)
    completed = subprocess.run(command)
    return completed.returncode, read_fired(report)


def read_fired(report: Path) -> Optional[int]:
    """Faults fired, from a report/v1 file; None when it is missing or malformed."""
    try:
        with report.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != REPORT_SCHEMA:
        return None
    if not isinstance(data.get("events") or [], list):
        return None
    return fired_count(data)


def fired_count(report: dict) -> int:
    return sum(1 for event in report.get("events") or [] if isinstance(event, dict) and event.get("fired") is True)


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


def evidence_state(exit_code: int, fired: Optional[int]) -> str:
    """The proof state, with a faultkit crash and a missing report as errors, never as evidence."""
    if exit_code not in (EXIT_OK, EXIT_TARGET_FAILED, EXIT_FAULT_NOT_FIRED):
        return f"error: faultkit exited {exit_code}"
    if fired is None:
        return REPORT_ERROR
    return proof_state(exit_code, fired)


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


def render_proof(scenario: str, mode: str, fired: Optional[int], exit_code: int, state: str, report: str, color: bool) -> str:
    return "\n".join(
        [
            paint("=== proof ===", "bold", color),
            f"scenario:      {scenario}",
            f"mode:          {mode}",
            f"faults fired:  {paint('-' if fired is None else str(fired), 'green' if fired else 'yellow', color)}",
            f"target exit:   {exit_code}",
            f"proof state:   {paint(state, state_color(state), color)}",
            f"report:        {report}",
        ]
    )


def render_summary(rows: list[tuple[str, Optional[int], Optional[int], str]], color: bool) -> str:
    """rows: (invariant id, faults fired, target exit, proof state); None prints as "-"."""
    width = max(len("invariant"), *(len(row[0]) for row in rows))
    lines = [paint("=== prove-all ===", "bold", color), f"{'invariant':<{width}}  fired  exit  proof state"]
    for ident, fired, exit_code, state in rows:
        fired_text = "-" if fired is None else str(fired)
        exit_text = "-" if exit_code is None else str(exit_code)
        lines.append(f"{ident:<{width}}  {fired_text:>5}  {exit_text:>4}  {paint(state, state_color(state), color)}")
    return "\n".join(lines)


def worst_state(states: list[str]) -> str:
    """The worst of several proof states, by SEVERITY."""
    return min(states, key=lambda state: next(i for i, prefix in enumerate(SEVERITY) if state.startswith(prefix)))


def render_outcomes(values: Values, entries: list[dict], states: dict[str, str], color: bool) -> str:
    """The === outcomes === table: each declared outcome, in id order, with its invariants and their worst state."""
    rows = []
    for outcome in sorted(values.outcomes, key=lambda o: int(o.id[3:])):
        ids = [e["id"] for e in entries if e.get("outcome") == outcome.id]
        rows.append((outcome.id, ", ".join(ids) or "-", worst_state([states[i] for i in ids]) if ids else NO_INVARIANT))
    width_id = max(len("outcome"), *(len(row[0]) for row in rows))
    width_ids = max(len("invariants"), *(len(row[1]) for row in rows))
    lines = [paint("=== outcomes ===", "bold", color), f"{'outcome':<{width_id}}  {'invariants':<{width_ids}}  worst state"]
    for ident, ids, state in rows:
        lines.append(f"{ident:<{width_id}}  {ids:<{width_ids}}  {paint(state, state_color(state), color)}")
    covered = sum(1 for row in rows if row[2] != NO_INVARIANT)
    unlinked = sum(1 for e in entries if "outcome" not in e)
    lines.append(f"declared {len(rows)}, covered {covered}, uncovered {len(rows) - covered}, unlinked invariants {unlinked}")
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
        "--values",
        help='with --manifest: the values file (default: the manifest\'s "values", else .faultkit/values.md)',
    )
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
    if ns.values and not ns.manifest:
        parser.error("--values needs --manifest")
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


def run_all(ns: argparse.Namespace, manifest: Manifest, binary: Path, color: bool, values: Optional[Values] = None) -> int:
    manifest_dir = Path(ns.manifest).parent
    rows = []
    for e in manifest.entries:
        print(paint(f"=== invariant: {e['id']} ===", "bold", color), flush=True)
        print(e["invariant"], flush=True)
        if e["fault_status"] == "not_generated":
            print(f"{paint(NOT_GENERATED, 'dim', color)}: {e['fault_reason']}", flush=True)
            rows.append((e["id"], None, None, NOT_GENERATED))
            continue
        config = str(manifest_dir / e["config"]) if "config" in e else None
        report = Path(ns.reports_dir) / f"{e['id']}.report.json"
        mode = e.get("mode", "auto")
        command = build_command(
            binary, report=str(report), target=e["gate"], config=config, scenario=e.get("scenario"),
            mode=mode, base_url=e.get("base_url", False), provider=e.get("provider"), verbose=ns.verbose,
        )
        exit_code, fired = run_one(command, report)
        state = evidence_state(exit_code, fired)
        print(render_proof(
            config or e["scenario"], "base-url" if e.get("base_url") else mode,
            fired, exit_code, state, str(report), color,
        ), flush=True)
        rows.append((e["id"], fired, exit_code, state))
    print(render_summary(rows, color), flush=True)
    if values is not None:
        print(render_outcomes(values, manifest.entries, {row[0]: row[3] for row in rows}, color), flush=True)
    return aggregate_exit([row[3] for row in rows])


def main(argv: Optional[list[str]] = None) -> int:
    ns, target = parse_args(sys.argv[1:] if argv is None else argv)
    manifest, values = None, None
    if ns.manifest:
        try:
            manifest = load_manifest(Path(ns.manifest))
            values_path = resolve_values(ns.values, manifest, Path.cwd())
            if ns.values and not values_path.exists():
                raise ValuesError(f"values file {values_path} not found")
            values = check_outcomes(manifest, values_path)
        except (ManifestError, ValuesError) as exc:
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
        return run_all(ns, manifest, binary, color, values)

    command = build_command(
        binary, report=ns.report, target=target, config=ns.config, scenario=ns.scenario,
        mode=ns.mode, base_url=ns.base_url, provider=ns.provider, verbose=ns.verbose,
    )
    exit_code, fired = run_one(command, Path(ns.report))
    state = evidence_state(exit_code, fired)
    print(render_proof(
        ns.config or ns.scenario, "base-url" if ns.base_url else ns.mode, fired, exit_code,
        state, ns.report, color,
    ), flush=True)
    return EXIT_INTERNAL if state == REPORT_ERROR else exit_code


if __name__ == "__main__":
    sys.exit(main())
