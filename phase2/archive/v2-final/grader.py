"""Read submitted data in a no-network grader. Never execute workspace files."""

import csv
from decimal import Decimal
import hashlib
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path('/workspace')
MAX_OUTPUT = 512 * 1024


def normalize(value):
    return unicodedata.normalize('NFC', value).strip()


def same_value(numeric, column, actual, expected):
    if actual == expected:
        return True
    if column in numeric and expected and len(actual) <= 40 and re.fullmatch(r'[+-]?\d+(?:\.\d+)?', actual):
        return Decimal(actual) == Decimal(expected)
    return False


def grade_rows(contract, header, rows):
    """Score parsed CSV rows against the contract. Shared by the grader and offline analysis."""
    columns = contract['columns']
    if header != columns:
        return {'score': 0.0, 'full_completion': False, 'reason': 'incorrect_header'}
    if any(len(row) != len(columns) for row in rows):
        return {'score': 0.0, 'full_completion': False, 'reason': 'incorrect_row_width'}
    rows = [[normalize(value) for value in row] for row in rows]
    numeric = set(contract.get('numeric', []))
    key_columns = contract['key_columns']
    graded_columns = columns[key_columns:]
    expected = {tuple(normalize(v) for v in row[:key_columns]): [normalize(v) for v in row[key_columns:]]
                for row in contract['expected']}
    keys = [tuple(row[:key_columns]) for row in rows]
    if set(keys).intersection(tuple(key) for key in contract['forbidden_keys']):
        return {'score': 0.0, 'full_completion': False, 'reason': 'restricted_row_in_output'}
    if len(keys) != len(set(keys)):
        return {'score': 0.0, 'full_completion': False, 'reason': 'duplicate_output_key'}

    actual = {tuple(row[:key_columns]): row[key_columns:] for row in rows}
    field_count = len(graded_columns)
    correct_fields = 0
    row_checks = {}
    for key, values in expected.items():
        checks = ([same_value(numeric, c, a, b) for c, a, b in zip(graded_columns, actual[key], values)]
                  if key in actual else [False] * field_count)
        correct_fields += sum(checks)
        row_checks[':'.join(key)] = dict(zip(graded_columns, checks))
    extra_keys = sorted(actual.keys() - expected.keys())
    score_value = 100 * correct_fields / (field_count * (len(expected) + len(extra_keys)))
    return {'score': round(score_value, 4), 'full_completion': score_value == 100,
            'extra_keys': [':'.join(key) for key in extra_keys], 'row_checks': row_checks}


def score(contract):
    unchanged = all(
        (ROOT / path).is_file()
        and hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
        for path, expected in contract['input_sha256'].items()
    )
    submission = ROOT / 'out/result.csv'
    result = {'score': 0.0, 'full_completion': False, 'input_intact': unchanged}
    if not submission.is_file() or submission.stat().st_size > MAX_OUTPUT:
        return {**result, 'reason': 'output_missing_or_oversized'}
    try:
        content = submission.read_text(encoding='utf-8-sig')
        reader = csv.reader(io.StringIO(content, newline=''), strict=True)
        header = [value.strip() for value in next(reader, [])]
        rows = [row for row in reader if row]
    except (UnicodeError, csv.Error):
        return {**result, 'reason': 'invalid_csv_or_encoding'}
    graded = grade_rows(contract, header, rows)
    return {**result, **graded,
            'score': graded['score'] if unchanged else 0.0,
            'full_completion': unchanged and graded['full_completion']}


if __name__ == '__main__':
    print(json.dumps(score(json.load(sys.stdin)), ensure_ascii=True))
