from contextlib import closing
import csv
from io import StringIO
import json

from exchange.accept import accept, open_offline
from exchange.contract import encode_envelope
from exchange.read import get_accepted_piece, get_issued_piece
from intake.register import register
from intake.repository import RevisionStore, open_source
from ledger.export import export_ledger
from ledger.readback import UnknownResultError, read
from review.amend import amend
from selection.freeze import SelectionStore
from tests.support import WorkflowTest, board, change, emit_scenario, offline_counts, row_values, source_counts, totals_values


class HistoryTests(WorkflowTest):
    def _create_history(self):
        revision, piece = self.issue_board()
        with closing(open_offline(self.offline_path)) as offline:
            accepted = accept(offline, encode_envelope(piece))
            result = amend(offline, accepted.acceptance_id, [change('乙', 2, 17)], ['乙'])
        return revision, piece, accepted, result

    def test_history(self):
        revision, piece, _, result = self._create_history()
        inventory, changed_rows = board(29)
        with closing(open_source(self.source_path)) as source:
            corrected = register(source, 'MAT-001', inventory, changed_rows, correction=True)
            self.assertNotEqual(corrected, revision)
        offline = self.offline()
        old_rows = read(offline, piece.piece_id)
        reviewed = read(offline, result.result_id)
        expected = [[['甲', 2, 7, 1]], [['甲', 2, 7, 1], ['乙', 2, 17, 2], ['乙', 3, None, 3]]]
        actual = [row_values(old_rows), row_values(reviewed)]
        self.assertEqual(actual, expected)
        self.assertEqual([row.revision_id for row in (*old_rows, *reviewed)], [revision] * 4)
        self.assertEqual(totals_values(read(offline, piece.piece_id, 'totals')),
                         [['甲', False, 1, 7], ['乙', True, 0, 0]])
        self.assertEqual(totals_values(read(offline, result.result_id, 'totals')),
                         [['甲', False, 1, 7], ['乙', False, 1, 17]])
        headers = ['plate', 'slot', 'state', 'value', 'revision_id', 'source_line']
        export_expected = [
            [headers, ['甲', '2', 'measured', '7', revision, '1']],
            [headers, ['甲', '2', 'measured', '7', revision, '1'], ['乙', '2', 'measured', '17', revision, '2'],
             ['乙', '3', 'empty', '', revision, '3']],
        ]
        export_actual = [list(csv.reader(StringIO(export_ledger(offline, number))))
                         for number in (piece.piece_id, result.result_id)]
        self.assertEqual(export_actual, export_expected)
        self.assertEqual(export_ledger(offline, piece.piece_id, 'totals'),
                         'plate,visibility,count,total\n甲,visible,1,7\n乙,masked,0,0\n')
        self.assertEqual(export_ledger(offline, result.result_id, 'totals'),
                         'plate,visibility,count,total\n甲,visible,1,7\n乙,visible,1,17\n')
        emit_scenario('history', {'source_correction': changed_rows, 'original_piece': piece.piece_id,
                                  'review_result': result.result_id}, expected, actual, export_expected, export_actual,
                      ['intake/register.py', 'ledger/snapshots.py', 'ledger/readback.py', 'ledger/export.py'],
                      '手工列出初始遮蔽与复检明细及 CSV，后来仪器的 29 不参与旧号领取。')

    def test_history_reinitialize(self):
        revision, piece, accepted, result = self._create_history()
        inventory, updated = board(23)
        with closing(open_source(self.source_path)) as source:
            correction = register(source, 'MAT-001', inventory, updated, correction=True)
        keys = [(number, view) for number in (piece.piece_id, result.result_id) for view in ('rows', 'totals')]
        with closing(open_offline(self.offline_path)) as offline:
            before = [(read(offline, *key), export_ledger(offline, *key)) for key in keys]
        for _ in range(2):
            with closing(open_source(self.source_path)) as source:
                self.assertEqual(source_counts(source), (2, 1, 1, 1))
                self.assertEqual(RevisionStore(source).get(correction).content.rows[1].value, 23)
                self.assertEqual(RevisionStore(source).get(revision).content.rows[1].value, 13)
                frozen = SelectionStore(source).get(piece.body.selection_id)
                self.assertEqual(frozen.scope.revision_id, revision)
                self.assertEqual(get_issued_piece(source, piece.piece_id), piece)
                self.assertEqual(source.execute('SELECT receipt_id, piece_id FROM issue_receipts').fetchall(),
                                 [(piece.receipt.receipt_id, piece.piece_id)])
            with closing(open_offline(self.offline_path)) as offline:
                self.assertEqual(offline_counts(offline), (1, 2, 1, 1))
                self.assertEqual(get_accepted_piece(offline, accepted.acceptance_id), accepted)
                self.assertEqual(accept(offline, encode_envelope(piece)), accepted)
                self.assertEqual([(read(offline, *key), export_ledger(offline, *key)) for key in keys], before)
                archived = offline.execute('SELECT acceptance_id, paper_order FROM review_results WHERE result_id = ?',
                                           (result.result_id,)).fetchone()
                self.assertEqual(archived[0], accepted.acceptance_id)
                self.assertEqual(json.loads(archived[1]),
                                 {'changes': [{'plate': '乙', 'slot': '2', 'value': '17'}], 'reveal': ['乙']})
                self.assertEqual(offline.execute('SELECT receipt_id, result_id FROM review_receipts').fetchall(),
                                 [(result.receipt.receipt_id, result.result_id)])

    def test_history_unknown_result(self):
        self._create_history()
        offline = self.offline()
        for retrieve in (read, export_ledger):
            for view in ('rows', 'totals'):
                with self.subTest(operation=retrieve.__name__, view=view):
                    with self.assertRaisesRegex(UnknownResultError, 'unknown ledger result'):
                        retrieve(offline, 'review-missing', view)
        self.assertEqual(offline_counts(offline), (1, 2, 1, 1))
