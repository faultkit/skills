# faultkit execution

How to turn an invariant into a run that produces evidence. Everything here
was learned by doing it against real agents; the gotchas are the ones that
cost the most time.

## Custom scenarios

Record the six lines first. If any is blank, the scenario is not ready.

```text
Business value:
Unacceptable outcome:
Business invariant:
Boundary host and path:
Synthetic response:
Expected safe outcome:
```

Then the YAML:

```yaml
name: <invariant-slug>
description: <one line: what the synthetic response pretends to be>
experiments:
  - name: <fault-name>
    fault:
      http_status: 200
      response_headers:
        Content-Type: application/json
      response_body: '<verbatim JSON, the real service's shape>'
    match:
      host: "<host glob>"
      path: <path glob>
    probability: 1.0
```

When a builtin expresses the fault, pin its failure mode instead of writing
a body. Copy the experiment from `faultkit scenario show <builtin>` and raise
its probability; faultkit still sends each provider's own response:

```yaml
name: <invariant-slug>
description: <builtin> pinned at probability 1.0
experiments:
  - name: <fault-name>
    failure: <the builtin's failure mode>
    probability: 1.0
```

Add `provider: <id>` to narrow it to one provider. The rate-limit mode keeps
the builtin's `Retry-After: 30`; for a retry path, see the gotchas.

Rules:

- `probability: 1.0`. Determinism is the point. A run that fires sometimes
  cannot be a gate.
- The narrowest `match` that still fires. A `path` glob almost always; a
  `host` glob only when the same path exists on several hosts you do not
  want to touch.
- `response_body` verbatim, in the real service's shape, with nothing
  invented. A stale snapshot omits data; it does not fabricate any.
- One scenario per invariant. A second failure mode is a second file.
- Put the file under `.faultkit/invariants/<invariant-slug>.yaml`, or
  `<ws>/invariants/` in a workspace, and record it in the manifest; see
  "The invariant manifest".

Three worked examples, one per shape that needs a custom scenario:

**S1, valid but wrong, cold-chain dispatch.** Match `host: "*"`, `path:
/v1/chat/completions`. The body is a complete chat completion whose tool
call selects the route that breaches two weather limits, with a plausible
reason. Every structural check passes; only the policy check can catch it.

**S2, resilience hides failure, support triage.** Match `host:
api.openai.com`, `path: /v1/chat/completions`, `http_status: 503`,
`Retry-After: "1"`. Every call fails, the retry layers exhaust, the fallback
answers. The short `Retry-After` is deliberate; see the gotchas.

**S3, stale evidence, collections.** Match `host: "*"`, `path: /payments*`,
`http_status: 200`, a payments body with `"source": "replica"`, an `as_of`
days old, and the settling payment absent. The model is never touched and
the loop runs to its wrong conclusion.

## Choosing the injection mode

| Target | Mode | Why |
| --- | --- | --- |
| Python, Go, curl, most libc clients calling a provider | forward proxy (default) | they honour `HTTPS_PROXY` and the injected CA bundle |
| Node global `fetch`, undici, SDKs in a filtered subprocess | `--base-url` | they ignore proxy env; faultkit injects `OPENAI_BASE_URL` and friends |
| Bedrock via boto3 or the AWS SDKs | forward proxy | SigV4 survives the MITM; base-URL rewriting breaks it |
| A tool's backend service, local or remote | forward proxy, `host: "*"` or the host, plus a `path` glob | model calls pass through untouched; the loop keeps running |
| Syscall-level faults | eBPF, Linux, privileges | outside the runner; give the user the command |

When unsure whether a client honours proxy env, run once in forward-proxy
mode. If faultkit prints `warning: no requests reached faultkit`, switch to
`--base-url`. That warning is never something to work around by editing
the scenario.

## Gotchas

**Base-URL mode needs a provider host.** faultkit decides which environment
variable to inject from the scenario's `host`, so it must be a provider it
knows: `api.openai.com`, `api.anthropic.com`. `host: "*"` does not work in
`--base-url` mode.

**The builtin rate-limit fixture sends `Retry-After: 30`.** SDKs honour it.
A six-request retry storm becomes three minutes of sleeping. For any retry
or fallback path, write a raw 503 or 429 with `Retry-After: "1"`.

