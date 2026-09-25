# AI Resilience skill

A skill for coding agents that protects the business value of an AI workflow
when models, streams, tools, retrieval, networks, or state fail. It starts from
what must never happen, not from what the API returned.

```text
business value -> unacceptable outcome -> invariant -> fault -> recovery -> proof
```

Instead of asking whether a call succeeded, the skill asks whether the business
invariant still holds: a refund cannot exceed the policy limit; retrying cannot
charge twice; a partial stream cannot become a final decision; stale evidence
cannot authorize a regulated action; failure becomes an explicit degraded state,
never fabricated success. The method is tool-agnostic. faultkit is the optional
way to prove the result.

## Modes

| Mode | When | What it does |
| --- | --- | --- |
| Review | Assess, explain, or plan | Maps value, boundaries, silent failures, invariants, and residual risk. Changes no code. |
| Harden | Build or fix a workflow | Adds the smallest deterministic guard at the action boundary and the test that locks it. |
| Run | Explicitly requested fault injection | Selects or generates a faultkit scenario, writes the gate test if missing, records it in `.faultkit/invariants/`, obtains faultkit, runs it locally, reports the proof state. |
| Run all | Explicitly requested, whole project | Adds every invariant a fault can express to `.faultkit/invariants/`, runs them all, reports one proof state per invariant. |

Run and Run all are opt-in. Ordinary use of the skill neither installs tools nor
injects faults. Review and Harden end by asking whether to run it and wait
for the answer. Add `--auto` to any command to run the whole chain without
stopping at the questions; the safety gate still runs first and a production
signal still stops the chain.

## Install in Claude Code

```text
/plugin marketplace add faultkit/skills
/plugin install faultkit@faultkit
```

Then `/faultkit:review`, `/faultkit:harden`, `/faultkit:run`, and
`/faultkit:run-all` are available. The first two also trigger on their
own when a conversation turns to resilience; `run` and `run-all` run only
when you invoke them.

## Install for other agents

Copy the `faultkit/` directory into your repository as
`.agents/skills/faultkit/` and add one line to your `AGENTS.md`:

```markdown
For AI workflow changes, read `.agents/skills/faultkit/SKILL.md` and follow it.
```

This repository is itself a working installation.

## Example prompts

```text
Use the AI Resilience skill to review this refund agent. Identify the business
value, unacceptable outcomes, silent failures, deterministic invariants, and the
smallest recovery design. Do not change code.
```

```text
Use the AI Resilience skill to harden this shipment-planning workflow. A partial
model stream must never dispatch a route. Add deterministic tests.
```

```text
/faultkit:run a paid invoice is never sent to collections -- pytest -q
```

```text
/faultkit:run-all
```

## The invariant manifest

Each invariant the skill proves can be kept in the project under
`.faultkit/invariants/`: one faultkit scenario per invariant and a
`manifest.json` mapping each one to its scenario, injection mode, and gate
test. The skill asks before writing it. Without a yes, and always with
`--auto` or in a non-interactive session, it writes into a temporary
workspace and leaves the project untouched; a project that already has a
manifest has said yes. Commit the directory. Any machine, including CI,
replays every invariant with one command and gets one proof state per
invariant:

```bash
python3 faultkit/scripts/run_faultkit.py --manifest .faultkit/invariants/manifest.json
```

It exits non-zero when any invariant is broken or any run injected nothing.
The format is in `faultkit/references/faultkit-execution.md`, "The
invariant manifest".

## The proof condition

A run counts as evidence only when

```text
faults fired > 0 AND business invariant held
```

A run in which no fault fired is invalid evidence even if the target exited
successfully; a green run that injected nothing is the most dangerous result.
The helper `faultkit/scripts/run_faultkit.py` asks faultkit for a JSON
report, counts fired events, and exits with faultkit's own code so shells and
CI can branch on it. It obtains faultkit from an explicit path, `$FAULTKIT`,
`PATH`, a local source tree, or a checksum-verified download of a pinned
release, in that order. It never resolves "latest".

Runs stay in local, test, or explicitly authorized environments, with real
irreversible side effects replaced by fakes.

## Layout

- `faultkit/SKILL.md`: the skill, with its four modes
- `faultkit/references/`: the method, the silent-failure catalog, the
  faultkit scenario mapping, execution and gotchas
- `faultkit/scripts/run_faultkit.py`: the verified runner
- `skills/`: Claude Code plugin wrappers
- `evals/`: prompts and assertions the skill is tested against

faultkit is open source under Apache 2.0: [faultkit.dev](https://faultkit.dev/),
[github.com/faultkit/faultkit](https://github.com/faultkit/faultkit). This
skill is under the same licence.
