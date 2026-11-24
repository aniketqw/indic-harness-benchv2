# Failure audits (17-18 Nov 2026)

Read-only scripts used to audit every non-perfect output. Run from the repository root with `PYTHONPATH=.`.

- `literal_audit.py` (v2): re-solves each task under a literal reading of every value form the v2 notice did not document and rescores the output. It needs `SCR` pointing at a folder with `analysis.json` (merged v2 runs). Output: `literal_audit.json`.
- `diff_v21.py <campaign>`: cell-by-cell diff of every non-perfect output against the answer key, using grader semantics. Outputs: `diff_v2.txt` (campaign `final`) and `diff_v21.txt` (campaign `final-v21`).
- `cells.py <diff files>`: counts cell errors that repeat across runs.
- `show.py <task prefix> [patterns]`: prints a task notice, the matching input rows and the answer rows.
