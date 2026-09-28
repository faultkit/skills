---
name: values
description: Declares the business value and the unacceptable outcomes of an AI workflow in .faultkit/values.md, from the user's own words or from a review's draft, and writes the file only after the user says yes. Only runs when invoked by the user.
disable-model-invocation: true
argument-hint: "[outcomes in your own words]"
allowed-tools: Read Write Edit Grep Glob
---

Read `${CLAUDE_PLUGIN_ROOT}/faultkit/SKILL.md` and follow its **Values** mode, with `${CLAUDE_PLUGIN_ROOT}/faultkit/references/values.md`, for: $ARGUMENTS

If `$ARGUMENTS` is empty and a Review ran in this conversation, offer its draft: the Undeclared outcomes in declared mode, the inferred chain in inferred mode. With neither, ask for the business value and the unacceptable outcomes in the user's own words, one line each, and stop.

Show the whole file and ask before writing `.faultkit/values.md`. There is no `--auto`.
