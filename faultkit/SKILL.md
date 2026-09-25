---
name: faultkit
description: Use when an AI or LLM workflow, agent, or tool loop needs to be reviewed for silent failures, hardened at an irreversible action boundary, or proven under an injected fault; when someone asks what happens if the model is wrong, mentions retries or fallbacks hiding errors, stale tool data, truncated output, or wants a business invariant turned into a test. Also use when faultkit, fault injection, or a scenario YAML is mentioned in the context of an agent.
---

# AI Resilience

Protect the business value of an AI workflow when models, streams, tools,
retrieval, networks, or state fail. The question is never whether a call
returned. It is whether the business invariant still holds.

```text
business value -> unacceptable outcome -> invariant -> fault -> recovery -> proof
```

Four modes share that chain. Review maps it and changes nothing. Harden
adds the smallest guard and the test that locks it. Run turns an
invariant into an injected fault and reports whether the proof held. Run
all does that for every invariant in the project and, with the user's
consent, keeps each one in `.faultkit/invariants/`, where CI can replay
them.

## Modes

| Mode | When | What it does |
| --- | --- | --- |
| Review | Assess, explain, or plan | Maps value, boundaries, silent-failure candidates, invariants, smallest recovery, residual risk. Changes no code. |
| Harden | Build or fix a workflow | Counts the invariants, asks how to proceed when several are unguarded, adds the smallest deterministic guard at each action boundary and the gate test that locks it, and offers a pull request. Runs the project's tests, not faultkit. |
| Run | Explicitly requested fault injection | Selects or generates a faultkit scenario, writes the gate if missing, records it in the invariant manifest, obtains faultkit, runs it locally, reports the proof state. |
| Run all | Explicitly requested, for the whole project | Adds every invariant a fault can express to the manifest, then runs every entry and reports one proof state per invariant. |

Run and Run all are opt-in. Use them only when the user asks for fault
injection or faultkit by name, or answers yes when Review or Harden asks.
Never decide on your own to download a binary or inject faults. Review and
Harden end by showing their findings, asking one question, and waiting; the
user's yes is the opt-in.

## Auto mode

`--auto` anywhere in the input runs the whole chain without stopping at the
questions. Review continues straight into Run; Harden hardens every
unguarded invariant in a row and continues into Run or Run all; Run with
no invariant derives one with the first three Review steps, the action
with the largest blast radius first; Run all writes the invariants it
finds without asking. This is the mode for CI and for a user who has
already decided.

Three rules survive auto mode unchanged. The safety gate runs first and a
production signal stops the chain, flag or no flag. The chain acts on one
project, the current directory or the one named, never on a set found by
listing a parent directory. Nothing leaves the user's hands without
consent: with no one to ask, Run and Run all write the proof to a
temporary workspace, as "Where the proof is written" says, and Harden
prints the pull request commands instead of opening one. Without
`--auto`, every question stops and waits.

## Where the proof is written

Run and Run all produce a scenario, a gate test, a manifest entry, and a
report per invariant. They go into the project only with the user's
consent.

| Location | When | Layout |
| --- | --- | --- |
| Project | the user chose it, or `.faultkit/invariants/manifest.json` already exists, which is that choice made earlier | `.faultkit/invariants/` (scenarios, `manifest.json`), `.faultkit/reports/`, gates in the project's test directory, `.faultkit/reports/` in `.gitignore` |
| Workspace | otherwise, and always when no one can be asked: `--auto` or a non-interactive session | a new `mktemp -d -t faultkit-XXXXXX` directory `<ws>` with `invariants/`, `reports/`, and `tests/` for the gates; the project is not touched, not even `.gitignore` |

Unless the manifest exists, ask before the first file is written: keep the
scenarios, gates, and manifest in the project, where they can be committed
and replayed in CI, or in a temporary workspace that leaves the project
untouched? Ask once per conversation and wait for the answer. In the steps
below, `.faultkit/` stands for the chosen location: the project's
`.faultkit/`, or `<ws>/`.

A gate in the workspace still runs from the project root. It imports the
project's code by absolute path, or runs with the root on the import path
(`python -m pytest <ws>/tests/...`), and its manifest `gate` uses the
absolute path of the test. The project's own test configuration does not
apply to it. End the report with the workspace path and say that the proof
lives only there; running again and choosing the project keeps it.

The references carry the method and the faultkit knowledge. Read the one
the step names; do not reconstruct it by experiment.

