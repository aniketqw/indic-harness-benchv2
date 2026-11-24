
# Indic Harness Bench phase two

This separate suite contains 24 original synthetic file workflows, three per domain.
Each task crosses English, Hindi (Devanagari), and Roman Hinglish instructions with
English and Hindi working files, using GPT-OSS-120B and Nemotron 3 Super. The full run
plans 288 conditions in one serial campaign. The mid-semester tasks, runtime
source, and historical results remain in their original locations.

Each workspace contains a CSV ledger, a separate authoritative CSV amendment feed,
and a text policy or evidence note. There are 24–66 base rows, six amendments, and
12–36 expected deliverable rows per workflow. Six independent batches reuse
task-specific synthetic case patterns with paired source changes, so the agent
must join amendments by the batch and source row before making decisions. IDs,
codes, and literal titles or strings can remain
the same across workspaces, including Indic-script literals where preserving or
editing them is part of the job. The output is a UTF-8 CSV with a fixed schema.
Graders check individual fields and reject changes to the input files. They key
results by batch and business ID, accept row reordering and equivalent numeric
formats, and flag omitted or extra rows and duplicate IDs. The tasks exercise
structured file work. Long documents, OCR, and open-ended writing are outside
this version's scope. The suite
does not include mixed-workspace conditions or repeats.

## Review on Windows

From the repository root, run:

```powershell
py -B -X utf8 -m phase2 review
```

Open `work/phase2-review/README.md`. Each linked folder shows three prompts, both
workspaces, and the expected CSV. Edit the corresponding domain JSON in
`phase2/tasks/` or the source/answer changes in `phase2/variants.json`, then
regenerate the review copy. The translations are authored
drafts for team review. The review and expected files are never imported into the
agent workspace.

Run `py -B -X utf8 -m phase2 build` to build the phase-two Docker images.
Run `py -B -X utf8 -m phase2 validate` after editing task sources or code.
Validation checks every grader in Docker and exercises OpenClaw and the relay
with a synthetic upstream for both profiles. It needs no Ollama key or credits.

## Run a reviewed batch

Use the hidden key prompt from [local key setup](../docs/KEYS_AND_RECOVERY.md).
The runner loads local credentials and requires the validated sources and images.
Start with a small batch to verify provider compatibility and actual spend.

### Local dashboard

Start it in a PowerShell window:

```powershell
py -B -X utf8 -m phase2.dashboard
```

Open the printed local address (normally `http://127.0.0.1:8765`). The dashboard
has a **Tasks** tab that previews the exact prompt and all three input files
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

### Command line

```powershell
py -B -X utf8 -m phase2 start tonight --scope full --limit 2
py -B -X utf8 -m phase2 status tonight
py -B -X utf8 -m phase2 resume tonight --limit 22
```

Omit `--limit` to run all remaining conditions. A separate campaign using
`--scope pilot` covers the first task in each domain, 96 conditions. Use different
names for development and final data. Each campaign stops on infrastructure or
quota failure. Check the saved record and provider dashboard before resuming.

## Pause before shutting down

In a second PowerShell window at the repository root, run:

```powershell
py -B -X utf8 -m phase2 pause tonight --wait
```

The controller finishes the active condition, retires its containers, and saves
the checkpoint. Wait for **Safe to shut down**. After reboot, start Docker
Desktop and then run:

```powershell
py -B -X utf8 -m phase2 resume tonight
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
