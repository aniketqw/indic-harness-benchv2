# Phase two suite v2: design notes

## Why v2 exists

Suite v1 (24 tasks, archived in `archive/v1-easy/`) built each workspace from a 4-11 row
toy table with one trap, copied into six batches that differed in two to four cells. In the
first seven `tonight` conditions, GPT-OSS-120B (since replaced) and Nemotron 3 Super scored 100 on five of
the six graded runs. The one 75 came from leaving zero-valued `due` fields blank (an
instruction ambiguity), not from a reasoning error. A solution that ignored the amendment
feed entirely would still have averaged 78%. v2 was designed after seeing those seven runs
and before any v2 model run. Disclose this in the paper.

## Design

- 16 tasks, two per domain, each crossed with 3 instruction languages (English, Hindi,
  Hinglish) × 2 workspace languages (English, Hindi) × 2 models = 192 conditions.
- Every task is generated from a fixed seed into one canonical dataset. Both workspaces
  render that dataset with identical per-cell format choices, so they carry the same facts.
  Every rendered cell is parsed back and compared with the canonical value before freezing.
- Difficulty comes from rule interaction, not size: an unsorted seq-ordered amendment feed,
  precedence and tie-breaking, inclusive boundaries, unit conversion, half-up rounding,
  allocation under capacity, and mixed real-world value formats. Rules are fully specified
  in the notice; there is no hidden or subjective judgment.
- The Hindi workspace adds Hindi headers and labels, Devanagari digits in some cells, Hindi
  month names and सुबह/दोपहर/शाम/रात time expressions. Localization and archive tasks also
  test Unicode handling (NFC, ZWJ/ZWNJ, nukta, chandrabindu) in both workspaces.
- Prompts now state the output formats (dates, times, plain numbers) and that a field is
  blank only where the notice says so, which removes the v1 blank-versus-zero ambiguity.

## Rule ablations

For every task the reference solution was re-run with exactly one rule ignored, and the
result was scored with the real grader. Every ablation scores below 100, so every rule
affects the answer and a full completion requires all of them.

| Task | Domain | Input rows | Output rows | Scored fields | Hindi bytes | Rules ablated | Mean / max score with one rule ignored |
|---|---|---|---|---|---|---|---|
| 01-upi-settlement UPI settlement close | finance | 107 | 36 | 108 | 9,243 | 9 | 86.8 / 99.0741 |
| 02-gst-payables GST payables register | finance | 80 | 64 | 256 | 7,572 | 11 | 92.4 / 98.8281 |
| 03-bus-roster School bus roster | schools | 151 | 118 | 354 | 5,139 | 9 | 95.2 / 99.435 |
| 04-exam-seating Exam room allocation | schools | 59 | 34 | 136 | 4,231 | 8 | 85.3 / 97.0588 |
| 05-grower-payout Paddy procurement payout | agriculture | 191 | 24 | 120 | 11,372 | 9 | 81.4 / 95.0 |
| 06-seed-allocation Seed lot allocation | agriculture | 104 | 72 | 216 | 8,047 | 7 | 71.7 / 87.037 |
| 07-ui-strings Hindi UI string QA | localization | 80 | 60 | 120 | 7,125 | 8 | 96.3 / 99.1667 |
| 08-search-normalization Grocery search normalization | localization | 187 | 138 | 138 | 5,512 | 11 | 95.7 / 99.2754 |
| 09-water-schedule Ward water-supply plan | municipal | 96 | 60 | 240 | 7,441 | 6 | 92.4 / 98.75 |
| 10-grievance-dedup Grievance consolidation | municipal | 152 | 72 | 288 | 13,231 | 9 | 92.8 / 98.6111 |
| 11-parcel-dispatch Parcel dispatch and charges | logistics | 109 | 93 | 279 | 14,985 | 9 | 88.8 / 95.3405 |
| 12-delivery-audit Proof-of-delivery audit | logistics | 155 | 57 | 171 | 9,157 | 7 | 89.0 / 96.4912 |
| 13-appointment-rebooking Appointment rebooking | clinic | 220 | 41 | 123 | 15,097 | 7 | 65.9 / 82.9268 |
| 14-lab-flags Lab result flags | clinic | 178 | 66 | 132 | 18,224 | 7 | 85.2 / 97.7273 |
| 15-catalogue-merge Catalogue de-duplication | archives | 83 | 39 | 117 | 8,292 | 7 | 81.2 / 94.0171 |
| 16-digitization-audit Digitization page audit | archives | 141 | 125 | 375 | 5,172 | 4 | 82.8 / 97.8667 |

