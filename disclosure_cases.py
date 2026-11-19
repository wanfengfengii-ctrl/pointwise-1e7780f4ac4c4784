import json
from contextlib import closing

from exchange.accept import AcceptError, accept, open_offline
from exchange.contract import encode_envelope
from exchange.issue import issue
from intake.register import register
from intake.repository import open_source
from ledger.readback import read
from review.amend import amend
from selection.freeze import stage


PLATES = ('甲', '乙', '丙', '丁')
EXPECTED_ROWS = {
    '甲': [(2, 7, 2)],
    '乙': [(2, 13, 4), (3, None, 1)],
    '丙': [],
    '丁': [(5, 0, 3)],
}
EXPECTED_TOTALS = {'甲': (1, 7), '乙': (1, 13), '丙': (0, 0), '丁': (1, 0)}


def stage_fixture(db):
    inventory = [
        {'plate': '甲', 'slots': [2]},
        {'plate': '乙', 'slots': [3, 2]},
        {'plate': '丙', 'slots': []},
        {'plate': '丁', 'slots': [5]},
    ]
    rows = [
        {'plate': '乙', 'slot': 3, 'value': None},
        {'plate': '甲', 'slot': 2, 'value': 7},
        {'plate': '丁', 'slot': 5, 'value': 0},
        {'plate': '乙', 'slot': 2, 'value': 13},
    ]
    revision_id = register(db, 'MAT-DISCLOSE', inventory, rows)
    selection_id = stage(db, revision_id, list(reversed(PLATES)), ['乙'])
    return revision_id, selection_id


def check_baseline():
    with closing(open_source(':memory:')) as source:
        revision_id, selection_id = stage_fixture(source)
        piece = issue(source, selection_id)
        payload = encode_envelope(piece)

    document = json.loads(payload)
    slots = document['body']['slots']
    assert tuple(document['body']['plates']) == PLATES
    assert document['body']['masked'] == ['乙']
    assert [(row['slot'], row['value'], row['source_line']) for row in slots if row['plate'] == '乙'] == [
        ('2', '13', '4'), ('3', None, '1'),
    ]
    document['body']['slots'] = [row for row in slots if row['plate'] == '甲']

    with closing(open_offline(':memory:')) as offline:
        try:
            accept(offline, json.dumps(document))
        except AcceptError as exc:
            assert 'receipt does not bind' in str(exc), str(exc)
        else:
            raise AssertionError('V1 accepted a cropped body with the original receipt')

        accepted = accept(offline, payload)
        assert accept(offline, payload).acceptance_id == accepted.acceptance_id
        original = read(offline, piece.piece_id, 'totals')
        assert [(item.plate, item.masked, item.count, item.total) for item in original] == [
            ('甲', False, 1, 7), ('乙', True, 0, 0), ('丙', False, 0, 0), ('丁', False, 1, 0),
        ]
        result = amend(offline, accepted.acceptance_id, reveal=['乙'])
        rows = read(offline, result.result_id)
        totals = read(offline, result.result_id, 'totals')
        actual_rows = {plate: [] for plate in PLATES}
        for row in rows:
            assert row.revision_id == revision_id
            actual_rows[row.plate].append((row.slot, row.value, row.source_line))
        actual_totals = {item.plate: (item.count, item.total) for item in totals}
        assert actual_rows == EXPECTED_ROWS
        assert actual_totals == EXPECTED_TOTALS
        assert read(offline, piece.piece_id, 'totals') == original
    print(json.dumps({'v1_masked_plate_in_payload': '乙', 'v1_cropped_with_original_receipt': 'rejected',
                      'revealed_rows': actual_rows, 'revealed_totals': actual_totals}, ensure_ascii=False))


if __name__ == '__main__':
    check_baseline()
