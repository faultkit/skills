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

Five modes share that chain. Values declares what must never happen.
Review maps the chain and changes nothing. Harden adds the smallest guard
and the test that locks it. Prove turns an invariant into an injected
fault and reports whether the proof held. Prove all does that for every
invariant in the project and, with the user's consent, keeps each one in
`.faultkit/invariants/`, where CI can replay them.

An unacceptable outcome names the harm in the language of the business.
An invariant names the record a script reads and the condition on it
that, when it holds, prevents that outcome. Classify a sentence by what it
names: a record and a condition make an invariant; only the harm, in
business words, makes an outcome, even when a script could detect it. A
user's text can be either; classify it, never assume. A team declares its
outcomes in `.faultkit/values.md` with Values mode, and a proof names its
outcome when the file declares one.

## Modes

| Mode | When | What it does |
| --- | --- | --- |
| Values | Declare what must never happen | Writes the business value and the unacceptable outcomes to `.faultkit/values.md`, from the user's words or a review's draft, only after a yes. Changes no code. |
| Review | Assess, explain, or plan | Maps value, boundaries, silent-failure candidates, invariants, smallest recovery, residual risk. Changes no code. |
| Harden | Build or fix a workflow | Counts the invariants, asks how to proceed when several are unguarded, adds the smallest deterministic guard at each action boundary and the gate test that locks it, and offers a pull request. Runs the project's tests, not faultkit. |
| Prove | Explicitly requested fault injection | Selects or generates a faultkit scenario, writes the gate if missing, records it in the invariant manifest, uses the installed faultkit, runs it locally, reports the proof state. |
| Prove all | Explicitly requested, for the whole project | Adds every invariant to the manifest, the ones no fault expresses yet as `not_generated`, then runs every other entry and reports one proof state per invariant. |

Prove and Prove all are opt-in. Use them only when the user asks for fault
injection or faultkit by name, or answers yes when Review or Harden asks.
Never install or download faultkit yourself, and never decide on your own
to inject faults. Review and Harden end by showing their findings, asking
one question, and waiting; the user's yes is the opt-in.

## Auto mode

`--auto` anywhere in the input runs the whole chain without stopping at the
questions. Review continues straight into Prove; Harden hardens every
unguarded invariant in a row and continues into Prove or Prove all; Prove with
no invariant derives one with Review steps 0 to 3, the action
with the largest blast radius first; Prove all writes the invariants it
finds without asking. This is the mode for CI and for a user who has
already decided.

Three rules survive auto mode unchanged. The safety gate runs first and a
production signal stops the chain, flag or no flag. The chain acts on one
project, the current directory or the one named, never on a set found by
listing a parent directory. Nothing leaves the user's hands without
consent: with no one to ask, Prove and Prove all write the proof to a
temporary workspace, as "Where the proof is written" says, and Harden
prints the pull request commands instead of opening one. Without
`--auto`, every question stops and waits.

## Where the proof is written

Prove and Prove all produce a scenario, a gate test, a manifest entry, and a
report per invariant. They go into the project only with the user's
consent.

| Location | When | Layout |
| --- | --- | --- |
| Project | the user chose it, or `.faultkit/invariants/manifest.json` already exists, which is that choice made earlier | `.faultkit/invariants/` (scenarios, `manifest.json`), `.faultkit/reports/`, gates in the project's test directory, `.faultkit/reports/` in `.gitignore` |
| Workspace | otherwise, and always when no one can be asked: `--auto` or a non-interactive session | a new `mktemp -d -t faultkit-XXXXXX` directory `<ws>` with `invariants/`, `reports/`, and `tests/` for the gates; the project is not touched, not even `.gitignore` |

Unless the manifest exists, ask before the first file is written: keep the
scenarios, gates, and manifest in the project, where they can be committed
and replayed in CI, or in a temporary workspace that leaves the project
untouched? Ask once per conversation and wait for the answer. With no one
to ask, `--auto` or a non-interactive session, do not ask: use the
workspace and continue. In the steps below, `.faultkit/` stands for the
chosen location: the project's `.faultkit/`, or `<ws>/`.

A gate in the workspace still runs from the project root. It imports the
project's code by absolute path, or runs with the root on the import path
(`python -m pytest <ws>/tests/...`), and its manifest `gate` uses the
absolute path of the test. The project's own test configuration does not
apply to it. End the report with the workspace path and say that the proof
lives only there; running again and choosing the project keeps it.