- `references/business-invariants.md`: boundaries, the chain, writing an
  invariant, the two questions, recovery patterns.
- `references/silent-failure-catalog.md`: the eight shapes, S1 to S8.
- `references/faultkit-scenarios.md`: builtin scenarios mapped to shapes.
- `references/faultkit-execution.md`: custom scenarios, mode selection,
  gotchas, proof states, the gate test, the helper, safety.

## Review

Do not change code in this mode.

1. Find the boundaries. Read `references/business-invariants.md`,
   "Boundaries to find", and list every irreversible action with its
   `file:line`. Everything else is a path to one of those.
2. Fill the chain for the action with the largest blast radius first, then
   the others. Six lines each, over the side effect, never over the model's
   words.
3. Ask the two questions per candidate: is there a check, and does it gate
   anything. Name fail-open shapes by their line.
4. Classify each candidate with `references/silent-failure-catalog.md`. The
   shape decides the scenario; do not build a harness of hostile responses
   to find out what the catalog already states.
5. Write the report in exactly this shape, under 120 lines. The reader must
   see the boundary, the invariant and the proof on the first screen.
   Secondary findings are one line each under residual risk.

```markdown
# Resilience review: <workflow>
## Business value
## Unacceptable outcomes
## Boundaries found            (file:line for each irreversible action)
## Silent-failure candidates   (shape, file:line, is there a check, does it gate)
## Invariants                  (one line each, over observable state)
## Smallest recovery           (per invariant, from the recovery patterns)
## Proof plan                  (per invariant: gate test + faultkit scenario, builtin or custom)
## Residual risk
```

6. Give the proof plan one line per invariant a fault can express. Name the
   builtin scenario from `references/faultkit-scenarios.md` when one
   expresses the fault, and say "custom" with the boundary host and path
   when none does. An invariant no fault expresses goes under residual
   risk with the reason.
7. Show the report. Close it with one count line, where n is the lines
   under Invariants and k the lines in the proof plan:
   `Invariants: <n> found, <k> provable with faultkit.` With k = 0, say so
   and end without a question.
8. Otherwise ask one question and stop: whether to run faultkit now for the
   primary invariant with Run, naming the invariant, the scenario, the
   injection mode, and the exact command. When k > 1, add one line under
   the question: `/faultkit:run-all` proves all k in one go and keeps them
   in `.faultkit/invariants/`. Wait for the answer. Until the user says yes,
   do not run faultkit, download anything, or write a scenario or a test.
   On yes, continue with Run from its first step, the safety gate; on a
   request for all of them, with Run all. In a non-interactive session,
   print the Run command, and the Run all command when k > 1, and end.
   With `--auto`, skip the question and continue with Run at once.

## Harden

1. Count before changing anything. Take the invariants from the input, from
   `.faultkit/invariants/manifest.json`, from a review in this conversation,
   or from the first four Review steps. For each, answer Review step 3's two
   questions against the current code, and add its last proof state when a
   report exists in `.faultkit/reports/`. Show them as a list and close with
   one line: `Invariants: <n> found, <u> not yet guarded.` With u = 0, say
   so and end.
2. When the input named one invariant, or u = 1, harden that one.
   Otherwise ask one question and stop: harden them one at a time, stopping
   after each for a go-ahead; all in a row without stopping; or wait for the
   user's instruction on which ones and how? Wait for the answer; on "wait",
   do nothing until the instruction comes. With `--auto`, harden all in a
   row. In a non-interactive session without `--auto`, print the list and
   the command with `--auto`, and end.
3. For each invariant to harden, largest blast radius first:
   - Place the guard next to the effect, using "Recovery patterns" in
     `references/business-invariants.md`. Recompute from source data;
     separate shape from authorization; fail closed; make refusal loud;
     mark degraded output as degraded. Prefer the guard inside the adapter
     that performs the effect, so a violating write is impossible rather
     than avoided.
   - Ensure the gate test by the rules in `references/faultkit-execution.md`,
     "The gate test": it asserts on the store, its message starts with
     `SILENT FAILURE:`, it is green without a fault and red under one. A
     gate the manifest already names stays as it is.
   - Run the project's own tests. Do not run faultkit.
   - One at a time: show the diff, the test, and one paragraph naming the
     invariant and the boundary, then ask whether to go on to the next one
     and wait. On stop, go to step 4 with the ones done.
