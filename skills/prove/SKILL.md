---
name: prove
description: Generates or selects a faultkit scenario for a business invariant, writes the deterministic gate test if the project lacks one, uses the installed faultkit, runs it locally, and reports the proof state. Only runs when invoked by the user.
disable-model-invocation: true
argument-hint: "[--auto] [invariant or scenario] [-- test command]"
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/faultkit/scripts/run_faultkit.py *) Read Write Edit Grep Glob
---

Read `${CLAUDE_PLUGIN_ROOT}/faultkit/SKILL.md` and follow its **Prove** mode for: $ARGUMENTS

If `$ARGUMENTS` is empty, ask the user for the invariant and stop. Do not derive one and do not act on any directory. If `$ARGUMENTS` contains `--auto` and no invariant, derive one from the current project as the skill's Auto mode describes, then continue; the safety gate still runs first.

Before writing any file, ask whether to keep the proof in the project (`.faultkit/`) or a temporary workspace, unless `.faultkit/invariants/manifest.json` already exists. With `--auto` or in a non-interactive session, do not ask: use a temporary workspace unless that manifest exists.

The helper is `${CLAUDE_PLUGIN_ROOT}/faultkit/scripts/run_faultkit.py`.