The values file is the one exception to the `.faultkit/` substitution
above: it is always the project's `.faultkit/values.md`. Only Values mode
and a yes to the question of Review or Prove all write it; `--auto` never
does. With `--auto` and no values file, the inferred values are drafted to
`<ws>/values.md`, with the inferred marker line, once the workspace
exists, so the workspace manifest can carry `outcome`. A workspace
manifest never carries `values`; its run passes `--values <ws>/values.md`
when that draft exists.

The references carry the method and the faultkit knowledge. Read the one
the step names; do not reconstruct it by experiment.

- `references/business-invariants.md`: boundaries, the chain, writing an
  invariant, the two questions, recovery patterns.
- `references/silent-failure-catalog.md`: the eight shapes, S1 to S8.
- `references/faultkit-scenarios.md`: builtin scenarios mapped to shapes.
- `references/faultkit-execution.md`: custom scenarios, mode selection,
  gotchas, proof states, the gate test, the helper, safety.
- `references/values.md`: the values file, outcome versus invariant,
  proposals, linking, coverage, and when the file may be written.

## Values

Declare what must never happen. Follow `references/values.md`, "Writing
the values file".

1. Take the input: the user's words, or, with no input, the draft from a
   Review in this conversation. In declared mode the draft is its
   Undeclared outcomes; in inferred mode it is its inferred chain. With
   neither, ask for the business value and the unacceptable outcomes in
   the user's own words, one line each, and stop.
2. Classify every sentence by "Outcome or invariant". Keep invariants aside
   and name them: they belong in the manifest, not here.
3. Merge with `.faultkit/values.md` when it exists: keep every id and its
   text, and number new outcomes after the highest id. Never renumber, and
   never delete.
4. Validate against the grammar, show the whole file, and ask one question:
   write it? When the draft holds a Review's proposals, the answer can
   accept each one, drop it, or record it under `## Out of scope`; write
   the file as the answer shapes it. Wait for the answer; write only on
   yes. With no outcome left, because every sentence was an invariant,
   there is no file to write: say so and end. In a non-interactive
   session, print the file and end. There is no `--auto` for this mode.

## Review

Do not change code in this mode.

0. Read `.faultkit/values.md` if it exists, by `references/values.md`.
   Declared mode: the chain's Business value and Unacceptable outcome lines
   come from the file verbatim, each outcome line cites its `UO-n`, and the
   section is tagged `[declared]`. A file that starts with the inferred
   marker is still read in declared mode, but tagged `[inferred]`; the
   count line says `inferred` for `declared`, and the report says in one
   line that a person confirms the file by removing that marker. Inferred
   mode, with no file: infer them in step 2 and tag the section
   `[inferred]`.
1. Find the boundaries. Read `references/business-invariants.md`,
   "Boundaries to find", and list every irreversible action with its
   `file:line`. Everything else is a path to one of those.
