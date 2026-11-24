# RL-harness pilot: plain-language notes (living document)

Last updated: 2026-11-25. Pilot run: `rlharness/runs/oc_pilot1/` (GPT-OSS-20B via OpenClaw in Docker, your Ollama Cloud).

---------------------------------------------------------------------------------------------------
## 0. The one-paragraph version

The benchmark gives an AI agent a job (read some files, write some output files). A program then
checks the output and gives a score from 0 to 1. We want to see if we can make the agent score higher
by letting it practice: it tries a task several times, we look at which attempts scored better, write
down what they did differently as a short "lesson", and show those lessons to the agent on later tasks.
The model itself never changes (it is a cloud model); only the guidance we give it changes.

---------------------------------------------------------------------------------------------------
## 1. What the benchmark tasks actually are

50 everyday office/engineering jobs, each given in English, Hindi and Hinglish. Same files, same
required outputs, same grader; only the instruction language changes.

Every task: read files in `in/`, write files in `out/`, grader checks `out/`.

Task categories (count): Office communication 7, Software engineering 7, Data/finance 7, Workspace/tool use 6,
Long-running autonomy 6, Knowledge and evidence 6, SRE/DevOps 6, Professional workflows 5.

### Pilot tasks and their REAL grader checks (weights from actual runs)

Train tasks (the agent practices on these):
- 027 contract-summary-risk: 14 equal checks, e.g. risk CSV exists, header exact, exactly six risk rows,
  severity values valid, risk "auto-renewal" found, risk "liability" found, summary has a policy-risks section,
  summary avoids forbidden advice.
- 036 citation-consistency-audit: citation_errors.csv parseable (0.40), corrected_bib.json parseable (0.40),
  formats valid (0.10), audit_notes.md explains unknowns (0.10), citation_graph.json parseable (0.10)
- 063 alert-dedup-noise: deduped_incidents.json exists/valid (0.78), noise_report.md exists (0.16),
  input files not modified (0.06)
- 071 ecommerce-support-routing: 15 checks, e.g. three output files exist (0.05 each), routing actions match
  ground truth (0.13), policy clauses cited (0.10), priority reflects escalation (0.10), reply templates avoid
  forbidden promises (0.05), CSV header exact (0.03)

Held-out test tasks (never practiced on; we measure improvement here):
- 033 offline-knowledge-qa: answers.json is a complete JSON array (0.15), answer facts match docs (0.35),
  source_file and quote support answers (0.30), unanswerable question marked `insufficient_evidence` (0.20)
- 035 conflicting-source-resolution: schema (0.12), facts follow priority rules (0.32), evidence cites winning
  sources (0.18), quotes grounded in the source (0.08+0.04), uncertainties.md lists unconfirmed items (0.15),
  conflict_matrix.csv (0.15), plus smaller checks
- 034 evidence-matrix-claims: one CSV with exact header, every claim covered, classification is
  support/contradict/unclear, source_file path correct, evidence phrase present
- 062 k8s-config-audit: k8s_audit.csv has the required findings (0.86), input files not modified (0.14)

### What "fully right" means
Score 1.0 = EVERY weighted check passes. Partly right = some weights pass. Example: in task 062 an attempt
that wrote a good CSV scored 0.86-0.87 (it missed some small thing); an attempt that wrote no CSV scored 0.14
(it only got the "inputs not modified" credit for doing nothing).

---------------------------------------------------------------------------------------------------
## 2. Questions asked and answers (kept so we remember the reasoning)

**Q: Is the "-1 if you edit an input file" rule relevant? Nobody would do that.**
A: You are right. Evidence: 0 integrity violations in the 300 existing benchmark conditions, and 0 in the
first 21 pilot attempts. Also the grader ALREADY contains this as an ordinary check in some tasks
(063: 0.06, 062: 0.14), which even gives free credit to an agent that does nothing. So the -1 rule adds nothing.
DECISION (pending your OK): drop it from the reward; keep only as a logged warning flag.

**Q: What are the "plus rules"? Is there any real use of them?**
A: The only extra was a speed bonus (max +0.05, only for a perfect score). It has no real use: the learning
step ignores differences smaller than 0.1, so the bonus can never change what we learn. DECISION (pending):
remove it. Bespoke Labs also found simple rewards beat fancy ones.

