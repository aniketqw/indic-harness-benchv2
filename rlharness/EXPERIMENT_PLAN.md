# Experiment plan: a small, pre-specified, matched comparison (GLM, Phase 2)

Status: PROPOSED 2026-11-25, not yet run. Goal: a result small enough to run in a few hours but designed so that, if the
tips help, we can honestly say "this is what we did, on these items, and this is what we saw".

## 1. Question
On Phase 2 tasks, does a short list of tips learned from practice attempts raise GLM-5.3-Flash's score compared with
(a) the same harness with no tips and (b) the same harness with equal-length filler text?

## 2. Why GLM only, and why these tasks
- GLM is the faster model in the published results (median 79 s per attempt vs 367 s for Nemotron), so it is the cheap
  one to iterate on. Nemotron becomes a replication if GLM shows an effect.
- Published GLM results leave room only on some tasks. Tasks where GLM was already 6 of 6 cannot show a gain.
  Headroom tasks (GLM correct out of 6 conditions, published): 04-exam-seating 2, 07-ui-strings 2, 06-seed-allocation 4,
  09-water-schedule 4, 10-grievance-dedup 4, 13-appointment-rebooking 4, 15-catalogue-merge 4,
  16-digitization-audit 4. These 8 tasks have 28 of 48 conditions correct (58%): 20 failures to fix.
- Selecting tasks by published weakness is fine because we measure our own matched baseline on the same items
  (a task that only looked bad by luck will look better in our baseline, not in the comparison).
- All 8 reseed validly (19 or 20 of 20 seeds, 06: 16 of 20), so we can practice on new variants.

## 3. Items
Item = (task, prompt language, file language). 8 tasks x 3 prompt languages x 2 file languages = **48 items**.
Primary test = the **frozen** upstream instance of each item (the real benchmark data).
Practice uses only **seeded variants** (different data, same rules), never the frozen instance.
Secondary transfer check = 4 tasks never practiced (01-upi-settlement, 02-gst-payables, 11-parcel-dispatch,
12-delivery-audit), English prompt x both file languages = 8 items. Purpose: do the tips hurt tasks GLM already does well?

## 4. Arms (same harness, same model, temperature 0, matched on the same items)
| Arm | Prompt gets |
|---|---|
| A baseline | the task only |
| B placebo | task plus generic filler of equal length |
| C tips | task plus the learned tip list |
Arms A and C are also run on the 8 transfer items. A is re-run on 12 random primary items to estimate run-to-run noise.

## 5. Practice (builds the tips)
8 tasks x 2 file languages x 1 seed x G=4 attempts (English prompt, temperature 0.7) = 64 attempts. Score with the
grader, compare best and worst attempt per group (skip groups with no spread), reflect on the grader's per-row and
per-column errors to write at most 2 general tips each, keep at most 8 tips. One pass only.
Practice runs at the same time as arm A, since A does not depend on it.

## 6. Size and time
| Part | Attempts |
|---|---|
| Practice | 64 |
| Primary: A + B + C | 48 x 3 = 144 |
| Noise re-run of A | 12 |
| Transfer: A + C | 8 x 2 = 16 |
| **Total** | **236** |
At about 2 minutes average (published GLM median 79 s, with a long tail) and 4 parallel workers: **about 2 hours**,
if the cloud service tolerates 4 parallel runs. Speed levers: GLM only, 4 workers, one practice pass, A and practice in parallel.

## 7. Pre-specified analysis (fixed before running; no re-picking items after seeing results)
Primary metric: number of **fully correct** items out of 48. Secondary: mean field score; per file language; paired
better/worse/same counts; task-clustered bootstrap interval (8 tasks, so wide); failure types before and after.
Proposed rule for "tips helped" (all must hold):
1. C has at least 6 more fully-correct items than A (12.5 points);
2. C beats B by at least 3 items;
3. items that get worse under C are at most half of items that get better;
4. the A-vs-A re-run change rate is smaller than the A-vs-C change.
If these do not hold we report a null result.

## 8. What the result can and cannot say
It can say: in this pre-specified test, tips learned on seeded variants did or did not raise GLM's fully-correct rate on
the frozen instances of 8 headroom tasks, beyond a no-tips run and a filler run in the same harness.
It cannot say: that tips improve agents in general, that they work for other models (needs the Nemotron replication),
that they transfer to new domains (the 8-item transfer check is only a safety check), or anything about Indian languages
broadly. 8 tasks is a small sample, so intervals will be wide.

## 9. Build list before running
Phase 2 practice loop (grouping, reward from grade_rows, reflector using row_checks, tip library), arm runner with
interleaved ordering and resumable logging, noise re-run selection, analysis script, results export. Not built yet.