**Forward-proxy mode intercepts loopback too.** It sets `HTTP_PROXY` and no
`NO_PROXY`, so a mock service on `127.0.0.1` is faulted like any other host.
`--base-url` mode is the opposite: it sets `NO_PROXY=127.0.0.1,localhost`.

**Synthetic faults never reach the provider.** A fully synthetic fault skips
the upstream round trip. Running a faulted scenario with a real key
exported costs nothing and works offline. Only the un-faulted baseline
spends tokens.

**"No requests reached faultkit" is invalid evidence.** The target never
used the proxy or the injected base URL. The run may print a green test
result; it proved nothing. Exit code 3 says the same thing.

**Every synthetic response carries `X-Faultkit-Synthetic: true`.** Useful in
an outcome object for diagnostics, never as an input to a decision.

**A faulted model call stops an agent loop at step one.** With
`probability: 1.0` on the model host, the first call fails and the loop
never reaches its tools. Loop failures are reproduced by faulting a tool's
path while the model passes through.

## Proof states

faultkit exits 0 when the target passed, 1 when it failed, 2 on an internal
error, 3 when no fault fired, 4 on a usage error. The skill reads them as
three proof states, plus two errors:

| faultkit exit | Fired | Gate | Proof state |
| --- | --- | --- | --- |
| 3 | 0 | any | `invalid evidence: nothing was injected` |
| 0 or 1 | 0 | any | `invalid evidence: nothing was injected` |
| 1 | > 0 | failed | `silent failure confirmed` |
| 0 | > 0 | passed | `invariant proven under fault` |
| 0, 1, or 3 | no valid report | | `error: report missing or malformed` |
| any other | | | `error: faultkit exited N` |

Fired is read from faultkit's report file (`"schema":
"faultkit.dev/report/v1"`), never from its console output. A manifest entry
with `fault_status: not_generated` has no run and no proof state; it is
listed as `fault not generated`.

The proof condition for hardened code is `faults fired > 0 AND invariant
held`. A target that passed with nothing fired is the most dangerous
result, because it looks like the good one. Use these exact strings; CI and
humans should read the same word.

## The gate test

A gate is deterministic when it asserts on the side effect, not on the
model's text, and when its failure message says what happened in the terms
of the business. It is green without a fault and red under one, so ordinary
CI exercises the guard too. Skip outside faultkit only when the test cannot
run at all without an injected fault.

Rules:

- Assert on the store, ledger, queue, or outbox.
- Start the failure message with `SILENT FAILURE:` and name the action, its
  source, and what was recorded.
- Never read the agent's closing summary as evidence; two agents in this
  skill's own evaluation reported actions their tools had refused.
- Never edit fixture data, weaken an assertion, or lower `probability` to
  make a run pass.

pytest:

```python
def test_unsafe_agent_never_persists_a_policy_violation(tmp_path):
    ledger = DispatchLedger(tmp_path / "ledger.jsonl")
    outcome = run_agent(ledger, mode="unsafe")
    assert outcome.business_invariant_preserved, (
        "SILENT FAILURE: HTTP 200, schema-valid tool call, but "
        f"{outcome.requested_dispatch.route_id} was dispatched with policy "
        f"violations {outcome.policy_violations}"
    )