**Q: So what IS the reward then?**
A (proposed, simplest honest version): reward = the grader's score (0 to 1, the sum of the weights of the
checks that passed). Nothing else. Infrastructure failures (crash/timeout) get no reward and are skipped.
The useful part is NOT a fancy formula; it is that the score is split into named checks, so we can see
exactly WHICH checks fail (e.g. in task 035 "uncertainties.md lists unconfirmed items" failed 2 out of 2).
The reflector uses those failing checks to write lessons.

**Q: What are the checks over here? Be clear.**
A: See section 1: each task has 3 to 15 checks written by the benchmark authors, each with a weight.
They check mostly (a) file exists, (b) exact format (header, JSON keys, allowed values), (c) required facts
or sections are present, (d) forbidden things are absent, (e) inputs untouched.

---------------------------------------------------------------------------------------------------
## 3. Our harness (what runs)

```
trainer script (loop.py)
   -> Docker container running OpenClaw 2026.9.7 (read / write / edit tools only)
   -> your local Ollama -> Ollama Cloud model (gpt-oss:20b-cloud)
   <- output files copied back -> original grader scores them -> reward
   -> compare attempts of the same task -> reflector writes lessons -> lesson library
   -> lessons added to later prompts
```
Files: `core.py` (task loader, grading), `oc_runner.py` (one OpenClaw attempt), `reward.py`, `loop.py`.
Differences from the original study: no Windows key store / relay, runs on the Mac, grading on the host, and
(IMPORTANT, see 4) restricted tools. A fresh baseline is measured here; it does not equal the published numbers.

Learning loop per epoch: 4 attempts per (task, language) at temperature 0.7 -> reward -> best vs worst attempt
(only if the gap is at least 0.1; "no spread, no learning") -> reflector writes at most 2 general lessons ->
library keeps at most 8. Test at temperature 0 on held-out tasks, 2 repeats, three conditions:
no lessons (baseline), 3 generic sentences (placebo), learned lessons.

---------------------------------------------------------------------------------------------------
## 4. IMPORTANT finding: our tool restriction is probably depressing the baseline

I gave OpenClaw only read/write/edit tools (no shell) because the container can reach the host. But then the
agent CANNOT LIST A FOLDER. Several tasks say "read in/sources/*.txt" or "in/docs/*.md" without naming files.
Evidence from the run so far:
- Task 034: 6 of 6 attempts scored exactly 0.0. The `read` calls failed (4 of 5, 13 of 13, 1 of 1) and the
  model sometimes invented non-existent tools ("...?", "operations?") and wrote no output.
- Task 033: 5 of 6 scored 0.0 for the same reason; the one success (0.81) guessed file names.
- The original study allowed `exec` (shell: ls, cat), so this is a difference WE introduced, not a model flaw.
So the current baseline is partly measuring the harness, not the model. Options (needs your decision):
 A. Allow `exec` inside the container (matches the original). Cost: container has host/internet access via
    Docker's default network; needs a locked-down network (e.g. an internal network plus a small proxy to Ollama).
 B. Keep read/write/edit but pre-list the directory contents in the prompt (changes the prompt; disclose).
 C. Keep as is (weakest; results mostly about tool discovery).
Recommendation: A with an internal network (closest to the original), B as a quick fallback.
The running pilot should be treated as a smoke test; its baseline is not a valid baseline.

---------------------------------------------------------------------------------------------------
## 5. Status log
- OpenClaw image built (ihb-agent:2026.9.7); smoke attempt (004 en) scored 1.0 in 24 s.
- First launch failed silently (python -I removed the import path); relaunched as oc_pilot1.
- Another session (indic-harness-bench-r-2) ran a separate 3-tool-loop pilot (`runs/gptoss_pilot1`), partial,
  lessons were generic ("validate headers/keys"). Files untouched.
- Early oc_pilot1 baseline: low scores, dominated by the tool-listing problem in section 4.

## 6. Caveats and open risks
1. Tiny sample (4 held-out tasks x 3 languages x 2 repeats): wide uncertainty, no significance claims.
2. Section 4 harness restriction biases the baseline downward until fixed.
3. Failures seen on held-out tasks may not occur on the training tasks, so the loop might not learn them.
4. Lessons may be generic and useless; the placebo control exists to expose that.
5. A null result (no improvement) is possible and reportable.
6. Different harness from the published study; scores not directly comparable.
7. Lessons come from train-task check labels; keep train and test tasks disjoint (they are).
8. Temperature 0 on a cloud model is not fully deterministic; hence 2 repeats.
9. Quota is shared with the other session; do not run both at once.
10. Reflector uses the same model as the agent; read lessons by hand.

