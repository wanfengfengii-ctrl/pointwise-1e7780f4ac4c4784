from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from exchange.accept import accept, open_offline
from exchange.contract import encode_envelope
from exchange.issue import issue
from intake.register import register
from intake.repository import open_source
from selection.freeze import stage


def board(hidden_value=13):
    inventory = [{'plate': '甲', 'slots': [2]}, {'plate': '乙', 'slots': [2, 3]}]
    rows = [
        {'plate': '甲', 'slot': 2, 'value': 7},
        {'plate': '乙', 'slot': 2, 'value': hidden_value},
        {'plate': '乙', 'slot': 3, 'value': None},
    ]
    return inventory, rows


def change(plate, slot, value):
    return {'plate': plate, 'slot': slot, 'value': value}


def row_values(rows):
    return [[row.plate, row.slot, row.value, row.source_line] for row in rows]


def totals_values(totals):
    return [[item.plate, item.masked, item.count, item.total] for item in totals]


def emit_scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual, code_paths, oracle):
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id, 'input': inputs, 'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': code_paths, 'oracle': oracle,
    }, ensure_ascii=False, sort_keys=True))


def source_counts(db):
    return (
        db.execute('SELECT count(*) FROM revisions').fetchone()[0],
        db.execute('SELECT count(*) FROM selections').fetchone()[0],
        db.execute('SELECT count(*) FROM issued_pieces').fetchone()[0],
        db.execute('SELECT count(*) FROM issue_receipts').fetchone()[0],
    )


def offline_counts(db):
    return (
        db.execute('SELECT count(*) FROM accepted_pieces').fetchone()[0],
        db.execute('SELECT count(*) FROM ledger_snapshots').fetchone()[0],
        db.execute('SELECT count(*) FROM review_results').fetchone()[0],
        db.execute('SELECT count(*) FROM review_receipts').fetchone()[0],
    )


@contextmanager
def deny_sql(db, action, name):
    statements = []
    denied = []

    def authorize(code, subject, _detail, _database, _origin):
        if code == action and subject == name:
            denied.append(subject)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    db.set_trace_callback(statements.append)
    db.set_authorizer(authorize)
    try:
        yield statements, denied
    finally:
        db.set_authorizer(None)
        db.set_trace_callback(None)


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='material-tests-')
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.source_path = root / 'source.sqlite'
        self.offline_path = root / 'offline.sqlite'

    def source(self):
        db = open_source(self.source_path)
        self.addCleanup(db.close)
        return db

    def offline(self):
        db = open_offline(self.offline_path)
        self.addCleanup(db.close)
        return db

    def issue_board(self, inventory=None, rows=None, *, batch='MAT-001'):
        if inventory is None and rows is None:
            inventory, rows = board()
        with closing(open_source(self.source_path)) as source:
            revision = register(source, batch, inventory, rows)
            selection = stage(source, revision, ['乙', '甲'], ['乙'])
            piece = issue(source, selection)
        return revision, piece

    def accept_board(self):
        revision, piece = self.issue_board()
        db = self.offline()
        return db, revision, piece, accept(db, encode_envelope(piece))
