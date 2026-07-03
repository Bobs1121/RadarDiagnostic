# radarAnalyze — Phase 16 Development Plan

| Item | Value |
| ---- | ----- |
| Date | 2026-06-27 |
| Branch | `refactor/v2` |
| Baseline | Phase 15 complete; after Phase 16.4, `pytest -q` = 208 passed / 1 skipped / 2 xfailed |
| Mode | Codex plans/reviews; Copilot CLI executes scoped implementation prompts |

---

## 0. Current Progress

The project is past the Phase 14/15 stabilization work:

- Phase 14: TPE pattern expansion, dual-layer condition extraction, suppression/output window analysis, and robustness fixes are complete.
- Phase 15: prewarm, `variable_chains` caching, signal-map preloading, atomic memory writes, JSON repair, pattern decay, and legacy pattern ID migration are complete.
- Test baseline is green after excluding the script-style infrastructure verifier from pytest collection and fixing its optional identity check.

Current verified commands:

```bash
python -m pytest -q
# 208 passed, 1 skipped, 2 xfailed

python tests/test_infrastructure_verification.py
# 59 passed, 0 failed
```

The remaining high-value work is no longer broad stabilization; it is productization of the identity/material/snapshot model and broader real-case validation.

---

## 1. Execution Model

### Role split

Codex acts as the engineering brain:

- keeps the roadmap and taskboard coherent;
- decomposes each task into a small implementation prompt;
- reviews Copilot output and diffs;
- runs tests and updates docs/AGENTS when public behavior changes;
- decides whether a task is done.

Copilot CLI acts as the execution worker:

- receives one scoped prompt at a time;
- edits files or runs focused checks;
- returns a diff/test summary;
- does not choose new scope on its own.

### Copilot command template

```powershell
copilot -p "<scoped task prompt>" --allow-all-tools --allow-all-paths --no-color -s
```

For risky tasks, use read-only audit prompts first:

```powershell
copilot -p "Read-only audit: inspect <files>. Do not edit files. Return findings and proposed patch plan." --allow-all-tools --allow-all-paths --no-color -s
```

### Definition of done

Every implementation task must end with:

- focused tests for touched modules;
- `python -m pytest -q` unless the change is documentation-only;
- docs/taskboard update;
- no unrelated file rewrites.

---

## 2. Phase 16 Goal

Make identity, snapshot, material, and harness metadata feel like one coherent product surface rather than a set of partially integrated foundations.

Phase 16 deliberately avoids work blocked by missing external data. Real sc6h/cr5cb diagnosis expansion remains important, but it needs case data from the user. The unblocked path is to harden the local foundation so those cases can be added cleanly later.

---

## 3. Task Plan

### 16.0 Test Infrastructure Baseline

Status: done in this session.

Scope:

- Keep `tests/test_infrastructure_verification.py` as a direct-run verifier, not a pytest-collected module.
- Treat missing `config.identity` as valid because variant resolution already flows through `variants/default_variant`.

Acceptance:

- `python -m pytest -q` passes.
- `python tests/test_infrastructure_verification.py` passes.

Files:

- `conftest.py`
- `tests/test_infrastructure_verification.py`

### 16.1 Step-1 Prewarm Timing Harness

Priority: P0

Status: done in this session by Copilot CLI, reviewed by Codex.

Problem:

Phase 15 proves prewarm cache hits through unit tests, but the handoff still lists one deferred item: run a practical end-to-end timing check for Step 1 / source-doc initialization.

Implementation:

- Add a small non-LLM timing tool that measures `_run_prewarm()` twice and records cache-hit timing.
- Avoid full diagnosis because LLM/API availability is environment-dependent.
- Write a JSON result under `reports/` or `source_docs/<variant>/`.

Suggested entry:

```bash
python tools/measure_prewarm_timing.py --variant gen6/gwm_b26 --runs 2
```

Acceptance:

- Second run reports cache hit behavior and elapsed time.
- Tool exits non-zero only for real failures, not missing LLM API.
- Test covers JSON output shape with mocked prewarm calls.