## 7. Next steps (after your decision on section 4)
- Fix the tool problem, rerun baseline in a fresh run folder (do not mix with oc_pilot1).
- Simplify the reward to the grader score (section 2), then run train and eval.
- Read the learned lessons and some transcripts by hand before trusting any number.
- If lessons help on held-out tasks: replicate on Nemotron; add SWE-smith-style repair tasks.

---------------------------------------------------------------------------------------------------
## 8. Earlier pilot result (other session, `runs/gptoss_pilot1`, 3-tool loop, GPT-OSS, 4 held-out tasks, 2 reps)

Mean score /100, baseline (no lessons) -> with learned lessons:
| | overall | English | Hindi | Hinglish |
|---|---|---|---|---|
| baseline | 41.6 | 55.0 | 41.8 | 28.0 |
| lessons | 47.4 | 48.7 | 45.9 | 47.6 |
| change | +5.8 | -6.3 | +4.1 | +19.5 |

Per task (baseline -> lessons): 033 12.8 -> 0.0; 035 56.2 -> 66.0; 034 22.8 -> 38.2; 062 74.7 -> 85.4.
Input tokens rose ~15% (longer prompt). CORRECTION to an earlier belief: English did NOT improve; English got
worse, Hinglish improved most. No placebo control was run in that pilot, 2 repeats only, 4 tasks only, so none
of this is attributable to lesson content yet. Task 033 collapsing to 0.0 is unexplained and needs inspection.

## 9. Agreed plan (user, 2026-11-25): baselines first, then scale, then explain
1. Baselines: no-lessons (noise floor from many repeats), placebo, per language, per task.
2. Scale: many more tasks (cross-validated folds over the 50), same measurement.
3. Explain WHY any change happens (see 10).
## 10. "Why" analyses to run
- Per-check deltas: which exact grader checks flip from fail to pass.
- Failure taxonomy before/after: missing file, wrong format, invented tool, wrong content, timeout.
- Leave-one-out lesson ablation; placebo of equal length; lessons in English vs translated to Hindi/Hinglish.
- Turns, tokens and elapsed time before/after (longer prompt effect).
- Noise floor: repeat the baseline until run-to-run spread is known; call a change real only if it exceeds it.

---------------------------------------------------------------------------------------------------
## 11. Upstream update merged (2026-11-25): Phase 2 suite (the "16 tasks")
Our GitHub repo is a FORK (aniketqw/indic-harness-benchv2) of yahall0/indic-harness-benchv2; the update was on the
upstream, not the fork. Added remote `upstream`, fast-forwarded local master to 9c4753e (2 commits, 129 files added,
README modified; nothing existing changed). NOT pushed to the fork (awaiting user's OK).

Phase 2 (suite v2.1): 16 synthetic file-workflow tasks, 2 per domain x 8 Indian domains (finance, schools,
agriculture, localization, municipal, logistics, clinic, archives). 3 instruction languages (en/hi/hinglish) x
2 WORKSPACE languages (English / Hindi files) x 2 models (GLM-5.3-Flash, Nemotron 3 Super) = 192 conditions.
GPT-OSS was replaced (GPT-OSS-120B failed on Ollama Cloud). Tasks: CSV inputs + a notice with 4-8 interacting rules
(amendment feed, precedence, boundaries, unit conversion, rounding, capacity). Grader: exact match by business ID,
field-level scoring, penalizes missing/extra/duplicate rows and any input change. Every rule is necessary.
Published findings (one run per condition): 146/192 fully correct (76%); English vs Hindi workspace 84% vs 68%;
Hindi/Hinglish instructions cost ~8 points; models similar overall (77% vs 75%), fail differently (GLM: wrong
details; Nemotron: budget exhaustion with no file). Source: phase2/reports/v21-findings.html.
Relevance to RL: tasks come from authoring generators (canonical dataset -> en/hi workspaces from a fixed seed), i.e.
the Reasoning-Gym/SWE-smith pattern; fully-correct is a clean verifiable reward. To verify: can generators emit new seeds?
Phase 1 pilot (8 tasks, GPT-OSS) baseline continues running separately; it is unaffected by the merge.
