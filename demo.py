from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from disclosure_cases import PLATES, stage_fixture
from exchange.accept import accept, accept_disclosure, open_offline
from exchange.contract import encode_envelope
from exchange.issue import disclose_plate, issue, issue_disclosure
from intake.register import register
from intake.repository import open_source
from ledger.export import export_ledger
from ledger.readback import read, read_disclosure
from review.amend import amend
from selection.freeze import stage


def run_v1(examples: Path, directory: Path) -> None:
    board = json.loads((examples / 'board.json').read_text(encoding='utf-8'))
    order = json.loads((examples / 'order.json').read_text(encoding='utf-8'))
    source_path = directory / 'source.sqlite'
    offline_path = directory / 'offline.sqlite'
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


def print_disclosure(label: str, audit_id: str, ledger: dict) -> None:
    print(f'{label} {audit_id} (发行 {ledger["issue_id"]}, 修订 {ledger["revision_id"]})')
    for entry in ledger['plates']:
        if entry['status'] == 'undisclosed':
            print(f'  {entry["plate"]}: 未披露')
            continue
        details = ', '.join(
            f'{row["slot"]}={row["value"]}' if row['value'] is not None else f'{row["slot"]}=真空'
            for row in entry['rows']
        )
        print(f'  {entry["plate"]}: 核验 count={entry["count"]} total={entry["total"]} [{details}]')


def run_v2(source_path: Path, offline_path: Path) -> None:
    with closing(open_source(source_path)) as source:
        revision_id, selection_id = stage_fixture(source)
        first_id, first_credential = issue_disclosure(source, selection_id)
        second_id, _ = issue_disclosure(source, selection_id)
        jia = disclose_plate(source, first_id, '甲')
        yi = disclose_plate(source, first_id, '乙')
        bing = disclose_plate(source, first_id, '丙')
        ding = disclose_plate(source, first_id, '丁')
        print(f'首班发行 {first_id}，次班发行 {second_id}（固定盘序 {"、".join(PLATES)}）')

    # 首班只领获准盘甲，源库随后断开（此处不再打开 source）。
    with closing(open_offline(offline_path)) as offline:
        first_audit = accept_disclosure(offline, first_credential, jia)
        first_ledger = read_disclosure(offline, first_audit)
    print_disclosure('首班核验号', first_audit, first_ledger)

    # 断源后的补收：沿用首次可信凭据补领乙、丙、丁。
    with closing(open_offline(offline_path)) as offline:
        supplement_audit = accept_disclosure(offline, first_credential, yi)
        accept_disclosure(offline, first_credential, bing)
        all_audit = accept_disclosure(offline, first_credential, ding)
        replay_audit = accept_disclosure(offline, first_credential, jia)
        supplement_ledger = read_disclosure(offline, supplement_audit)
        complete_ledger = read_disclosure(offline, all_audit)
        first_after = read_disclosure(offline, first_audit)
    print_disclosure('补收乙后核验号', supplement_audit, supplement_ledger)
    print_disclosure('补收齐全核验号', all_audit, complete_ledger)
    print(f'重投甲返回首次核验号 {replay_audit}（与首班号一致：{replay_audit == first_audit}）')
    print(f'首班号范围保持不变：{first_after == first_ledger}')
    print(f'夹具手算合计 {json.dumps({"甲": [1, 7], "乙": [1, 13], "丙": [0, 0], "丁": [1, 0]}, ensure_ascii=False)}')
    assert complete_ledger['revision_id'] == revision_id


def main() -> None:
    examples = Path(__file__).resolve().parent / 'examples'
    with TemporaryDirectory(prefix='material-handoff-') as directory:
        root = Path(directory)
        run_v1(examples, root)
        print()
        run_v2(root / 'disclosure-source.sqlite', root / 'disclosure-offline.sqlite')


if __name__ == '__main__':
    main()
