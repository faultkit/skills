---
name: run-all
description: Finds every business invariant in the project that a fault can express, keeps each as a faultkit scenario and gate in .faultkit/invariants/, runs them all locally, and reports one proof state per invariant. Only runs when invoked by the user.
disable-model-invocation: true
argument-hint: "[--auto] [project path]"
allowed-tools: Bash Read Write Edit Grep Glob
---

Read `${CLAUDE_PLUGIN_ROOT}/faultkit/SKILL.md` and follow its **Run all** mode for: $ARGUMENTS

Before writing new invariants, show them, ask, and wait for the answer. If `$ARGUMENTS` contains `--auto`, do not ask; the safety gate still runs first.

The helper is `${CLAUDE_PLUGIN_ROOT}/faultkit/scripts/run_faultkit.py`.
