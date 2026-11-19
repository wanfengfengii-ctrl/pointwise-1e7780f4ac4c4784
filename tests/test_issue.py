import sqlite3

from exchange.contract import decode_piece, encode_envelope
from exchange.issue import IssueError, issue
from exchange.read import get_issued_piece
from intake.register import RegistrationError, register
from intake.repository import RevisionStore
from selection.checks import SelectionError
from selection.freeze import SelectionStore, stage
from tests.support import WorkflowTest, board, change, deny_sql, source_counts


class IssueTests(WorkflowTest):
    def test_clean_issue(self):
        db = self.source()
        inventory = [{'plate': '甲', 'slots': [2, 1]}]
        rows = [change('甲', 2, 7), change('甲', 1, 0)]
        revision = register(db, 'MAT-ZERO', inventory, rows)
        self.assertEqual(register(db, 'MAT-ZERO', inventory, rows), revision)
        selected = stage(db, revision, ['甲'])
        issued = issue(db, selected)
        piece = decode_piece(encode_envelope(issued).encode('utf-8'))
        self.assertEqual([(s.plate, s.slot, s.value, s.source_line) for s in piece.body.slots],
                         [('甲', 1, 0, 2), ('甲', 2, 7, 1)])
        self.assertEqual(piece.body.masked, ())
        self.assertEqual(piece.receipt.piece_id, piece.piece_id)
        self.assertEqual(piece.receipt.revision_id, revision)
        self.assertEqual(piece.receipt.selection_id, selected)
        self.assertEqual(piece.receipt.plates, ('甲',))
        self.assertEqual(get_issued_piece(db, issued.piece_id), issued)
        self.assertEqual(source_counts(db), (1, 1, 1, 1))

    def test_clean_issue_same_batch_conflict(self):
        db = self.source()
        inventory, rows = board()
        old = register(db, 'MAT-001', inventory, rows)
        frozen = stage(db, old, ['甲'])
        updated = [change('甲', 2, 8), *rows[1:]]
        with self.assertRaisesRegex(RegistrationError, 'explicit correction'):
            register(db, 'MAT-001', inventory, updated)
        self.assertEqual(source_counts(db), (1, 1, 0, 0))
        new = register(db, 'MAT-001', inventory, updated, correction=True)
        self.assertNotEqual(old, new)
        self.assertEqual(register(db, 'MAT-001', inventory, rows), old)
        self.assertEqual(register(db, 'MAT-001', inventory, updated), new)
        store = RevisionStore(db)
        self.assertEqual(store.get(old).content.rows[0].value, 7)
        self.assertEqual(store.get(new).content.rows[0].value, 8)
        old_piece = issue(db, frozen)
        new_piece = issue(db, stage(db, new, ['甲']))
        self.assertEqual((old_piece.body.slots[0].value, new_piece.body.slots[0].value), (7, 8))
        self.assertEqual((old_piece.receipt.revision_id, new_piece.receipt.revision_id), (old, new))
        self.assertEqual(SelectionStore(db).get(frozen).scope.revision_id, old)

    def test_clean_issue_issue_rollback(self):
        db = self.source()
        inventory, rows = board()
        revision = register(db, 'MAT-001', inventory, rows)
        frozen = stage(db, revision, ['甲', '乙'], ['乙'])
        with self.assertRaisesRegex(IssueError, 'unknown frozen selection'):
            issue(db, 'sel-unknown')
        with deny_sql(db, sqlite3.SQLITE_READ, 'revisions') as (_, denied):
            with self.assertRaises(IssueError) as error:
                issue(db, frozen)
            self.assertIsInstance(error.exception.__cause__, sqlite3.DatabaseError)
            self.assertEqual(denied, ['revisions'])
        self.assertEqual(source_counts(db), (1, 1, 0, 0))
        with deny_sql(db, sqlite3.SQLITE_TRANSACTION, 'COMMIT') as (statements, denied):
            with self.assertRaises(IssueError) as error:
                issue(db, frozen)
            self.assertIsInstance(error.exception.__cause__, sqlite3.DatabaseError)
            self.assertEqual(denied, ['COMMIT'])
            for table in ('issued_pieces', 'issue_receipts'):
                self.assertTrue(any(sql.startswith(f'INSERT INTO {table} ') for sql in statements))
        self.assertFalse(db.in_transaction)
        self.assertEqual(source_counts(db), (1, 1, 0, 0))
        successful = issue(db, frozen)
        self.assertEqual(get_issued_piece(db, successful.piece_id), successful)
        self.assertEqual(source_counts(db), (1, 1, 1, 1))

    def test_bad_record(self):
        db = self.source()
        inventory, rows = board()
        with self.assertRaisesRegex(RegistrationError, 'repeats a plate slot'):
            register(db, 'MAT-DUP', inventory, [*rows, change('甲', 2, 9)])
        self.assertFalse(RevisionStore(db).has_batch('MAT-DUP'))
        with self.assertRaisesRegex(SelectionError, 'unknown source revision'):
            stage(db, 'rev-unregistered', ['甲'])
        self.assertEqual(source_counts(db), (0, 0, 0, 0))

    def test_bad_record_invalid_input(self):
        db = self.source()
        inventory, rows = board()
        cases = [
            ('boolean', [change('甲', 2, False), *rows[1:]], 'integer or explicit null'),
            ('float', [change('甲', 2, 7.0), *rows[1:]], 'integer or explicit null'),
            ('implicit null', [*rows[:2], {'plate': '乙', 'slot': 3}], 'explicit value'),
            ('missing slot', rows[:2], 'each declared slot'),
            ('outside inventory', [change('甲', 3, 7), *rows[1:]], 'outside the inventory'),
        ]
        for name, records, message in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(RegistrationError, message):
                    register(db, 'MAT-BAD', inventory, records)
                self.assertFalse(RevisionStore(db).has_batch('MAT-BAD'))
        with self.assertRaisesRegex(RegistrationError, 'registered batch'):
            register(db, 'MAT-ABSENT', inventory, rows, correction=True)
        self.assertEqual(source_counts(db), (0, 0, 0, 0))

    def test_wrong_scope(self):
        db = self.source()
        inventory, rows = board()
        revision = register(db, 'MAT-001', inventory, rows)
        with self.assertRaisesRegex(SelectionError, 'outside the selection'):
            stage(db, revision, ['甲'], ['乙'])
        self.assertEqual(source_counts(db), (1, 0, 0, 0))

    def test_wrong_scope_unknown_source_or_plate(self):
        db = self.source()
        inventory, rows = board()
        revision = register(db, 'MAT-001', inventory, rows)
        with self.assertRaisesRegex(SelectionError, 'unknown source revision'):
            stage(db, 'rev-missing', ['甲'])
        with self.assertRaisesRegex(SelectionError, 'absent from the revision'):
            stage(db, revision, ['甲', '丙'])
        self.assertEqual(source_counts(db), (1, 0, 0, 0))