4. Show the diff, the tests, and one paragraph per invariant naming it and
   its boundary; after one at a time, one line each. Then ask one question
   and stop: whether to run faultkit now to prove it, with Run for one
   invariant or Run all for several, and the exact command. Wait for the
   answer, exactly as Review step 8 does. With `--auto`, skip the question
   and continue at once.
5. Last, after the proof when one ran, ask one question and stop: open a
   pull request with these changes? Wait for the answer. With `--auto` or in
   a non-interactive session, do not ask and do not open one; print the
   commands. On yes:
   - Follow the project's own rules for branches, commits, and pull
     requests (`CLAUDE.md`, `CONTRIBUTING.md`) where they exist.
   - Never commit to the default branch. Create `faultkit/harden-<id>` for
     one invariant, `faultkit/harden` for several.
   - One commit per invariant, in the order hardened: its guard, its gate,
     and its manifest entry when the proof is kept in the project, with a
     message naming the invariant. When two invariants changed the same
     lines, commit them together and name both.
   - Push the branch and open the pull request with `gh pr create`. The
     body lists each invariant with its guard at `file:line`, its gate
     test, and its proof state, quoting the `=== proof ===` block or the
     `=== run-all ===` table when a proof ran, and saying "not proven with
     faultkit" when none did.
   - Without `gh`, a remote, or push rights, say so and print the commands.

## Run

Input: an invariant in words, a scenario name, or a scenario path, optionally
followed by `--` and the test command. With no input, ask for the invariant
and stop. Never derive one on your own in this mode; in a non-interactive
session print the usage and exit instead. The one exception is `--auto`:
then derive the invariant with the first three Review steps, largest blast
radius first, and continue. Act on exactly one project, the
current directory or the one named in the input, never on a set of projects
found by listing a parent directory.

1. **Safety gate, before anything else.** Look for production signals:
   deploy variables, non-local database URLs, a `.env` naming a live
   account, a real provider key with a baseline that would spend it. If
   found, stop and say why. Confirm irreversible effects are fakes.
2. Resolve the invariant and the target command: from the arguments, from
   the project's test runner, or ask. One invariant per run. Then decide
   where the proof is written, by "Where the proof is written".
3. Choose the scenario with `references/faultkit-scenarios.md`. Builtin when
   it expresses the fault; otherwise a custom file from the template in
   `references/faultkit-execution.md`, "Custom scenarios", at
   `.faultkit/invariants/<invariant-slug>.yaml`. One scenario,
   `probability: 1.0`, the narrowest match that still fires.
4. Choose the injection mode from the table in
   `references/faultkit-execution.md`. Node's fetch and filtered
   subprocesses need `--base-url`; a tool's backend is faulted on its own
   path so the model passes through. Read the gotchas before writing a
   retry scenario.
5. Ensure a deterministic gate exists. If no test asserts the invariant on
   the side effect, write the smallest one in the project's runner, in the
   project's test directory or in `<ws>/tests/`. Not a suite, not a
   conftest, not a second scenario.
6. Record the invariant in `.faultkit/invariants/manifest.json` by the rules
   in `references/faultkit-execution.md`, "The invariant manifest": add its
   entry, or replace the entry with the same id. The manifest is what Run
   all and CI replay.
7. Run the helper with `--verbose`, so every fired fault is visible, and let
   it print the proof block. On a terminal the block is coloured; add
   `--color always` when the output is captured for a person to read. A
   builtin scenario takes `--scenario <name>` in place of `--config`.

```bash
python3 <skill>/scripts/run_faultkit.py --verbose \
  --config .faultkit/invariants/<invariant-slug>.yaml \
  --report .faultkit/reports/<invariant-slug>.report.json \
  [--base-url] [--provider <id>] \
  -- <test command>
```

8. Show the user faultkit's output, not a paraphrase of it. For each run,
   one status line, then one fenced block holding faultkit's own lines
   verbatim: the `fault fired` lines, the `=== faultkit summary ===` block,
   and the `=== proof ===` block. The status line carries the state and its
   marker: ✅ invariant proven under fault, ❌ silent failure confirmed,
   ⚠️ invalid evidence: nothing was injected. When two modes were run, close
   with a two-row table: mode, faults fired, target exit, proof state. Then
   list every artifact created with its path. Run once per mode of the code
   under test when the project has an unhardened and a hardened path.

```text
=== proof ===
scenario:      <path or builtin name>
mode:          proxy | base-url
faults fired:  <n>
target exit:   <code>
proof state:   invalid evidence: nothing was injected | silent failure confirmed | invariant proven under fault
report:        <json path>
```