2. Fill the chain for the action with the largest blast radius first, then
   the others. Six lines each, over the side effect, never over the model's
   words.

   In declared mode, a boundary whose worst outcome is not declared goes
   under `## Undeclared outcomes`, one line each with its `file:line`, as a
   proposal with a provisional id `UO-new-1`, `UO-new-2`, and so on. Skip
   one that means the same as a line under the file's `## Out of scope`.
   Review never writes the values file on its own.
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
## Business value              ([declared] or [inferred])
## Unacceptable outcomes       (declared: each with its UO-n)
## Boundaries found            (file:line for each irreversible action)
## Silent-failure candidates   (shape, file:line, is there a check, does it gate)
## Invariants                  (one line each, over observable state)
## Outcome coverage            (declared mode: per outcome, UO-n, the invariant ids that protect it or none, how many are provable)
## Smallest recovery           (per invariant, from the recovery patterns)
## Proof plan                  (per invariant: gate test + faultkit scenario, pinned builtin or custom)
## Undeclared outcomes         (declared mode, when any: UO-new-n, file:line)
## Residual risk
```

6. Give the proof plan one line per invariant a fault can express. Name the
   builtin scenario from `references/faultkit-scenarios.md` when one
   expresses the fault, pinned at `probability: 1.0` for the proof, and say
   "custom" with the boundary host and path when none does. An invariant no
   fault expresses goes under residual risk with the reason.
7. Show the report. Close it with one count line, where d is the declared
   or inferred outcomes, c the ones with at least one invariant, p the
   lines under Undeclared outcomes, n the lines under Invariants, and k the
   lines in the proof plan. Declared mode:
   `Outcomes: <d> declared, <c> covered, <p> proposed. Invariants: <n> found, <k> provable with faultkit.`
   with `, <p> proposed` only when p > 0. Inferred mode:
   `Outcomes: <d> inferred, none declared. Invariants: <n> found, <k> provable with faultkit.`
   With k = 0, say so and end without a question, after one line: in
   inferred mode, `/faultkit:values saves the inferred outcomes for you to correct.`;
   in declared mode with p > 0, the proposals line from step 8.
8. Otherwise ask one question and stop.
   - Declared mode: whether to run faultkit now for the primary invariant
     with Prove, naming the invariant, its outcome, the scenario, the
     injection mode, and the exact command.
   - Inferred mode: one compound question. Save the inferred business value
     and outcomes to `.faultkit/values.md` for the user to correct, run
     faultkit now for the primary invariant with Prove (named as above), or
     both?

   When k > 1, add one line under the question: `/faultkit:prove-all`
   proves all k in one go and keeps them in `.faultkit/invariants/`. When
   p > 0, add one line: `/faultkit:values` declares the p proposed
   outcomes; the draft is ready.

   Wait for the answer. Until the user says yes, do not run faultkit,
   download anything, or write a scenario, a test, or the values file. The
   answers:
   - Save: write `.faultkit/values.md` by `references/values.md`, with the
     inferred marker line. Print the Prove command, and the Prove all
     command when k > 1, then end.
   - Prove: continue with Prove from its first step, the safety gate.
   - All of them: continue with Prove all.
   - Both: write the file, then continue.

   In a non-interactive session, print the Prove command, and the Prove all
   command when k > 1, then end. With `--auto`, skip the question and
   continue with Prove at once. In inferred mode, the inferred values are
   drafted to `<ws>/values.md` after Prove's safety gate, as "Where the
   proof is written" says.

## Harden

1. Count before changing anything. Take the invariants from the input, from
   `.faultkit/invariants/manifest.json`, from a review in this conversation,
   or from Review steps 0 to 4. For each, answer Review step 3's two
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
   and stop: whether to run faultkit now to prove it, with Prove for one
   invariant or Prove all for several, and the exact command. Wait for the
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
     message naming the invariant and its outcome (`UO-n`) when it has one.
     When two invariants changed the same lines, commit them together and
     name both.
   - Push the branch and open the pull request with `gh pr create`. The
     body lists each invariant with its outcome (`UO-n`) when it has one,
     its guard at `file:line`, its gate test, and its proof state, quoting
     the `=== proof ===` block or the `=== prove-all ===` table when a proof
     ran, and saying "not proven with faultkit" when none did.
   - `git` and `gh` sign in with the user's own setup. Never read, ask for,
     print, or pass a token, and never set one in a command's environment.
   - Without `gh`, a remote, or push rights, say so and print the commands.

## Prove

Input: an invariant in words, a scenario name, or a scenario path, optionally
followed by `--` and the test command. With no input, ask for the invariant
and stop. Never derive one on your own in this mode; in a non-interactive
session print the usage and exit instead. The one exception is `--auto`:
then derive the invariant with Review steps 0 to 3, largest blast
radius first, and continue. Act on exactly one project, the
current directory or the one named in the input, never on a set of projects
found by listing a parent directory.

1. **Safety gate, before anything else.** Look for production signals:
   deploy variables, non-local database URLs, a `.env` naming a live
   account, a real provider key with a baseline that would spend it. Judge
   by names and hosts; never print, copy, or send a secret's value. If
   found, stop and say why. Confirm irreversible effects are fakes.
2. Resolve the invariant and the target command: from the arguments, from
   the project's test runner, or ask. One invariant per run. Then decide
   where the proof is written, by "Where the proof is written".
   Read `.faultkit/values.md` if it exists. When the input sentence is an
   outcome (see "Outcome or invariant" in `references/values.md`), derive
   its invariant with Review steps 1 to 3 for the boundary it names; when
   it is an invariant, keep it. A declared outcome gives the manifest entry
   its `outcome`. Name an undeclared one in one line and continue; do not
   write the values file, and ask no new question.
3. Choose the scenario with `references/faultkit-scenarios.md` and write it
   to `.faultkit/invariants/<invariant-slug>.yaml` from
   `references/faultkit-execution.md`, "Custom scenarios": the builtin's
   failure mode pinned when one expresses the fault, a custom body when
   none does. Never prove with a builtin by name: builtins fire at 5 to 20%,
   so most runs inject nothing. One scenario, `probability: 1.0`, the
   narrowest match that still fires.
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
   entry, or replace the entry with the same id. The manifest is what Prove
   all and CI replay.
   The entry carries `outcome` by "Linking invariants" in
   `references/values.md`, and so does any existing entry that protects a
   declared outcome without naming it; step 8 lists each such change as
   `link <id> -> UO-n`. Writing `outcome` makes the manifest version 3, by
   the version rules in "The invariant manifest"; a manifest that needs no
   version 3 field keeps its version.
7. Run the helper with `--verbose`, so every fired fault is visible, and let
   it print the proof block. On a terminal the block is coloured; add
   `--color always` when the output is captured for a person to read.
   Narrow a pinned failure mode to one provider with `provider:` in its
   file, not with `--provider`.

```bash
python3 <skill>/scripts/run_faultkit.py --verbose \
  --config .faultkit/invariants/<invariant-slug>.yaml \
  --report .faultkit/reports/<invariant-slug>.report.json \
  [--base-url] \
  -- <test command>
