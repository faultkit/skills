---
name: run
description: Same as prove-all. Finds every business invariant in the project, keeps each as a faultkit scenario and gate in .faultkit/invariants/ (or as not_generated when no fault expresses it yet), runs them locally, and reports one proof state per invariant. Only runs when invoked by the user.
disable-model-invocation: true
argument-hint: "[--auto] [project path]"
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/faultkit/scripts/run_faultkit.py *) Read Write Edit Grep Glob
---

Read `${CLAUDE_PLUGIN_ROOT}/faultkit/SKILL.md` and follow its **Prove all** mode for: $ARGUMENTS

Before writing new invariants, show them, ask whether to write them and whether to keep them in the project or a temporary workspace, and wait for the answer. If `$ARGUMENTS` contains `--auto`, do not ask; write into a temporary workspace unless `.faultkit/invariants/manifest.json` already exists. The safety gate still runs first.

The helper is `${CLAUDE_PLUGIN_ROOT}/faultkit/scripts/run_faultkit.py`.
