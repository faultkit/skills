# AI Resilience skill

A skill for coding agents that protects the business value of an AI workflow
when models, streams, tools, retrieval, networks, or state fail. It starts from
what must never happen, not from what the API returned.

It works on your project's checkout from a coding agent with a shell, and
Claude Code is the tested path. Proving also needs Python 3 on macOS or Linux.

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
| Values | Declare what must never happen | Writes your business value and unacceptable outcomes to `.faultkit/values.md`, from your words or a review's draft, after you say yes. Changes no code. |
| Review | Assess, explain, or plan | Maps value, boundaries, silent failures, invariants, and residual risk, and ends with how many invariants faultkit can prove. Changes no code. |
| Harden | Build or fix a workflow | Counts the invariants, asks whether to harden them one at a time, all in a row, or on your instruction, adds the smallest deterministic guard at each action boundary and the test that locks it, and asks before opening a pull request. |
| Prove | Explicitly requested fault injection | Selects or generates a faultkit scenario, writes the gate test if missing, uses your installed faultkit, runs it locally, reports the proof state. Keeps the proof in `.faultkit/invariants/` if you agree, otherwise in a temporary workspace. |
| Prove all | Explicitly requested, whole project | Adds every invariant to the manifest, the ones no fault expresses yet as `not_generated`, runs the rest, reports one proof state per invariant. Same choice of where the proof is kept. |

Prove and Prove all are opt-in. Ordinary use of the skill never injects faults, and
no mode installs anything. Review ends by asking whether to run faultkit for the
primary invariant, and names `/faultkit:prove-all` when there are more; without a
values file, the same question offers to save the inferred outcomes. Harden ends by
asking whether to prove the change, then whether to open a pull request. Each
question waits for your answer. Add `--auto` to any command to run the whole
chain without stopping at the questions. The safety gate still runs first, a
production signal still stops the chain, and `--auto` never counts as
consent: proofs go to a temporary workspace unless the project already keeps
a manifest, and Harden prints the pull request commands instead of opening
one.

## Install in Claude Code

```text
/plugin marketplace add faultkit/skills
/plugin install faultkit@faultkit
```

