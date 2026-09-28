# Declared values

A team says once what must never happen. The skill proves, on every run,
that the invariants protecting it still hold. `.faultkit/values.md` holds
the first two links of the chain:

```text
business value -> unacceptable outcome -> invariant -> fault -> recovery -> proof
```

The file is small, written in the team's own words, and committed with the
code, so a change to it is reviewed like any other change. Nothing in it is
sent anywhere.

## The file

```markdown
---
workflow: collections-agent
domains: [payments, collections]
---
## Business value
Paying customers are never treated as delinquent.

## Unacceptable outcomes
- UO-1: A final notice or a collections referral is issued for a paid invoice.
- UO-2: A customer is charged twice for one invoice.

## Out of scope
- Wrong tone in a reminder email.
```

| Rule | Detail |
| --- | --- |
| Encoding | UTF-8 |
| Frontmatter | Optional. `workflow` (string), `domains` (list of strings), `owner` (string). Unknown keys are ignored. |
| Sections | `## ` headings, matched case-insensitively after trimming. `## Business value` and `## Unacceptable outcomes` are required; `## Out of scope` is optional; other sections are ignored. |
| Business value | The section's text, trimmed; must not be empty. |
| Outcome | A line matching `^- (UO-\d+): (.+)$` inside Unacceptable outcomes. Nothing else is an outcome. Ids are unique; at least one is required. |
| Out of scope | Each `- ` line in that section. |
| Inferred marker | A first line `<!-- inferred by faultkit; not declared by a person -->` marks a file the skill drafted. HTML comments are otherwise ignored. |
| Errors | Name the line. The helper exits 4 on a bad file. |

Ids are never renumbered or deleted. New outcomes continue the numbering, so
`UO-3` means the same thing in every commit that has it.

## Outcome or invariant

An unacceptable outcome is written in the language of the business: "a
customer is charged twice for one invoice". An invariant is a
deterministic statement over observable state that, when it holds,
prevents the outcome: "no invoice has two charge rows in the ledger".

The test from `business-invariants.md` decides which one a sentence is. If
a script could check it from the store with the model switched off, it is
an invariant. Otherwise it is an outcome, and its invariant is still to be
derived. A user's sentence can be either. Classify it; never assume.
Invariants belong in the manifest, not in this file.

## Declared and inferred

| Mode | When | Review's chain |
| --- | --- | --- |
| Declared | `.faultkit/values.md` exists | Business value and Unacceptable outcomes verbatim from the file, each outcome citing its `UO-n`, tagged `[declared]` |
| Inferred | no file | inferred from the code as before, tagged `[inferred]` |

A proof is complete without a values file. Proofs kept in the project
should still trace to a declared outcome, so Review offers to save the
inferred values.

## Writing the values file

There are three ways to declare outcomes:

1. **Values mode (`/faultkit:values`).** It takes the user's words or a
   Review's draft, shows the file, and writes it after a yes.
2. **Review's closing question.** In inferred mode, the user can answer
   "save".
3. **By hand.** Edit the file directly; the grammar above is all there is.

When writing:

- Take the user's sentences one by one. Classify each by "Outcome or
  invariant". Keep invariants aside and say so: "these are invariants; they
  belong in the manifest, not here".
- Number new outcomes after the highest existing id. Never renumber, and
  never delete.
- Validate against the grammar, show the whole file, and ask before
  writing. There is no `--auto` for this file.
- An existing file is merged, not replaced: keep every id and its text,
  and append.
- A file the skill drafted from inferences starts with the inferred marker
  line. It stays until a person edits the file and removes it.

Only Values mode and a yes to Review's closing question write
`.faultkit/values.md`. `--auto` never writes it. With `--auto`, Review
drafts `<ws>/values.md` with the inferred marker line, so the workspace
manifest can carry `values` and `outcome`.

## Proposals and out of scope

In declared mode, Review compares the boundaries it finds with the declared
outcomes. A boundary whose worst outcome is not declared goes under
`## Undeclared outcomes`, one line each with its `file:line`, as a proposal
with a provisional id `UO-new-1`, `UO-new-2`, and so on. Review never writes
the file.

- **Accepting a proposal.** Values mode, run with no argument after that
  Review, offers the proposals as the draft. Accepted ones get the next
  `UO-n`.
- **Rejecting a proposal.** Values mode offers to record the rejected
  outcome under `## Out of scope`.
- **Out of scope stays out.** Review never proposes an outcome that means
  the same as an `## Out of scope` line. The skill judges the meaning, not
  the wording.

## Linking invariants

A manifest entry names the outcome it protects with `outcome: "UO-n"`
(manifest version 3; see `faultkit-execution.md`, "The invariant
manifest").

- Several invariants may share an outcome. An invariant may have no
  outcome.
- An outcome can be declared after an invariant that already protects it.
  In that case the next Prove or Prove all sets the entry's `outcome` in the
  same manifest write as its other changes, and shows it as `link`. This
  needs no new question; it is the same file under the same consent.

## Coverage

For each declared outcome, in id order, coverage lists the invariants that
name it and their worst proof state. The order, worst first:

1. `error`
2. `silent failure confirmed`
3. `invalid evidence`
4. `fault not generated`
5. `invariant proven under fault`

An outcome no invariant names is uncovered: `no invariant yet`.

- **Counts.** Coverage counts `declared`, `covered`, and `uncovered`
  outcomes, plus `unlinked invariants`: manifest entries that name no
  outcome.
- **Where coverage appears.** Review's `## Outcome coverage`, the helper's
  `=== outcomes ===` table, and the CI report.
- **CI.** Coverage never changes the helper's exit code. In CI, an
  uncovered outcome is reported, not failed, unless the project opts in.
