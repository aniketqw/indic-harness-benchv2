# Architecture and experiment design (Phase 2, OpenClaw, cloud models)

Status: PROPOSED design, 2026-11-25. Decided: Phase 2 tasks, OpenClaw harness, GLM-5.3-Flash + Nemotron 3 Super,
baselines before anything else. Open: scale, Track B (real RL on a small open model).

## 1. What we are asking

Phase 2 shows the models fail in specific, different ways (GLM: wrong field values, especially with Hindi files;
Nemotron: runs out of budget and writes no file). Question: can a loop that uses the grader as a reward, in the
spirit of GRPO, find runtime guidance that fixes such failures, does it transfer, and why does it work or not?

RQ1 Baseline: per model, prompt language x file language, with a measured noise floor.
RQ2 Does practice-derived guidance raise held-out scores over (a) no guidance and (b) a placebo of equal length?
RQ3 Where and why: which languages, tasks, fields and failure types change; which lessons matter?
RQ4 Transfer: new seeds of practiced tasks, unseen tasks/domains, the other model, other instruction languages.

## 2. System

```
            +----------------------- Task layer (Phase 2) -----------------------+
            | frozen upstream tasks (16)      p2gen.py: new seeds (14 tasks ok)   |
            | prompt(task, en|hi|hinglish)    inputs(task, en|hi files)           |
            +-----------------------------------+--------------------------------+
                                                | workspace tar + prompt (+ lessons)
 Trainer (Python, on Mac)                       v
 +----------------------+      +--------- Docker, internal network ---------+
 | sampler: G attempts  | ---> | OpenClaw agent container (read/write/edit/  |
 | per (task,seed,lang) |      | exec; no internet; no host mounts)          |
 |                      |      +----------------------+---------------------+
 |                      |                             | only route out
 |                      |                      +------v-------+  allow-list: chat on 2 models
 |                      |                      | rlh-proxy2   |  (blocks /api/pull, others)
 |                      |                      +------+-------+
 |                      |                             v
 |                      |                  your Ollama -> Ollama Cloud (GLM / Nemotron)
 |                      | <---- out/result.csv (tar) ----- agent container
 | grader (upstream     |
 |  grade_rows) -> field|  per-row, per-column correctness  = reward signal + failure evidence
 | reward = fields right|
 | / fields total       |
 | group advantage      |  (r - group mean)/std; no spread -> no learning
 | reflector -> lessons |  best vs worst attempt, grader row_checks as evidence
 | lesson library (<=8) |  prepended to the prompt on later attempts
 +----------------------+
```
Weights never change (cloud models). The "policy" being improved is the guidance text. This is training-free
group-relative optimization; it must not be described as RL on the model.

## 3. Reward
reward = (correct fields) / (total fields incl. extra rows) from upstream grade_rows, 0..1. Full completion (all fields)
tracked separately as the headline "fully correct". Input tampering zeroes the score upstream (already handled).
Infrastructure failures (harness error, provider 5xx) get no reward and are excluded. No speed bonus, no extra terms
(Bespoke: simple reward is more stable). Optional later: partial credit for "file written" as a diagnostic only.

## 4. Data and splits
16 tasks = 8 domains x 2. Train on freshly SEEDED instances of tasks in the training domains; evaluate on the FROZEN
upstream instances (the published benchmark) so results connect to the Phase 2 report.
Folds: 4 folds, each holds out 2 domains (4 tasks); each task is held out exactly once.
Test sets per fold: (A) frozen instances of held-out-domain tasks (cross-domain transfer), (B) frozen instances of
practiced tasks (in-seed generalization). Never practice on a frozen instance that is also a test instance.
Seeds: 03-bus-roster (4/20 valid) and 08-search-normalization (seed ignored) are excluded from seeded practice.

## 5. Conditions (each evaluated at temperature 0, same harness)
C0 baseline (no lessons); C1 placebo (equal-length generic text); C2 learned lessons; C3 shuffled lessons (random
lessons from another domain, equal length); optional C4 hand-written lessons targeting the known failure modes.
Factors: model (2) x prompt language (3) x file language (2). Repeats for noise floor on C0 first.

## 6. Procedure per model and fold
1. Baseline C0 on test sets, r repeats -> noise floor.
2. Practice epochs: per train task, S seeds, language combos, G=4 attempts at temperature 0.7.
3. Reflect on best vs worst per group (only if spread >= 0.1), grader row_checks as evidence; update library.
4. Evaluate C1, C2, C3 on the test sets. 5. Rotate fold. 6. Cross-model transfer: lessons from GLM on Nemotron and back.

## 7. Analyses ("why")
- Per-field deltas: which columns/rules flip wrong -> right; per-task and per-language effect sizes with
  task-cluster bootstrap intervals (task = unit), as in the original study.
- Failure taxonomy before/after: no file (budget), wrong values, missing/extra rows, format/header, timeout.
- Leave-one-lesson-out ablation; lesson language (English vs Hindi/Hinglish translation); lesson count.
- Cost: tokens, turns, elapsed before/after (longer prompt effect).
- Claim rule: a change counts only if it exceeds the C0 noise floor AND beats C1/C3.

## 8. Budget (be honest)
One Phase 2 attempt ~3-5 min. Baseline on the 8 pilot tasks x 3 x 2 x 2 models = 96 attempts (~2.5 h at 2 workers).
Full 192 ~ 5 h. One fold of practice at S=2, 2 lang combos, G=4: ~100-200 attempts per model per epoch. The whole
design is multi-day of cloud quota, so it is staged with go/no-go gates after each stage.

## 9. Stages and gates
S0 smoke (2 attempts) -> S1 baseline on pilot tasks -> gate: noise floor acceptable? -> S2 one fold, one model, small
practice -> gate: lessons beat placebo? -> S3 both models, all folds -> S4 analysis and report.

## 10. Track B (optional, real RL)
GRPO + LoRA on a small open model (e.g. Qwen3-1.7B/3B) using seeded Phase 2 tasks as the environment and the same
reward. Needs a GPU (shared A6000 is marginal). Separate from the cloud track; would answer "does real RL transfer",
not "can we improve GLM/Nemotron". Existing: 1.7B untrained baseline on phase-1 prompts scored 14.98/100.

## 11. Risks
Small sample and non-determinism at temperature 0; lessons may be generic or null; quota/time; GLM Flash vs flash
naming resolved (glm-5.3-flash:cloud works); our harness differs from the published relay/accounting stack, so
absolute scores may differ from the Phase 2 report: always compare to our own C0.