```

`node:test`:

```js
test("a ticket the model did not classify is never auto-routed", async () => {
  const outcome = await runAgent({ mode: "unsafe" });
  assert.ok(outcome.business_invariant_preserved,
    `SILENT FAILURE: ${outcome.ticket_id} auto-routed to ` +
    `${outcome.stored.queue}/${outcome.stored.priority} with a ` +
    `${outcome.stored.sla_hours}h SLA from a ${outcome.source} classification`);
});
```

## The invariant manifest

Every invariant a run proves is kept so that CI can replay all of them.
`.faultkit/invariants/` holds one scenario file per invariant and
`manifest.json`, which maps each invariant to its scenario, injection mode,
and gate. Commit both. Reports go to `.faultkit/reports/`, which is not
committed.

This layout is written into the project only with the user's consent (see
"Where the proof is written" in `SKILL.md`). Without it, the same layout
lives in a temporary workspace `<ws>` made with `mktemp -d -t
faultkit-XXXXXX`: `<ws>/invariants/`, `<ws>/reports/`, and the gates in
`<ws>/tests/`, each gate's `gate` argv naming its test by absolute path.
The helper still runs from the project root and replays it with
`--manifest <ws>/invariants/manifest.json --reports-dir <ws>/reports`.

```json
{
  "version": 1,
  "invariants": [
    {
      "id": "triaged-only-when-model-classified",
      "invariant": "No ticket is stored as triaged unless the model produced the classification.",
      "shape": "S2",
      "config": "triaged-only-when-model-classified.yaml",
      "base_url": true,
      "gate": ["node", "--test", "test/triaged-only-when-model-classified.test.mjs"]
    }
  ]
}
```

Version 2 lists every invariant the project has, including the ones no
deterministic fault can express yet. Every entry carries `fault_status`:

```json
{
  "version": 2,
  "invariants": [
    {
      "id": "triaged-only-when-model-classified",
      "invariant": "No ticket is stored as triaged unless the model produced the classification.",
      "shape": "S2",
      "fault_status": "generated",
      "config": "triaged-only-when-model-classified.yaml",
      "base_url": true,
      "gate": ["node", "--test", "test/triaged-only-when-model-classified.test.mjs"]
    },
    {
      "id": "refund-over-limit-needs-approval",
      "invariant": "No refund over the limit is issued without a recorded human approval.",
      "shape": "S8",
      "fault_status": "not_generated",
      "fault_reason": "The approval is written by the billing service, which this project does not call over HTTP."
    }
  ]
}
```

Version 3 links each invariant to the outcome it protects, as declared in
`.faultkit/values.md` (`references/values.md`):

```json
{
  "version": 3,
  "values": ".faultkit/values.md",
  "invariants": [
    {
      "id": "paid-invoice-never-escalated",
      "outcome": "UO-1",
      "invariant": "A paid invoice is never sent to collections.",
      "shape": "S3",
      "fault_status": "generated",
      "config": "paid-invoice-never-escalated.yaml",
      "gate": ["pytest", "-q", "tests/test_paid_invoice.py"]
    }
  ]
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `values` (top level) | version 3: no | the values file, relative to the repository root; without it, `.faultkit/values.md` is used when it exists |
| `registry` (top level) | version 3: no | reserved for the scenario registry: an `https` `url` and a 40-hex commit `ref` |
| `id` | yes | kebab-case slug; names the scenario file, the gate test, and the report |
| `invariant` | yes | one sentence over observable state |
| `fault_status` | version 2: yes; version 1: never | `generated` (a scenario and a gate) or `not_generated` (no deterministic fault yet) |
| `fault_reason` | `not_generated`: yes | why no deterministic fault could be built |
| `shape` | no | silent-failure shape, S1 to S8 |
| `outcome` | version 3: no | the declared outcome this invariant protects, `UO-n`; several invariants may share one |
| `source` | version 3: no | reserved for a vendored registry scenario: `registry`, `id`, `version`, and the `sha256` of the `config` file, checked before any run |
| `config` or `scenario` | `generated`: exactly one; `not_generated`: neither | a scenario file relative to the manifest, or a builtin name (a sample, not a proof: builtins fire at 5 to 20%) |
| `mode` | no | `auto` (default), `proxy`, `ebpf` |
| `base_url` | no | `true` for `--base-url` injection |
| `provider` | no | narrow a builtin's fixture-driven failure modes to one provider; a custom scenario never needs it; `--provider` needs faultkit v0.1.3 or later |
| `gate` | `generated`: yes; `not_generated`: optional | the gate's command as an argv list, run from the project root without a shell |

Rules:

- One entry per invariant, `id` unique. Recording an invariant again
  replaces its entry; it never adds a second one.
- The gate runs that invariant's test only, so a red row names the
  invariant that broke.
- Never edit an entry's scenario, gate, or fixture to turn a red row green.
  Harden the code.
- Write version 1 while every entry is generated. When the first
  `not_generated` entry is recorded, write version 2 and add
  `"fault_status": "generated"` to every other entry.
- A `not_generated` entry never runs and never changes the helper's exit
  code. It stays in the manifest so the project's invariants are all
  listed, and it is proven once a deterministic fault exists.
- `config` is a path relative to the manifest's directory and must stay
  inside it, symlinks included.
- `values`, `registry`, `outcome`, and `source` need version 3. A version 1
  or 2 manifest that carries one is an error naming the field. Write
  version 3 when the first of them is recorded; a manifest that needs none
  keeps its version.
- Every `outcome` must be declared in the values file. An `outcome` with no
  values file is a dangling reference, and the helper exits 4.

## Running with the helper

`scripts/run_faultkit.py` acquires faultkit, runs the scenario, reads the
JSON report, and prints the proof block. It exits with faultkit's own code.
`--scenario <name>` runs a builtin as it is: a sample, not a proof.

```bash
python3 <skill>/scripts/run_faultkit.py --verbose \
  --config .faultkit/invariants/<invariant-slug>.yaml \
  --report .faultkit/reports/<invariant-slug>.report.json \
  [--base-url] [--provider openai] [--color auto|always|never] \
  -- <the project's test command>
```

With `--manifest`, it runs every entry of the manifest from the project
root, one faultkit run each, writing `.faultkit/reports/<id>.report.json`.
It prints a proof block per invariant and a closing `=== prove-all ===` table,
and exits with the worst result: 2 if any run errored, else 3 if any
injected nothing, else 1 if any silent failure was confirmed, else 0. A
malformed manifest exits 4 before anything runs.

A `not_generated` entry prints `fault not generated` with its reason, shows
`-` for fired and exit in the table, and never changes the exit code.
Before each run the helper deletes that invariant's old report. When a run
leaves no valid report, the state is `error: report missing or malformed`
and the helper exits 2; a missing report never counts as zero faults fired.

With a values file, the helper checks every `outcome` before anything
runs. It then prints a second table after `=== prove-all ===`, one row per
declared outcome, in id order. Each row lists the invariants that name the
outcome and their worst state (`error` > `silent failure confirmed` >
`invalid evidence` > `fault not generated` > `invariant proven under
fault`). An outcome no invariant names is `no invariant yet`. The helper
finds the file through `--values PATH`, else the manifest's `values`, else
`.faultkit/values.md`. The table never changes the exit code.

```text
=== outcomes ===
outcome  invariants                    worst state
UO-1     paid-invoice-never-escalated  invariant proven under fault
UO-2     fallback-never-auto-routes    silent failure confirmed
UO-3     -                             no invariant yet
declared 3, covered 2, uncovered 1, unlinked invariants 1
```

`unlinked invariants` counts manifest entries that name no outcome. Link
them, or declare the outcome they protect.

```bash
python3 <skill>/scripts/run_faultkit.py --verbose \
  --manifest .faultkit/invariants/manifest.json
```

`--verbose` makes faultkit print one line per fired fault with its host and
path, which is the evidence a reader wants to see. The proof block is
coloured when stdout is a terminal: green for proven, red for a confirmed
silent failure, yellow for invalid evidence. `NO_COLOR` and `FORCE_COLOR`
are honoured; `--color always` forces it for captured output that a person
will read.

Binary resolution, first match wins: `--faultkit-bin`, the `FAULTKIT`
environment variable, `faultkit` on `PATH`, `--faultkit-source <dir>` built
with `go build`, then a download of the pinned release for this platform
verified against the release's `checksums.txt` and cached under
`~/.cache/faultkit/<version>/`. The pinned version is a
constant in the script; it is never resolved from "latest".

The proof block:

```text
=== proof ===
scenario:      .faultkit/invariants/paid-invoice-never-escalated.yaml
mode:          auto
faults fired:  1
target exit:   1
proof state:   silent failure confirmed
report:        .faultkit/reports/paid-invoice-never-escalated.report.json
```

Run the gate under the fault once per mode of the code under test. The
unhardened path should read `silent failure confirmed`; the hardened path
should read `invariant proven under fault`. Anything else is not done yet.

## Safety

- Runs stay in local, test, or explicitly authorized environments. Before
  running, look for production signals: deploy variables, non-local database
  URLs, a `.env` naming a live account, a real provider key with a baseline
  that would spend it. Judge by names and hosts; never print, copy, or send a
  secret's value. If found, stop and say why.
- Irreversible side effects must be fakes: a JSONL ledger, an in-memory
  store, a sandbox account.
- The runner downloads only the pinned version from the fixed releases URL,
  verified by checksum.
- Never weaken a test, edit fixture data, or change a scenario's
  `probability` to make a proof pass. Report the failure instead.