```

8. Show the user faultkit's output, not a paraphrase of it. For each run,
   one status line, then one fenced block holding faultkit's own lines
   verbatim: the `fault fired` lines, the `=== faultkit summary ===` block,
   and the `=== proof ===` block. The status line carries the state and its
   marker: ✅ invariant proven under fault, ❌ silent failure confirmed,
   ⚠️ invalid evidence: nothing was injected. When two modes were run, close
   with a two-row table: mode, faults fired, target exit, proof state. Then
   list every artifact created with its path, and each `link` from step 6.
   Run once per mode of the code
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

## Prove all

Input: optionally `--auto`, optionally the project. Act on exactly one
project, the current directory or the one named, as Prove does.

1. **Safety gate, before anything else**, exactly as Prove step 1.
2. Read `.faultkit/invariants/manifest.json` and `.faultkit/values.md` if
   they exist; the values file decides declared or inferred mode, as in
   Review step 0. The manifest's entries stay as they are: never rewrite
   an entry's scenario or gate to change a result.
3. Find the invariants with Review steps 0 to 4, every boundary,
   largest blast radius first. Keep each one a fault can express that the
   manifest does not already hold. Record each one no fault expresses as a
   `not_generated` entry with its `fault_reason`, so the manifest lists
   every invariant the project has; it never runs.
   In declared mode, find the invariants outcome by outcome first, largest
   blast radius first, then the remaining boundaries. Each new invariant
   gets `outcome` when it covers a declared one, and each existing entry
   that protects a declared outcome without naming it gets `outcome` in the
   same write, shown as `link`.
4. With new invariants or links, show them as a table (id, outcome,
   invariant, shape, scenario, mode, gate; a `not_generated` row shows its
   reason instead, a `link` row only its id and outcome) and ask one
   question: write them and run the whole
   manifest, and, unless the manifest exists, keep them in the project or
   in a temporary workspace? Say that each `not_generated` entry lowers the
   CI score, and fails faultkit/action at its default `threshold: 100`
   until it is proven.
   Add one line of coverage: which outcomes the new invariants cover, and
   each declared outcome that stays uncovered with its reason. In inferred
   mode, the same compound question also asks whether to save the inferred
   values as `.faultkit/values.md`; with `--auto` or in a non-interactive
   session, never.
   Wait for the answer. With `--auto`, skip the
   question; the location follows "Where the proof is written". In a
   non-interactive session without `--auto`, print the table and the
   command with `--auto`, and end. With nothing new and nothing to link,
   go to step 6.
5. For each new generated invariant, Prove steps 3 to 6: scenario, mode,
   gate, manifest entry. Write each `not_generated` one with its reason,
   and each link, by "The invariant manifest" in
   `references/faultkit-execution.md`. One gate
   test per invariant, named after its id, so a red row names the invariant
   that broke.
6. Run every entry with one helper call. In the project, reports land in
   `.faultkit/reports/`; add that directory to `.gitignore` when the project
   has one. The scenario files and the manifest are meant to be committed.
   In a workspace, pass `--manifest <ws>/invariants/manifest.json
   --reports-dir <ws>/reports`, and `--values <ws>/values.md` when that
   draft exists.

```bash
python3 <skill>/scripts/run_faultkit.py --verbose \
  --manifest .faultkit/invariants/manifest.json