`invalid evidence` means the target never reached faultkit. Fix the mode or
the match; never edit the scenario's probability, the fixture data, or the
assertion to change the state.

## Run all

Input: optionally `--auto`, optionally the project. Act on exactly one
project, the current directory or the one named, as Run does.

1. **Safety gate, before anything else**, exactly as Run step 1.
2. Read `.faultkit/invariants/manifest.json` if it exists. Its entries stay
   as they are: never rewrite an entry's scenario or gate to change a
   result.
3. Find the invariants with the first four Review steps, every boundary,
   largest blast radius first. Keep each one a fault can express that the
   manifest does not already hold. Name the ones no fault expresses, one
   line each with the reason; they get no entry.
4. With new invariants, show them as a table (id, invariant, shape,
   scenario, mode, gate) and ask one question: write them and run the whole
   manifest, and, unless the manifest exists, keep them in the project or
   in a temporary workspace? Wait for the answer. With `--auto`, skip the
   question; the location follows "Where the proof is written". In a
   non-interactive session without `--auto`, print the table and the
   command with `--auto`, and end. With nothing new, go to step 6.
5. For each new invariant, Run steps 3 to 6: scenario, mode, gate, manifest
   entry. One gate test per invariant, named after its id, so a red row
   names the invariant that broke.
6. Run every entry with one helper call. In the project, reports land in
   `.faultkit/reports/`; add that directory to `.gitignore` when the project
   has one. The scenario files and the manifest are meant to be committed.
   In a workspace, pass `--manifest <ws>/invariants/manifest.json
   --reports-dir <ws>/reports`.

```bash
python3 <skill>/scripts/run_faultkit.py --verbose \
  --manifest .faultkit/invariants/manifest.json
```

7. Report as Run step 8 does, once per invariant: a status line, then
   faultkit's lines verbatim. Close with the helper's `=== run-all ===`
   table verbatim, then list every artifact created. The helper exits with
   the worst result. A silent failure confirmed on unhardened code is the
   honest outcome of this mode; fixing it is Harden's job.

## Red flags

| Thought | Reality |
| --- | --- |
| "The tests pass, so it is resilient." | Nothing was injected. Look at `faults fired`. |
| "They will obviously want the proof, so I'll run faultkit right after the review." | Show the findings, ask, wait. The yes is the opt-in. |
| "They passed --auto, so the safety gate is just a formality." | Auto mode skips questions, never the gate. A production signal stops the chain. |
| "No invariant was given, so I'll derive one for every project I can see." | Run with no input stops and asks. It never surveys directories. |
| "The agent's summary says it held the action." | Read the ledger. Two agents in this skill's evaluation reported actions their tools had refused. |
| "I'll set probability to 0.5 to be realistic." | Determinism is the point. A gate that fires sometimes is not a gate. |
| "No fault fired, but the target passed, so fine." | That is invalid evidence, the most dangerous result there is. |
| "I'll add a second scenario and a conftest while I'm here." | One invariant, one scenario, the smallest gate. Every invariant at once is Run all, and only when asked. |
| "This manifest entry is red; I'll loosen its scenario or gate so CI goes green." | Never. The entry states what must hold. Harden the code. |
| "They said run it, so writing `.faultkit/` into the project is fine." | Running is not keeping. Ask where, or use a workspace. |
| "The guards are in and the tests are green, so I'll push and open the PR." | Ask first; a pull request is published work. With `--auto`, print the commands. |
| "Let me write hostile responses to see what breaks." | The catalog states the shapes. Match the code to a shape and pick the scenario. |
| "This client probably honours the proxy." | Run once. The warning tells you. Then switch to `--base-url`. |
| "The gate should skip without faultkit so it cannot pass vacuously." | Prefer green without a fault and red under one, so ordinary CI exercises the guard. |
| "A better prompt would fix this." | Prompting is guidance. The model received "do not treat this as no payment" and escalated anyway. |
| "I'll adjust the fixture so the run passes." | Never. Report the failure. |

## Quick reference

- Mode selection: `references/faultkit-execution.md`, "Choosing the
  injection mode".
- Proof states: `references/faultkit-execution.md`, "Proof states". The
  condition for hardened code is `faults fired > 0 AND invariant held`.
- Shapes: `references/silent-failure-catalog.md`, the index table.
- Builtins: `faultkit scenario list` on the installed binary, then
  `references/faultkit-scenarios.md`.
- Manifest: `references/faultkit-execution.md`, "The invariant manifest".
