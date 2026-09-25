---
name: harden
description: Use when asked to make an AI or LLM workflow resilient, add a guard, policy check, or safety boundary around an irreversible action, prevent an agent from ever doing something, or fix a finding from a resilience review.
argument-hint: "[--auto] [invariant or finding] [path]"
---

Read `${CLAUDE_PLUGIN_ROOT}/faultkit/SKILL.md` and follow its **Harden** mode for: $ARGUMENTS

Start by counting the invariants. When more than one is unguarded, ask whether to harden them one at a time, all in a row, or on the user's instruction, and wait for the answer. End by asking whether to run faultkit to prove it, then whether to open a pull request, waiting for each answer.

If `$ARGUMENTS` contains `--auto`, do not ask: harden every unguarded invariant, continue into Run or Run all, and print the pull request commands instead of opening one. The safety gate still runs first.