```

7. Report as Prove step 8 does, once per invariant: a status line, then
   faultkit's lines verbatim. Close with the helper's `=== prove-all ===`
   table verbatim, then its `=== outcomes ===` table verbatim when a values
   file resolved, then list every artifact created. The helper exits with
   the worst result. A silent failure confirmed on unhardened code is the
   honest outcome of this mode; fixing it is Harden's job.

## Red flags

| Thought | Reality |
| --- | --- |
| "The tests pass, so it is resilient." | Nothing was injected. Look at `faults fired`. |
| "They will obviously want the proof, so I'll run faultkit right after the review." | Show the findings, ask, wait. The yes is the opt-in. |
| "They passed --auto, so the safety gate is just a formality." | Auto mode skips questions, never the gate. A production signal stops the chain. |
| "No invariant was given, so I'll derive one for every project I can see." | Prove with no input stops and asks. It never surveys directories. |
| "The agent's summary says it held the action." | Read the ledger. Two agents in this skill's evaluation reported actions their tools had refused. |
| "I'll set probability to 0.5 to be realistic." | Determinism is the point. A gate that fires sometimes is not a gate. |
| "A builtin expresses it, so I'll run the builtin." | Builtins fire at 5 to 20%. Pin the failure mode at 1.0 in a file, or the proof is luck. |
| "No fault fired, but the target passed, so fine." | That is invalid evidence, the most dangerous result there is. |
| "I'll add a second scenario and a conftest while I'm here." | One invariant, one scenario, the smallest gate. Every invariant at once is Prove all, and only when asked. |
| "This manifest entry is red; I'll loosen its scenario or gate so CI goes green." | Never. The entry states what must hold. Harden the code. |
| "They said run it, so writing `.faultkit/` into the project is fine." | Running is not keeping. Ask where, or use a workspace. |
| "The guards are in and the tests are green, so I'll push and open the PR." | Ask first; a pull request is published work. With `--auto`, print the commands. |
| "Let me write hostile responses to see what breaks." | The catalog states the shapes. Match the code to a shape and pick the scenario. |
| "This client probably honours the proxy." | Run once. The warning tells you. Then switch to `--base-url`. |
| "The gate should skip without faultkit so it cannot pass vacuously." | Prefer green without a fault and red under one, so ordinary CI exercises the guard. |
| "A better prompt would fix this." | Prompting is guidance. The model received "do not treat this as no payment" and escalated anyway. |
| "I'll adjust the fixture so the run passes." | Never. Report the failure. |
| "No fault expresses it, so it stays out of the manifest." | Record it as `not_generated` with the reason. The manifest lists every invariant, and CI counts it. |
| "The code implies this outcome, I'll add it to values.md." | Propose it under Undeclared outcomes. A person declares outcomes. |
| "They wrote the outcome, so the invariant is given." | An outcome is business language. Derive the invariant over the store; then prove that. |
| "No values file, so I'll skip outcomes." | Infer them, tag `[inferred]`, and offer the file. Proofs kept in the project should trace to a declared outcome. |
| "They turned that proposal down; I'll suggest it again next time." | Offer to record it under Out of scope; once there, Review never proposes it again. |
| "The outcome was declared after the proof, so it shows as uncovered." | Link the entry that protects it: set its `outcome` in the next manifest write. |
| "It's `--auto`, so I'll save the inferred values to `.faultkit/values.md`." | `--auto` is never consent. Draft `<ws>/values.md`; only Values mode or a yes writes the project's file. |
| "I'll renumber the outcomes so the ids are consecutive." | Ids are never renumbered or deleted. `UO-3` means the same thing in every commit that has it. |
| "The report is missing, so nothing fired." | A missing or malformed report is an error, never zero faults fired. |

## Quick reference

- Mode selection: `references/faultkit-execution.md`, "Choosing the
  injection mode".
- Proof states: `references/faultkit-execution.md`, "Proof states". The
  condition for hardened code is `faults fired > 0 AND invariant held`.
- Shapes: `references/silent-failure-catalog.md`, the index table.
- Builtins: `faultkit scenario list` on the installed binary, then
  `references/faultkit-scenarios.md`.
- Manifest: `references/faultkit-execution.md`, "The invariant manifest".
- Values: `references/values.md`.