Single-rule mistakes often still leave a field score above 90 because most rows are
unaffected. **Use full completion (all fields correct) as the primary outcome**, and report
the field score as secondary.

## v2.1: value glossary (after the `final` campaign audit)

The full v2 campaign (`results/final`, 192 conditions, 17 Nov 2026) was audited condition by
condition before any analysis. For every non-perfect output, the reference solver was re-run
under a literal reading of each value form the notice did not mention, and the output was scored
against those alternative keys. This found task-specification defects that made a faithful reading
disagree with the answer key:

- 06-seed-allocation: varieties appear both as a code (WHEAT) and as a cultivar name
  (Wheat HD-2967), and Hindi requests use both लघु किसान and छोटा किसान, while the notice only
  promised case and spacing variation. 7 of 11 non-perfect outputs match the literal reading
  exactly or almost exactly, and identical scores repeat across both models.
- 14-lab-flags: results mix test codes and names (HB, Hemoglobin), and the notice never said which
  form the output must use. All six GLM outputs score 100 once names are mapped to codes; the
  official score was 0.
- Smaller cases: 12-delivery-audit (डिब्बे and डिब्बा), 13-appointment-rebooking (STD and standard),
  04-exam-seating (AM and Morning).

v2.1 changes nothing in the data, rules, prompts or answers. `authoring/core.py` appends one generic
section to every notice, built from the generator's own value tables: a value glossary listing every
coded value that a workspace writes in more than one form, and the exact codes required for any
output column that holds coded values. Each v2 notice is an exact prefix of its v2.1 notice (checked
at build time). The rule ablations are unchanged. The v2 task files are preserved in
`archive/v2-final/` with SHA-256 sums.

The audit also confirmed that the remaining failures are model errors, not grading artifacts:
missing output files (the agent stopped or used its output budget without writing), wrong header
or extra column, query text written in place of the query ID, lower-case Roman numerals despite an
explicit upper-case rule, and rule mistakes in otherwise valid outputs. A case-insensitive rescoring
changed only that Roman-numeral run.

Runtime change for v2.1: a dropped provider stream (`ambiguous_transport`) is recorded as an
infrastructure failure and the campaign continues, using the same three-in-a-row stop rule as other
provider errors. Each infrastructure failure gets at most one recovery attempt
(`phase2/recovery/retry.py`); both records are kept.

The v2 campaign is reported as a preliminary run whose audit motivated v2.1. Primary results come
from `results/final-v21`. Budgets, models, grader and language rotation are identical in both.

## Limitations to disclose

- The data are synthetic. Hindi and Hinglish text was written by an AI model with
  self-review only; there was no independent human review.
- Models and budgets differ from the earlier protocol. GPT-OSS-120B was replaced by
  GLM-5.3-Flash after repeated provider HTTP 500 errors, and budgets were raised for both
  models (32,768 tokens per response, 65,536 output and 600,000 input tokens per attempt,
  40 requests, 1,200 s) so the harder tasks are not cut short by thinking length. Hindi
  workspaces are 1.1-2.3x larger in bytes and tokenize longer, so budget exhaustion may
  still be more frequent in Hindi conditions. Report budget exhaustion separately from
  errors.
- One run per condition and 16 tasks: an exploratory comparison, not a significance test.
- Difficulty was set by design and checked with rule ablations, not by model pilot scores.
