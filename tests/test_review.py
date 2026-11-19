from contextlib import closing
from dataclasses import replace
import json
import sqlite3

from exchange.accept import AcceptError, accept, open_offline
from exchange.contract import decode_piece, encode_envelope, piece_body_digest
from exchange.read import get_accepted_piece
from intake.register import register
from exchange.issue import issue
from ledger.export import export_ledger
from ledger.readback import read
from review.amend import AmendError, amend
from selection.freeze import stage
from tests.support import WorkflowTest, board, change, deny_sql, emit_scenario, offline_counts, row_values, totals_values


class ReviewTests(WorkflowTest):
    def test_reveal_original(self):
        db, revision, piece, accepted = self.accept_board()
        self.assertEqual(row_values(read(db, piece.piece_id)), [['甲', 2, 7, 1]])
        self.assertEqual(totals_values(read(db, piece.piece_id, 'totals')),
                         [['甲', False, 1, 7], ['乙', True, 0, 0]])
        result = amend(db, accepted.acceptance_id, reveal=['乙'])
        rows = read(db, result.result_id)
        self.assertEqual(row_values(rows), [['甲', 2, 7, 1], ['乙', 2, 13, 2], ['乙', 3, None, 3]])
        self.assertEqual([row.revision_id for row in rows], [revision] * 3)
        self.assertEqual(totals_values(read(db, result.result_id, 'totals')),
                         [['甲', False, 1, 7], ['乙', False, 1, 13]])
        self.assertEqual(row_values(read(db, piece.piece_id)), [['甲', 2, 7, 1]])

    def test_reveal_original_distinct_hidden_values(self):
        inventory, first_rows = board(13)
        _, second_rows = board(23)
        with closing(self.source()) as source:
            first = register(source, 'MAT-001', inventory, first_rows)
            second = register(source, 'MAT-001', inventory, second_rows, correction=True)
            first_piece = issue(source, stage(source, first, ['甲', '乙'], ['乙']))
            second_piece = issue(source, stage(source, second, ['甲', '乙'], ['乙']))
        self.source_path.unlink()
        db = self.offline()
        actual, downstream = [], []
        for piece, revision in [(first_piece, first), (second_piece, second)]:
            binding = accept(db, encode_envelope(piece))
            self.assertEqual(row_values(read(db, piece.piece_id)), [['甲', 2, 7, 1]])
            result = amend(db, binding.acceptance_id, reveal=['乙'])
            result_rows = read(db, result.result_id)
            self.assertEqual([row.revision_id for row in result_rows], [revision] * 3)
            actual.append(row_values(result_rows))
            downstream.append(totals_values(read(db, result.result_id, 'totals')))
        expected = [[['甲', 2, 7, 1], ['乙', 2, 13, 2], ['乙', 3, None, 3]],
                    [['甲', 2, 7, 1], ['乙', 2, 23, 2], ['乙', 3, None, 3]]]
        expected_totals = [[['甲', False, 1, 7], ['乙', False, 1, 13]],
                           [['甲', False, 1, 7], ['乙', False, 1, 23]]]
        self.assertEqual((actual, downstream), (expected, expected_totals))
        emit_scenario('reveal_original.distinct_hidden_values',
                      {'inventory': inventory, 'boards': [first_rows, second_rows], 'masked': ['乙'], 'reveal': ['乙']},
                      expected, actual, expected_totals, downstream,
                      ['exchange/encode.py', 'exchange/accept.py', 'review/reveal.py', 'ledger/totals.py'],
                      '按板录第二行分别恢复 13 与 23，第三行是真空，每盘各有一个实测。')

    def test_reveal_original_accept_identity_conflict(self):
        db, _, piece, accepted = self.accept_board()
        original_rows = read(db, piece.piece_id)
        original_totals = read(db, piece.piece_id, 'totals')
        reformatted = json.dumps(json.loads(encode_envelope(piece)), indent=2)
        self.assertEqual(accept(db, reformatted.encode('utf-8')), accepted)
        altered_body = replace(piece.body, slots=(replace(piece.body.slots[0], value=99), *piece.body.slots[1:]))
        altered_piece = replace(piece, body=altered_body,
                                receipt=replace(piece.receipt, body_digest=piece_body_digest(altered_body)))
        conflicting_envelope = encode_envelope(altered_piece)
        self.assertEqual(decode_piece(conflicting_envelope), altered_piece)
        with self.assertRaisesRegex(AcceptError, 'conflicting content'):
            accept(db, conflicting_envelope)
        malformed = json.loads(encode_envelope(piece))
        malformed['receipt']['body_digest'] = '0' * 64
        with self.assertRaisesRegex(AcceptError, 'does not bind'):
            accept(db, json.dumps(malformed))
        self.assertEqual(get_accepted_piece(db, accepted.acceptance_id), accepted)
        self.assertEqual(accepted.piece.receipt, piece.receipt)
        self.assertEqual(read(db, piece.piece_id), original_rows)
        self.assertEqual(read(db, piece.piece_id, 'totals'), original_totals)
        self.assertEqual(offline_counts(db), (1, 1, 0, 0))

    def test_amend_hidden(self):
        inventory, source_rows = board()
        revision, piece = self.issue_board(inventory, source_rows)
        self.source_path.unlink()
        changes = [change('乙', 2, 17)]
        with closing(open_offline(self.offline_path)) as db:
            accepted = accept(db, encode_envelope(piece))
            result = amend(db, accepted.acceptance_id, changes, ['乙'])
        db = self.offline()
        rows = read(db, result.result_id)
        actual = row_values(rows)
        downstream = {
            'review_totals': totals_values(read(db, result.result_id, 'totals')),
            'old_rows': row_values(read(db, piece.piece_id)),
            'old_totals': totals_values(read(db, piece.piece_id, 'totals')),
        }
        expected = [['甲', 2, 7, 1], ['乙', 2, 17, 2], ['乙', 3, None, 3]]
        expected_downstream = {
            'review_totals': [['甲', False, 1, 7], ['乙', False, 1, 17]],
            'old_rows': [['甲', 2, 7, 1]],
            'old_totals': [['甲', False, 1, 7], ['乙', True, 0, 0]],
        }
        values = {(row.plate, row.slot): row.value for row in rows}
        a_value = values.get(('甲', 2), 'missing')
        b_value = values.get(('乙', 2), 'missing')
        self.assertEqual((actual, downstream), (expected, expected_downstream),
                         f'MASKED_SLOT_MISPOST 甲/2={a_value} 乙/2={b_value} rows={actual!r}')
        self.assertEqual([row.revision_id for row in rows], [revision] * 3)
        self.assertEqual(result.receipt.acceptance_id, accepted.acceptance_id)
        self.assertEqual(result.receipt.result_id, result.result_id)
        self.assertEqual(result.receipt.piece_id, piece.piece_id)
        emit_scenario('amend_hidden', {'inventory': inventory, 'rows': source_rows, 'masked': ['乙'],
                                     'changes': changes, 'reveal': ['乙']},
                      expected, actual, expected_downstream, downstream,
                      ['exchange/encode.py', 'review/targets.py', 'review/amend.py', 'ledger/snapshots.py'],
                      '纸单只改乙盘第二槽。甲为 7，乙为 17，乙第三槽仍是真空，旧件的乙盘继续遮蔽。')

    def test_amend_hidden_reordered_input(self):
        inventory = [{'plate': '乙', 'slots': [3, 2]}, {'plate': '甲', 'slots': [10, 2]}]
        rows = [change('甲', 10, 4), change('乙', 3, None), change('乙', 2, 13), change('甲', 2, 7)]
        orders = [[change('乙', 2, 17), change('甲', 10, -6)],
                  [change('甲', 10, -6), change('乙', 2, 17)]]
        expected_lines = [[3, 2, 4, 1], [2, 3, 1, 4]]
        for index, records in enumerate((rows, list(reversed(rows)))):
            with self.subTest(order=index):
                revision, piece = self.issue_board(inventory, records, batch=f'MAT-ORDER-{index}')
                db = self.offline()
                binding = accept(db, encode_envelope(piece))
                result = amend(db, binding.acceptance_id, orders[index], ['乙'])
                actual = read(db, result.result_id)
                self.assertEqual([(r.plate, r.slot, r.value) for r in actual],
                                 [('乙', 2, 17), ('乙', 3, None), ('甲', 2, 7), ('甲', 10, -6)])
                self.assertEqual([r.source_line for r in actual], expected_lines[index])
                self.assertEqual([r.revision_id for r in actual], [revision] * 4)
                self.assertEqual(totals_values(read(db, result.result_id, 'totals')),
                                 [['乙', False, 1, 17], ['甲', False, 2, 1]])

    def test_amend_hidden_zero_accounting(self):
        inventory = [{'plate': '甲', 'slots': [10, 3, 2, 1]}, {'plate': '乙', 'slots': [2]}]
        rows = [change('甲', 3, None), change('甲', 1, 0), change('甲', 10, -2),
                change('乙', 2, 13), change('甲', 2, 7)]
        _, piece = self.issue_board(inventory, rows)
        db = self.offline()
        binding = accept(db, encode_envelope(piece))
        self.assertEqual(row_values(read(db, piece.piece_id)),
                         [['甲', 1, 0, 2], ['甲', 2, 7, 5], ['甲', 3, None, 1], ['甲', 10, -2, 3]])
        self.assertEqual(totals_values(read(db, piece.piece_id, 'totals')),
                         [['甲', False, 3, 5], ['乙', True, 0, 0]])
        result = amend(db, binding.acceptance_id, [change('乙', 2, 17)], ['乙'])
        self.assertEqual(totals_values(read(db, result.result_id, 'totals')),
                         [['甲', False, 3, 5], ['乙', False, 1, 17]])
        zero_edit = amend(db, binding.acceptance_id, [change('甲', 1, 1)])
        self.assertEqual(totals_values(read(db, zero_edit.result_id, 'totals')),
                         [['甲', False, 3, 6], ['乙', True, 0, 0]])

        large_inventory = [{'plate': '甲', 'slots': [1, 2]}, {'plate': '乙', 'slots': []}]
        large_rows = [change('甲', 1, 9223372036854775807), change('甲', 2, 7)]
        _, large_piece = self.issue_board(large_inventory, large_rows, batch='MAT-LARGE')
        accept(db, encode_envelope(large_piece))
        self.assertEqual(totals_values(read(db, large_piece.piece_id, 'totals')),
                         [['甲', False, 2, 9223372036854775814], ['乙', True, 0, 0]])
        self.assertEqual(export_ledger(db, large_piece.piece_id, 'totals'),
                         'plate,visibility,count,total\n甲,visible,2,9223372036854775814\n乙,masked,0,0\n')

    def test_empty_edit(self):
        db, _, piece, accepted = self.accept_board()
        original = read(db, piece.piece_id, 'totals')
        with self.assertRaisesRegex(AmendError, 'empty slot'):
            amend(db, accepted.acceptance_id, [change('乙', 2, 17), change('乙', 3, 19)], ['乙'])
        self.assertEqual(offline_counts(db), (1, 1, 0, 0))
        self.assertEqual(read(db, piece.piece_id, 'totals'), original)
        untouched = amend(db, accepted.acceptance_id, reveal=['乙'])
        self.assertEqual(row_values(read(db, untouched.result_id)),
                         [['甲', 2, 7, 1], ['乙', 2, 13, 2], ['乙', 3, None, 3]])

    def test_empty_edit_unknown_target(self):
        db, _, piece, accepted = self.accept_board()
        original = read(db, piece.piece_id)
        cases = [([change('甲', 2, 8), change('乙', 99, 17)], ['乙'], 'unknown original slot'),
                 ([change('甲', 2, 8)], ['乙', '丙'], 'unknown reveal plate')]
        for changes, reveal, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(AmendError, message):
                    amend(db, accepted.acceptance_id, changes, reveal)
                self.assertEqual(offline_counts(db), (1, 1, 0, 0))
                self.assertEqual(read(db, piece.piece_id), original)

    def _reject_final_commit(self, db, acceptance_id):
        with deny_sql(db, sqlite3.SQLITE_TRANSACTION, 'COMMIT') as (statements, denied):
            with self.assertRaises(AmendError) as error:
                amend(db, acceptance_id, [change('乙', 2, 17)], ['乙'])
            self.assertIsInstance(error.exception.__cause__, sqlite3.DatabaseError)
            self.assertEqual(denied, ['COMMIT'])
            for table in ('ledger_snapshots', 'review_results', 'review_receipts'):
                self.assertTrue(any(sql.startswith(f'INSERT INTO {table} ') for sql in statements))
        self.assertFalse(db.in_transaction)

    def test_failed_commit(self):
        db, _, piece, accepted = self.accept_board()
        old = read(db, piece.piece_id, 'totals')
        self._reject_final_commit(db, accepted.acceptance_id)
        self.assertEqual(offline_counts(db), (1, 1, 0, 0))
        self.assertEqual(read(db, piece.piece_id, 'totals'), old)
        result = amend(db, accepted.acceptance_id, [change('乙', 2, 17)], ['乙'])
        self.assertEqual(offline_counts(db), (1, 2, 1, 1))
        self.assertEqual(totals_values(read(db, result.result_id, 'totals')),
                         [['甲', False, 1, 7], ['乙', False, 1, 17]])

    def test_failed_commit_reopen_and_retry(self):
        _, piece = self.issue_board()
        with closing(open_offline(self.offline_path)) as db:
            accepted = accept(db, encode_envelope(piece))
            self._reject_final_commit(db, accepted.acceptance_id)
        db = self.offline()
        self.assertEqual(offline_counts(db), (1, 1, 0, 0))
        self.assertEqual(get_accepted_piece(db, accepted.acceptance_id), accepted)
        self.assertEqual(row_values(read(db, piece.piece_id)), [['甲', 2, 7, 1]])
        result = amend(db, accepted.acceptance_id, [change('乙', 2, 17)], ['乙'])
        self.assertEqual(offline_counts(db), (1, 2, 1, 1))
        self.assertEqual(db.execute('SELECT receipt_id, result_id FROM review_receipts').fetchall(),
                         [(result.receipt.receipt_id, result.result_id)])
        self.assertEqual(row_values(read(db, result.result_id)),
                         [['甲', 2, 7, 1], ['乙', 2, 17, 2], ['乙', 3, None, 3]])