Implemented files:

- `tools/measure_prewarm_timing.py`
- `tests/test_measure_prewarm_timing.py`

Verified commands:

```bash
python -m pytest tests/test_measure_prewarm_timing.py -q
# 1 passed

python tools/measure_prewarm_timing.py --variant gen6/gwm_b26 --runs 2 --output reports/prewarm_timing_test.json
# cache-hit runs: 0.747s and 1.270s on this machine
```

The generated `reports/prewarm_timing_test.json` file was a local verification artifact and is not kept in git.

Copilot prompt:

```text
Implement Phase 16.1. Add a small tool tools/measure_prewarm_timing.py that calls cli._run_prewarm for a variant multiple times, writes a JSON report, and avoids full diagnosis/LLM-dependent flows. Add focused tests with monkeypatching. Do not touch unrelated files. Run the focused test and report commands.
```

### 16.2 Identity Context Object in Orchestrator

Priority: P0

Status: done in this session by Codex. Copilot CLI execution was attempted but blocked by missing authentication.

Problem:

The code has `Variant`, `PackageProfile`, `Snapshot`, and `DiagnosisBundle`, but `Orchestrator` still mostly passes legacy project/config dictionaries. This increases the chance of future variant/package drift.

Implementation:

- Introduce a lightweight internal identity context helper, for example `_resolve_identity_context(config)`.
- Context should expose `variant_id`, `project_key`, `package_profile_id`, `source_docs_dir`, `memory_dir`, and resolved display names.
- Use it in report/bundle metadata and status messages first; avoid a full path migration in this phase.
- Keep legacy `-P` and existing config behavior intact.

Acceptance:

- Existing CLI calls still work.
- Diagnosis bundle metadata remains stable.
- New tests prove `gen6/gwm_b26` resolves through the context and legacy project mapping still works.

Implemented files:

- `ai/orchestrator.py`
- `tests/test_phase16_identity_context.py`

Verified commands:

```bash
python -m pytest tests/test_phase16_identity_context.py -q
# 3 passed

python tests/test_infrastructure_verification.py
# 59 passed / 0 failed

python -m pytest -q
# 202 passed / 1 skipped / 2 xfailed
```

Notes:

- Added `IdentityContext` and `_resolve_identity_context()` as a thin internal Orchestrator layer.
- Report headers now include `Variant`, `Package`, and `Project` when resolved.
- DiagnosisBundle metadata now includes the resolved identity context.
- Memory/source_docs directory behavior is unchanged except that Orchestrator now consumes the same resolved context consistently.

Copilot prompt:

```text
Implement Phase 16.2 narrowly. Add an internal identity context helper used by Orchestrator metadata/status paths without changing public CLI behavior. Preserve legacy project_key compatibility. Add focused tests for config/identity resolution and run existing identity tests. Do not migrate directories yet.
```

### 16.3 Material Registry Read Path and Prompt Injection Stub

Priority: P1

Status: done in this session by Codex.

Problem:

`MaterialRegistry` and `StructuredRequirementSet` exist, but diagnosis does not surface material status clearly. A full PDF/Excel parser can wait; the first useful step is reliable discovery and prompt-safe summarization.

Implementation:

- Add a deterministic material summary renderer.
- Include counts and high-level entries in diagnosis context when materials exist.
- Keep empty-material behavior explicit: "0 registered authoritative materials" in metadata/logs, not in the expert prompt unless useful.

Acceptance:

- Empty registry does not fail and produces clear metadata.
- A synthetic material fixture renders a bounded summary.
- No LLM dependency.

Implemented files:

- `core/materials.py`
- `ai/orchestrator.py`
- `tests/test_phase16_material_summary.py`

Verified commands:

```bash
python -m pytest tests/test_phase16_material_summary.py -q
# 3 passed

python -m pytest -q
# 205 passed / 1 skipped / 2 xfailed
```

Notes:

