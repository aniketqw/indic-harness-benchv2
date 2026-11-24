
# Indic Harness Bench phase two (suite v2)

This suite contains 16 original synthetic file workflows, two per domain (finance,
schools, agriculture, localization, municipal, logistics, clinic, archives). Each task
crosses English, Hindi (Devanagari) and Roman Hinglish instructions with English and
Hindi workspaces, using GLM-5.3-Flash and Nemotron 3 Super: 12 conditions per task and
192 in a full campaign. The earlier 24-task suite (v1) was too easy to discriminate
between models and is preserved unchanged in `archive/v1-easy/`; its `tonight`
campaign results remain in `results/tonight/` until archived via the dashboard.

Each workspace has two to five CSV files (24-140 rows per main file) and a notice with
4-8 interacting rules: an unsorted, seq-ordered amendment feed, precedence and
tie-break rules, inclusive boundaries, unit conversions, rounding, and capacity or
allocation logic. Values appear in mixed real-world formats (ISO, day-first and
month-name dates; Indian lakh grouping; Rs/₹ amounts; AM/PM times; stray spaces).
Hindi workspaces render the same facts with Hindi headers and labels, Devanagari
digits in some cells, Hindi month names and सुबह/दोपहर/शाम/रात times. The English and
Hindi workspaces are generated from one canonical dataset with identical per-cell
format choices, and every cell is parsed back and checked before freezing.

Tasks are authored by `phase2/authoring/` and frozen into `phase2/tasks/*.json`.
`difficulty.json` records, for every task, the score obtained by a reference solution
that ignores exactly one rule. Every such ablation fails, so a perfect score requires
every rule. Graders key rows by business ID, accept row reordering and equivalent
numeric formats, score individual fields, and penalize missing, extra and duplicate
rows and any change to the inputs.

To regenerate the tasks after editing an authoring module, run
`py -B -X utf8 -m phase2.authoring.build`, then `review`, `build` and `validate`.

## Review on Windows

From the repository root, run:

```powershell
py -B -X utf8 -m phase2 review
```

Open `work/phase2-review/README.md`. Each linked folder shows three prompts, both
workspaces, and the expected CSV. Edit the authoring module for the domain in
`phase2/authoring/`, rebuild the frozen tasks, then regenerate the review copy. The translations are authored
drafts for team review. The review and expected files are never imported into the
agent workspace.

Run `py -B -X utf8 -m phase2 build` to build the phase-two Docker images.
Run `py -B -X utf8 -m phase2 validate` after editing task sources or code.
Validation checks every grader in Docker and exercises OpenClaw and the relay
with a synthetic upstream for both profiles. It needs no Ollama key or credits.

## Run a reviewed batch

GLM-5.3-Flash replaced GPT-OSS-120B on 17 November 2026. On Ollama Cloud, GPT-OSS-120B
failed its first long generation in every v2 development attempt (HTTP 500 or a cut-off
stream), and a direct replay of one failed request reproduced the HTTP 500. GLM-5.3-Flash
uses the same settings as Nemotron 3 Super: high thinking, temperature 0, streaming, and
durable accounting before the relay delivers a response.

Phase-two budgets, identical for both models: 32,768 tokens per response, 65,536 output
and 600,000 input tokens per attempt, 40 requests, 1,200 seconds, and a 131,072-token
agent context window. They were raised from 8,192 / 16,000 / 200,000 / 30 / 600 s because
GLM-5.3-Flash spent a whole 8,192-token response thinking on the first script-writing step
of a v2 task; with 32,768 it finished thinking at 10,349 tokens and made the tool call.
A model response ending for length is recorded as budget exhaustion even if the agent
process exits normally. The runner records
provider 5xx failures without retransmitting the request and continues to the next condition.
It pauses after three consecutive such failures for a model in one session, or
immediately on ambiguous transport, quota, accounting, or cleanup errors.

Use the hidden key prompt from [local key setup](../docs/KEYS_AND_RECOVERY.md).
The runner loads local credentials and requires the validated sources and images.
Start with a small batch to verify provider compatibility and actual spend.

### Local dashboard

Start it in a PowerShell window:

```powershell
py -B -X utf8 -m phase2.dashboard
```

Open the printed local address (normally `http://127.0.0.1:8765`). The dashboard
has a **Tasks** tab that previews the exact prompt and all input files
for any combination of instruction and workspace languages.
The agent runs as a non-root user in a restricted Docker container with a
read-only root filesystem, a temporary workspace, and an internal network.
The agent has no host mounts or Docker socket. It can reach the inference relay
using an attempt token. The separate relay holds the Ollama key, and the
grader runs without network access.

The dashboard
defaults to two conditions per session. It shows the current task, scores by
model and domain, and an estimate of credits consumed. Ollama's dashboard has the
actual bill. Use Pause and wait for the dashboard to confirm that shutdown is
safe. After restart, open the dashboard again and Resume the same campaign.
Use **Restart** to archive the saved campaign and start from the first condition
with the current suite and selected batch size. **Clear run** archives the
campaign and leaves the dashboard empty without launching a run. These options
are available after the runner stops. Archives live in the Git-ignored
`phase2/results/_archive/` directory.

### Command line

```powershell
py -B -X utf8 -m phase2 start v2 --scope full --limit 2
py -B -X utf8 -m phase2 status v2
py -B -X utf8 -m phase2 resume v2 --limit 22
```

Omit `--limit` to run all remaining conditions. A separate campaign using
`--scope pilot` covers the first task in each domain, 96 conditions. Use different
names for development and final data. Each campaign stops on infrastructure or
quota failure. Check the saved record and provider dashboard before resuming.

## Pause before shutting down

In a second PowerShell window at the repository root, run:

```powershell
py -B -X utf8 -m phase2 pause v2 --wait
```

The controller finishes the active condition, retires its containers, and saves
the checkpoint. Wait for **Safe to shut down**. After reboot, start Docker
Desktop and then run:

```powershell
py -B -X utf8 -m phase2 resume v2
```

Resume opens the same SQLite journal and picks the next unstarted condition.
A forced shutdown can interrupt the current condition. On resume it is marked
interrupted and skipped to prevent duplicate spending. Completed conditions and
reserved inference accounting survive. Keep the whole campaign directory
together, including any SQLite WAL files.

The campaign keeps results in the Git-ignored `phase2/results/<campaign>/`.
Read `conditions.csv` for scores and status, `runs/` for saved artifacts and
per-run details, and `checkpoints/` for the SQLite backup and journal exports.
`status` is read-only. Pause and resume always use the same campaign name.
