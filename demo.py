from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from exchange.accept import accept, open_offline
from exchange.contract import encode_envelope
from exchange.issue import issue
from intake.register import register
from intake.repository import open_source
from ledger.export import export_ledger
from review.amend import amend
from selection.freeze import stage


def main() -> None:
    examples = Path(__file__).resolve().parent / 'examples'
    board = json.loads((examples / 'board.json').read_text(encoding='utf-8'))
    order = json.loads((examples / 'order.json').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='material-handoff-') as directory:
        source_path = Path(directory) / 'source.sqlite'
        offline_path = Path(directory) / 'offline.sqlite'
        with closing(open_source(source_path)) as source:
            revision_id = register(source, board['batch'], board['inventory'], board['rows'])
            selection_id = stage(source, revision_id, board['selection'], board['masked'])
            piece = issue(source, selection_id)
            payload = encode_envelope(piece)

        with closing(open_offline(offline_path)) as offline:
            accepted = accept(offline, payload)
            result = amend(offline, accepted.acceptance_id, order['changes'], order['reveal'])

        corrected_rows = [dict(row) for row in board['rows']]
        corrected_rows[1]['value'] = 23
        with closing(open_source(source_path)) as source:
            correction = register(source, board['batch'], board['inventory'], corrected_rows, correction=True)

        print(f'发行件 {piece.piece_id}，发行回执 {piece.receipt.receipt_id}，复检回执 {result.receipt.receipt_id}')
        print(f'仪器更正修订 {correction}')
        with closing(open_offline(offline_path)) as offline:
            for label, result_id in [('初始交班', piece.piece_id), ('夜班复检', result.result_id)]:
                print(f'{label} {result_id}')
                print(export_ledger(offline, result_id, 'rows'), end='')
                print(export_ledger(offline, result_id, 'totals'), end='')


if __name__ == '__main__':
    main()