- Added `render_material_summary()` as a deterministic, bounded material/requirement summary renderer.
- Empty registries return counts with `prompt_text=""`, so expert prompts stay quiet.
- Orchestrator logs material counts and injects the material section into `ContextBudget` only when there is actual prompt text.

Copilot prompt:

```text
Implement Phase 16.3. Add deterministic material registry summary rendering and wire it into diagnosis metadata/context in a bounded, no-LLM way. Add tests with a synthetic registry fixture. Keep empty registry behavior clean and non-noisy.
```

### 16.4 Harness Aggregate Regression Gate

Priority: P1

Status: done in this session by Codex.

Problem:

Harness aggregate reports exist, but the local development loop still relies on remembering the right command. Add a simple gate command or script for repeatable local regression.

Implementation:

- Add `tools/run_harness_gate.py`.
- Run existing harness cases, save aggregate report, and summarize pass/fail counts.
- Allow `--allow-known-skip` for the known sc6h edge case.

Acceptance:

- Script returns 0 when current expected baseline passes.
- Test uses a mocked `HarnessRunner`.
- Docs mention the command.

Implemented files:

- `tools/run_harness_gate.py`
- `tests/test_harness_gate.py`

Verified commands:

```bash
python -m pytest tests/test_harness_gate.py -q
# 3 passed

python tools/run_harness_gate.py --allow-known-edge --output reports/harness_gate_test.json
# 5/6 passed; sc6hrcta001 allowed; exit code 0

python -m pytest -q
# 208 passed / 1 skipped / 2 xfailed
```

The generated `reports/harness_gate_test.json` file was a local verification artifact and is not kept in git.

Copilot prompt:

```text
Implement Phase 16.4. Add a local harness gate script wrapping existing HarnessRunner aggregate reporting with a stable exit code and a mocked test. Keep behavior compatible with the known skipped/edge case.
```

### 16.5 AGENTS and Handoff Refresh

Priority: P1

Status: done in this session by Codex.

Problem:

Several module docs still describe older caveats or pre-Phase-15 state. After tasks 16.1-16.4, docs must reflect the implemented surfaces.

Implementation:

- Update only affected `AGENTS.md` files and `phase15-handoff` successor notes.
- Add a short Phase 16 handoff after implementation.

Acceptance:

- Public signatures, commands, and cache behavior documented.
- No broad doc churn.

Implemented files:

- `AGENTS.md`
- `ai/AGENTS.md`
- `core/AGENTS.md`
- `tools/AGENTS.md`
- `docs/technical/phase16-handoff-2026-06-27.md`

---

## 4. Recommended Order

1. Finish with 16.5 documentation refresh.

---

## 5. Blocked / User-Provided Inputs

These remain valuable but need external data or credentials:

- sc6h and cr5cb real cases: BLF/BAG/MF4 plus problem and expected behavior.
- Full LLM semantic annotation: needs available LLM API quota.
- End-to-end full diagnosis timing: needs LLM API and representative case data.

---

## 6. Current Local Changes

This plan starts after a small test infrastructure fix:

- `conftest.py`: ignores `tests/test_infrastructure_verification.py` during pytest collection.
- `tests/test_infrastructure_verification.py`: treats `identity` as optional and validates the dict shape when present.
- `tools/measure_prewarm_timing.py`: closes the Phase 15 deferred timing check through an offline, non-diagnosis prewarm timing harness.
- `tests/test_measure_prewarm_timing.py`: verifies report output shape and cache-hit detection.
- `ai/orchestrator.py`: now owns a thin resolved `IdentityContext` for report and bundle metadata.
- `tests/test_phase16_identity_context.py`: verifies default variant, legacy project mapping, and report identity rows.
- `core/materials.py`: renders deterministic material/requirement summaries.
- `tests/test_phase16_material_summary.py`: verifies empty, populated, and truncated material summaries.
- `tools/run_harness_gate.py`: wraps HarnessRunner aggregate regression with stable exit codes.
- `tests/test_harness_gate.py`: verifies passing, known-edge, and blocking-failure behavior.

Verification:

- `python -m pytest -q`
- `python tests/test_infrastructure_verification.py`