Prove and Prove all also need faultkit itself; see [Network access](#network-access).

Then `/faultkit:values`, `/faultkit:review`, `/faultkit:harden`,
`/faultkit:prove`, and `/faultkit:prove-all` are available, plus
`/faultkit:run`, which does the same as `prove-all`. Review and Harden also
trigger on their own when a conversation turns to resilience; `values`,
`prove`, `prove-all`, and `run` run only when you invoke them.

While the turn that invokes `prove`, `prove-all`, or `run` lasts, one shell
command runs without a permission prompt: the bundled helper,
`python3 faultkit/scripts/run_faultkit.py`, which runs the proof's test command
under faultkit. Every other shell command goes through your permission
settings.

To pick up a new version:

```bash
claude plugin marketplace update faultkit
claude plugin update faultkit@faultkit
```

## Install for other agents

Copy the `faultkit/` directory into your repository as
`.agents/skills/faultkit/` and add one line to your `AGENTS.md`:

```markdown
For AI workflow changes, read `.agents/skills/faultkit/SKILL.md` and follow it.
```

This repository is itself a working installation.

Prove and Prove all need faultkit installed; see [Network access](#network-access).

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
/faultkit:prove a paid invoice is never sent to collections -- pytest -q
```

```text
/faultkit:prove-all
```

## Declaring business values

Say once what must never happen, in `.faultkit/values.md`:

```markdown
## Business value
Paying customers are never treated as delinquent.

## Unacceptable outcomes
- UO-1: A final notice or a collections referral is issued for a paid invoice.
- UO-2: A customer is charged twice for one invoice.
```

There are three ways to declare outcomes:

- **`/faultkit:values`** takes your words, for example `/faultkit:values a
  customer is never charged twice for one invoice`. It numbers the
  outcomes, shows the file, and writes it after you say yes.
- **Answer "save" to the closing question of Review or Prove all.**
  Without a file, both infer the outcomes and offer to save them for you
  to correct.
- **Write the file yourself.** The grammar is in
  `faultkit/references/values.md`.

A Prove command also takes an outcome in your words, for example
`/faultkit:prove a paid invoice is never sent to collections`. The skill
derives the invariant to prove, and links it when the file declares that
outcome.

With the file, Review takes the business value and outcomes from it and
reports which outcomes the invariants cover. It also proposes the outcomes
it finds in the code that the file does not declare, and never adds them
itself. `/faultkit:values` declares the ones you accept.

A proof names the outcome it protects when the file declares one. The
helper prints the outcome coverage next to the proof table, including the
invariants that name no outcome, and so does faultkit/action v1.1.0 or
later in CI. Linking an outcome makes the manifest version 3, which
faultkit/action v1.0.0 rejects.

## The invariant manifest

Each invariant the skill proves can be kept in the project under
`.faultkit/invariants/`: one faultkit scenario per invariant and a
`manifest.json` mapping each one to its scenario, injection mode, and gate
test. The skill asks before writing it. Without a yes, and always with
`--auto` or in a non-interactive session, it writes into a temporary
workspace and leaves the project untouched; a project that already has a
manifest has said yes.

Invariants that no deterministic fault can express yet are kept too, as
`not_generated` entries with a reason (manifest version 2). They never run,
and CI lists them next to the proven ones. They lower the CI score, so at
faultkit/action's default `threshold: 100` each one fails the run until it
is proven; lower the threshold to accept known gaps.

Commit `.faultkit/invariants/` and the gate tests. Reports go to
`.faultkit/reports/`, which the skill adds to `.gitignore`. From the project
root, any machine with faultkit 0.1.3 or later installed (see [Network
access](#network-access)), including CI, replays every invariant with the
helper and gets one proof state per invariant. The helper is a single
standard-library Python file: use the copy in
`.agents/skills/faultkit/scripts/` when the skill is installed in the
repository, or fetch it at a pinned commit:

```bash
# faultkit 0.1.3 or later must be installed first; see Network access
curl -fsSLo run_faultkit.py \
  https://raw.githubusercontent.com/faultkit/skills/<commit-sha>/faultkit/scripts/run_faultkit.py
python3 run_faultkit.py --manifest .faultkit/invariants/manifest.json
```

It exits 0 only when every invariant that runs was proven under fault.
Otherwise it exits with the worst result: 2 if a run errored or left no
valid report, 3 if a run injected nothing, 1 if a silent failure was
confirmed. The format is in
`faultkit/references/faultkit-execution.md`, "The invariant manifest".

## The proof condition

A run counts as evidence only when

```text
faults fired > 0 AND business invariant held
```

A run in which no fault fired is invalid evidence even if the target exited
successfully; a green run that injected nothing is the most dangerous result.
The helper `faultkit/scripts/run_faultkit.py` asks faultkit for a JSON
report, counts fired events, and exits with faultkit's own code for one
scenario, or with the worst result across the manifest, so shells and CI can
branch on it. It uses faultkit from an explicit path, `$FAULTKIT`, `PATH`,
or a local source tree, in that order, and never downloads it. Without one
it stops and prints the install commands for your platform.

Runs stay in local, test, or explicitly authorized environments, with real
irreversible side effects replaced by fakes.

## Network access

The plugin's own code makes no network call. Prove and Prove all need
faultkit 0.1.3 or later installed:

```bash
brew install faultkit/tap/faultkit                            # macOS, Linux
yay -S faultkit-bin                                           # Arch Linux
go install github.com/faultkit/faultkit/cmd/faultkit@v0.1.3
```

[faultkit.dev/docs/install](https://faultkit.dev/docs/install/) lists the
other options. Without faultkit, the helper prints these commands and stops;
it never runs an install itself. Nothing about you or your project is sent,
and there is no telemetry.

Two more things reach the network, both under your control. Harden pushes a
branch and opens a pull request on your project's own remote only after you
say yes, and never with `--auto`. `git` and `gh` sign in with your own setup,
and neither command is pre-approved. The test command being proven runs as it
normally would: faultkit proxies its HTTP(S) traffic locally through a
per-run CA scoped to that process, synthetic faults never reach the real
provider, and requests that no fault matches go where your code sends them.

The plugin reads no token or API key. From the environment, the helper reads
only `FAULTKIT`, `NO_COLOR`, and `FORCE_COLOR`; the test command it runs
inherits your environment, as it would in your shell.

## Layout

- `faultkit/SKILL.md`: the skill, with its five modes
- `faultkit/references/`: the method, the silent-failure catalog, the
  faultkit scenario mapping, execution and gotchas, and the values file
- `faultkit/scripts/run_faultkit.py`: the verified runner, for one scenario
  or the whole manifest
- `skills/`: Claude Code plugin wrappers
- `evals/`: prompts and assertions the skill is tested against

faultkit is open source under Apache 2.0: [faultkit.dev](https://faultkit.dev/),
[github.com/faultkit/faultkit](https://github.com/faultkit/faultkit). This
skill is under the same licence.
