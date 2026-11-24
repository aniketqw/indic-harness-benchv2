"""One user-authorized recovery attempt for a phase-two infrastructure failure.

The primary record is never changed. The recovery runs under the same validated runtime,
images, prompts, budgets and grader as the campaign, in its own journal, and is appended to
`<campaign>/infrastructure_retries.json`. Only `infrastructure_failed` conditions qualify; agent
outcomes (completed, budget_exhausted, score 0) are never retried. Each source run gets at most
one recovery, and the recovery's own outcome is final.

This module sits outside the phase-two runtime signature, so adding it does not change the
validated protocol. Usage:

    py -B -X utf8 -m phase2.recovery.retry <campaign> <run_id> --authorization "<user request>"
"""

import argparse
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from bench.credentials import load_keys
from bench.durable import Journal, atomic_json
from bench.lease import ControllerLease
from extension50.common import NEM, SHARED

from ..controller import (JOURNAL, RESULTS, ROOT, VALIDATED, checked_images, profiles_and_limits, recover,
                          signature)
from ..runtime import attempt
from ..suite import catalog, read_json

RECORD = 'infrastructure_retries.json'
LABEL = 'recovery-1'


def leases(folder):
    return (ROOT / 'results/controller.lock', NEM / 'results/controller.lock', SHARED / 'results/controller.lock',
            RESULTS / 'controller.lock', folder / 'controller.lock')


def source_row(folder, run_id):
    with closing(Journal(folder / JOURNAL)) as journal:
        rows = {row['id']: row for row in journal.runs()}
    if run_id not in rows:
        raise ValueError('Unknown run ID for this campaign')
    row = rows[run_id]
    if row['status'] != 'infrastructure_failed':
        raise ValueError(f"Only infrastructure failures can be recovered; this run is {row['status']}")
    if any(r['status'] in ('running', 'planned') for r in rows.values()):
        raise ValueError('The campaign still has planned or running conditions. Recover after it finishes.')
    return row


def retry(folder, run_id, authorization):
    folder = Path(folder)
    record_path = folder / RECORD
    records = read_json(record_path) if record_path.exists() else []
    if any(item['source_run_id'] == run_id for item in records):
        raise ValueError('This condition already has a recovery attempt. No further retries are made.')
    with ExitStack() as stack:
        for path in leases(folder):
            stack.enter_context(ControllerLease(path))
        row = source_row(folder, run_id)
        settings = read_json(folder / 'campaign.json')
        images = checked_images()
        runtime_id = signature(images)
        if read_json(VALIDATED).get('signature') != runtime_id:
            raise ValueError('Run phase-two validate before live execution.')
        dataset_hash = hashlib.sha256(f"{runtime_id}:{settings['scope']}".encode()).hexdigest()
        if dataset_hash != settings['dataset_hash'] or dataset_hash != row['dataset_hash']:
            raise ValueError('Runtime differs from the campaign protocol. A recovery would not be comparable.')
        tasks = catalog()
        keys = load_keys()
        profiles, limits = profiles_and_limits()
        retry_id = hashlib.sha256(f"{dataset_hash}:{row['task']}:{row['language']}:{LABEL}".encode()).hexdigest()[:24]
        home = folder / 'recovery' / run_id
        home.mkdir(parents=True, exist_ok=True)
        authorized = datetime.now(timezone.utc).isoformat()
        with closing(Journal(home / JOURNAL)) as journal:
            recover(journal)
            if journal.runs():
                raise ValueError('A recovery journal already exists for this condition. Inspect it instead.')
            with journal.db:
                journal.db.execute('INSERT INTO runs(id,task,language,dataset_hash) VALUES(?,?,?,?)',
                                   (retry_id, row['task'], row['language'], dataset_hash))
            journal.slot_init(list(keys))
            journal.choose_slot(allowed=list(keys))
            planned = journal.get(retry_id)
            status = attempt(journal, planned, tasks[row['task']], keys, profiles, limits, images, home / 'runs')
            final = journal.get(retry_id)
            journal.export(home / 'checkpoints')
        result = json.loads(final['result']) if final['result'] else {}
        records.append({
            'attempt_number': 2, 'source_run_id': run_id, 'retry_run_id': retry_id,
            'task': row['task'], 'language': row['language'], 'status': status,
            'score': result.get('score'), 'full_completion': result.get('full_completion'),
            'source_failure': json.loads(row['result']).get('pause_reason') if row['result'] else None,
            'authorization': authorization, 'authorized_at_utc': authorized,
            'finished_utc': datetime.now(timezone.utc).isoformat(),
            'journal': (home / JOURNAL).relative_to(ROOT).as_posix(),
            'recovery_controller_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'primary_preserved': True, 'same_protocol': True, 'automatic_retries': False,
        })
        atomic_json(record_path, records)
        return records[-1]


def main():
    parser = argparse.ArgumentParser(description='One-time recovery of a phase-two infrastructure failure')
    parser.add_argument('campaign')
    parser.add_argument('run_id')
    parser.add_argument('--authorization', required=True, help="The user's request, recorded verbatim")
    args = parser.parse_args()
    print(json.dumps(retry(RESULTS / args.campaign, args.run_id, args.authorization), indent=2))


if __name__ == '__main__':
    main()
