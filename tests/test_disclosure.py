import copy
from contextlib import closing
import json
import sqlite3

from disclosure_cases import EXPECTED_ROWS, EXPECTED_TOTALS, PLATES, stage_fixture
from exchange.accept import AcceptError, accept_disclosure, open_offline
from exchange.disclosure import parse_credential
from exchange.issue import IssueError, disclose_plate, issue_disclosure
from intake.register import register
from intake.repository import open_source
from ledger.readback import UnknownResultError, read_disclosure
from selection.freeze import stage
from tests.support import WorkflowTest, deny_sql


def _rows(entry):
    if entry['status'] != 'verified':
        return None
    return [(row['slot'], row['value'], row['source_line']) for row in entry['rows']]


def _item(ledger, plate):
    return next(entry for entry in ledger['plates'] if entry['plate'] == plate)


class DisclosureTests(WorkflowTest):
    def test_issue_disclosure_is_new_per_call(self):
        with closing(open_source(self.source_path)) as source:
            revision, selection = stage_fixture(source)
            first_id, first = issue_disclosure(source, selection)
            second_id, second = issue_disclosure(source, selection)
        self.assertNotEqual(first_id, second_id)
        for credential, number in ((first, first_id), (second, second_id)):
            self.assertEqual(credential['version'], 2)
            self.assertEqual(credential['issue_id'], number)
            self.assertEqual(credential['revision_id'], revision)
            self.assertEqual(tuple(credential['plates']), PLATES)
        self.assertNotEqual(first['proof'], second['proof'])
        parsed = parse_credential(json.dumps(first))
        self.assertEqual(parsed.plates, PLATES)

    def test_disclose_plate_scope_and_shape(self):
        with closing(open_source(self.source_path)) as source:
            _, selection = stage_fixture(source)
            issue_id, credential = issue_disclosure(source, selection)
            yi = disclose_plate(source, issue_id, '乙')
            bing = disclose_plate(source, issue_id, '丙')
        self.assertEqual(yi['version'], 2)
        self.assertEqual(yi['issue_id'], issue_id)
        self.assertEqual(yi['plate'], '乙')
        self.assertEqual(yi['rows'], [
            {'slot': '2', 'value': '13', 'source_line': '4'},
            {'slot': '3', 'value': None, 'source_line': '1'},
        ])
        self.assertEqual(bing['rows'], [])
        # Credential carries no slot material for undisclosed plates.
        self.assertEqual(set(credential), {'version', 'issue_id', 'revision_id', 'plates', 'proof'})
        self.assertEqual(set(credential['proof']), {'algorithm', 'root'})
        with closing(open_source(self.source_path)) as source:
            with self.assertRaisesRegex(IssueError, 'not part of the issue'):
                disclose_plate(source, issue_id, '戊')

    def test_two_issues_first_plate_then_supplement(self):
        with closing(open_source(self.source_path)) as source:
            revision, selection = stage_fixture(source)
            first_id, first_credential = issue_disclosure(source, selection)
            second_id, second_credential = issue_disclosure(source, selection)
            first_yi = disclose_plate(source, first_id, '乙')
            jia = disclose_plate(source, first_id, '甲')
        self.assertNotEqual(first_id, second_id)

        with closing(open_offline(self.offline_path)) as offline:
            first_audit = accept_disclosure(offline, first_credential, jia)
            ledger = read_disclosure(offline, first_audit)
            self.assertEqual(ledger['issue_id'], first_id)
            self.assertEqual(ledger['revision_id'], revision)
            self.assertEqual([entry['plate'] for entry in ledger['plates']], list(PLATES))
            self.assertEqual(_rows(_item(ledger, '甲')), [(2, 7, 2)])
            for plate in ('乙', '丙', '丁'):
                self.assertEqual(_item(ledger, plate), {'plate': plate, 'status': 'undisclosed'})
            self.assertEqual(set(_item(ledger, '乙')), {'plate', 'status'})

            # Replaying the same plate returns the first audit number.
            self.assertEqual(accept_disclosure(offline, first_credential, jia), first_audit)

            second_audit = accept_disclosure(offline, first_credential, first_yi)
            self.assertNotEqual(second_audit, first_audit)
            added = read_disclosure(offline, second_audit)
            self.assertEqual(_rows(_item(added, '乙')), [(2, 13, 4), (3, None, 1)])
            yi_item = _item(added, '乙')
            self.assertEqual((yi_item['count'], yi_item['total']), (1, 13))
            # The earlier audit number keeps its original narrower scope.
            self.assertEqual(read_disclosure(offline, first_audit), ledger)

    def test_rejections_keep_first_ledger(self):
        with closing(open_source(self.source_path)) as source:
            _, selection = stage_fixture(source)
            first_id, first_credential = issue_disclosure(source, selection)
            jia = disclose_plate(source, first_id, '甲')
            genuine_yi = disclose_plate(source, first_id, '乙')
            _, other_credential = issue_disclosure(source, selection)
            other_yi = disclose_plate(source, other_credential['issue_id'], '乙')

        with closing(open_offline(self.offline_path)) as offline:
            baseline = accept_disclosure(offline, first_credential, jia)
            original = read_disclosure(offline, baseline)

            dropped = copy.deepcopy(genuine_yi)
            dropped['rows'] = [row for row in dropped['rows'] if row['slot'] != '3']
            line_changed = copy.deepcopy(genuine_yi)
            line_changed['rows'][0]['source_line'] = '9'
            value_changed = copy.deepcopy(genuine_yi)
            value_changed['rows'][0]['value'] = '31'
            added = copy.deepcopy(genuine_yi)
            added['rows'].append({'slot': '4', 'value': '2', 'source_line': '5'})
            repeated = copy.deepcopy(genuine_yi)
            repeated['rows'] = [repeated['rows'][0], copy.deepcopy(repeated['rows'][0]), repeated['rows'][1]]
            misordered = copy.deepcopy(genuine_yi)
            misordered['rows'] = list(reversed(misordered['rows']))
            renamed = copy.deepcopy(genuine_yi)
            renamed['plate'] = '甲'
            forged_root = copy.deepcopy(first_credential)
            forged_root['proof']['root'] = '0' * 64
            for label, candidate, supplied_credential in (
                ('dropped empty slot', dropped, first_credential),
                ('changed source line', line_changed, first_credential),
                ('changed value', value_changed, first_credential),
                ('added slot', added, first_credential),
                ('repeated slot', repeated, first_credential),
                ('misordered slots', misordered, first_credential),
                ('renamed plate', renamed, first_credential),
                ('other issue plate', other_yi, first_credential),
                ('forged root', genuine_yi, forged_root),
            ):
                with self.subTest(label=label):
                    with self.assertRaises(AcceptError):
                        accept_disclosure(offline, supplied_credential, candidate)
                    self.assertEqual(read_disclosure(offline, baseline), original)

            # Original plate remains issuable after the rejected attempts.
            retry = accept_disclosure(offline, first_credential, genuine_yi)
            self.assertNotEqual(retry, baseline)
            self.assertEqual(_rows(_item(read_disclosure(offline, retry), '乙')), [(2, 13, 4), (3, None, 1)])

    def test_cross_issue_credential_conflict(self):
        with closing(open_source(self.source_path)) as source:
            _, selection = stage_fixture(source)
            first_id, first_credential = issue_disclosure(source, selection)
            _, second_credential = issue_disclosure(source, selection)
            jia_one = disclose_plate(source, first_id, '甲')
            jia_two = disclose_plate(source, second_credential['issue_id'], '甲')
        aliased = dict(jia_one, issue_id=first_id)
        forged = copy.deepcopy(second_credential)
        forged['issue_id'] = first_id
        with closing(open_offline(self.offline_path)) as offline:
            accept_disclosure(offline, first_credential, jia_one)
            with self.assertRaisesRegex(AcceptError, 'different credential'):
                accept_disclosure(offline, forged, jia_one)
            with self.assertRaisesRegex(AcceptError, 'different issue'):
                accept_disclosure(offline, second_credential, aliased)

    def test_commit_failure_leaves_no_partial_result(self):
        with closing(open_source(self.source_path)) as source:
            _, selection = stage_fixture(source)
            issue_id, credential = issue_disclosure(source, selection)
            jia = disclose_plate(source, issue_id, '甲')
        with closing(open_offline(self.offline_path)) as offline:
            with deny_sql(offline, sqlite3.SQLITE_TRANSACTION, 'COMMIT') as (_, denied):
                with self.assertRaises(AcceptError):
                    accept_disclosure(offline, credential, jia)
                self.assertEqual(denied, ['COMMIT'])
            self.assertFalse(offline.in_transaction)
            self.assertEqual(offline.execute('SELECT count(*) FROM disclosure_acceptances').fetchone()[0], 0)
            self.assertEqual(offline.execute('SELECT count(*) FROM disclosure_ledger').fetchone()[0], 0)
            self.assertEqual(offline.execute('SELECT count(*) FROM disclosure_bindings').fetchone()[0], 0)
            audit = accept_disclosure(offline, credential, jia)
            self.assertEqual(_rows(_item(read_disclosure(offline, audit), '甲')), [(2, 7, 2)])

    def test_offline_only_and_reopen(self):
        with closing(open_source(self.source_path)) as source:
            _, selection = stage_fixture(source)
            issue_id, credential = issue_disclosure(source, selection)
            pieces = {plate: disclose_plate(source, issue_id, plate) for plate in PLATES}
        self.source_path.unlink()
        with closing(open_offline(self.offline_path)) as offline:
            first = None
            for plate in PLATES:
                audit = accept_disclosure(offline, credential, pieces[plate])
                if plate == '甲':
                    first = audit
            fixed = read_disclosure(offline, first)
            self.assertEqual(_rows(_item(fixed, '甲')), EXPECTED_ROWS['甲'])
        with closing(open_offline(self.offline_path)) as offline:
            self.assertEqual(read_disclosure(offline, first), fixed)
            self.assertEqual(accept_disclosure(offline, credential, pieces['甲']), first)
            complete = {}
            for entry in read_disclosure(offline, audit)['plates']:
                complete[entry['plate']] = (entry['count'], entry['total'])
            self.assertEqual(complete, EXPECTED_TOTALS)

    def test_fixed_plate_after_correction_and_reopen(self):
        inventory = [
            {'plate': '甲', 'slots': [2]},
            {'plate': '乙', 'slots': [2, 3]},
            {'plate': '丙', 'slots': [1]},
        ]
        rows = [
            {'plate': '甲', 'slot': 2, 'value': 7},
            {'plate': '乙', 'slot': 2, 'value': 13},
            {'plate': '乙', 'slot': 3, 'value': None},
            {'plate': '丙', 'slot': 1, 'value': 5},
        ]
        with closing(open_source(self.source_path)) as source:
            revision = register(source, 'MAT-ODD', inventory, rows)
            selection = stage(source, revision, ['甲', '乙', '丙'])
            issue_id, credential = issue_disclosure(source, selection)
            before = disclose_plate(source, issue_id, '乙')
        corrected = [dict(row) for row in rows]
        corrected[1]['value'] = 99
        with closing(open_source(self.source_path)) as source:
            correction = register(source, 'MAT-ODD', inventory, corrected, correction=True)
            self.assertNotEqual(correction, revision)
            after = disclose_plate(source, issue_id, '乙')
        self.assertEqual(after, before)
        self.assertEqual(before['rows'][0], {'slot': '2', 'value': '13', 'source_line': '2'})
        with closing(open_offline(self.offline_path)) as offline:
            audit = accept_disclosure(offline, credential, before)
            ledger = read_disclosure(offline, audit)
        self.assertEqual([entry['plate'] for entry in ledger['plates']], ['甲', '乙', '丙'])
        self.assertEqual(_rows(_item(ledger, '乙')), [(2, 13, 2), (3, None, 3)])
        self.assertEqual(_item(ledger, '甲'), {'plate': '甲', 'status': 'undisclosed'})

    def test_issue_disclosure_rollback_and_reopen(self):
        with closing(open_source(self.source_path)) as source:
            revision, selection = stage_fixture(source)
            with deny_sql(source, sqlite3.SQLITE_TRANSACTION, 'COMMIT') as (_, denied):
                with self.assertRaises(IssueError):
                    issue_disclosure(source, selection)
                self.assertEqual(denied, ['COMMIT'])
            self.assertFalse(source.in_transaction)
            self.assertEqual(source.execute('SELECT count(*) FROM disclosure_issues').fetchone()[0], 0)
            self.assertEqual(source.execute('SELECT count(*) FROM disclosure_plates').fetchone()[0], 0)
            issue_id, credential = issue_disclosure(source, selection)
            self.assertEqual(source.execute('SELECT count(*) FROM disclosure_issues').fetchone()[0], 1)
            plates = source.execute('SELECT count(*) FROM disclosure_plates WHERE issue_id = ?',
                                    (issue_id,)).fetchone()[0]
            self.assertEqual(plates, len(PLATES))
        with closing(open_source(self.source_path)) as source:
            self.assertEqual(disclose_plate(source, issue_id, '乙')['rows'][0]['value'], '13')
            self.assertEqual(len(credential['plates']), len(PLATES))

    def test_undisclosed_plate_cannot_be_guessed_from_received_material(self):
        with closing(open_source(self.source_path)) as source:
            _, selection = stage_fixture(source)
            issue_id, credential = issue_disclosure(source, selection)
            jia = disclose_plate(source, issue_id, '甲')
            genuine_yi = disclose_plate(source, issue_id, '乙')
        with closing(open_offline(self.offline_path)) as offline:
            accept_disclosure(offline, credential, jia)
        # 甲件的路径暴露了乙的承诺（哈希），却不含乙的开启盐或槽表。
        self.assertIn(genuine_yi['proof']['commitment'], jia['proof']['path'])
        self.assertNotIn(genuine_yi['proof']['salt'], json.dumps(jia))
        self.assertNotIn('rows', jia['proof'])
        self.assertEqual(set(jia['proof']), {'algorithm', 'salt', 'commitment', 'path'})
        # 对乙/2 低取值域尝试：保留已知承诺与路径，换猜测的读值也需匹配盐，
        # 无盐无法构造；这里用任意盐证明猜测件被拒绝且不影响账。
        guessed = copy.deepcopy(genuine_yi)
        guessed['rows'][0]['value'] = '12'
        guessed['proof']['salt'] = '0' * 64
        with closing(open_offline(self.offline_path)) as offline:
            with self.assertRaises(AcceptError):
                accept_disclosure(offline, credential, guessed)
            self.assertEqual(offline.execute('SELECT count(*) FROM disclosure_acceptances').fetchone()[0], 1)

    def test_single_plate_issue(self):
        inventory = [{'plate': '甲', 'slots': [2, 1]}]
        rows = [{'plate': '甲', 'slot': 2, 'value': 7}, {'plate': '甲', 'slot': 1, 'value': 0}]
        with closing(open_source(self.source_path)) as source:
            revision = register(source, 'MAT-ONE', inventory, rows)
            selection = stage(source, revision, ['甲'])
            issue_id, credential = issue_disclosure(source, selection)
            piece = disclose_plate(source, issue_id, '甲')
        self.assertEqual(piece['proof']['path'], [])
        with closing(open_offline(self.offline_path)) as offline:
            audit = accept_disclosure(offline, credential, piece)
            ledger = read_disclosure(offline, audit)
        self.assertEqual([entry['plate'] for entry in ledger['plates']], ['甲'])
        self.assertEqual(_rows(_item(ledger, '甲')), [(1, 0, 2), (2, 7, 1)])
        self.assertEqual((_item(ledger, '甲')['count'], _item(ledger, '甲')['total']), (2, 7))

    def test_unknown_audit(self):
        with closing(open_offline(self.offline_path)) as offline:
            with self.assertRaisesRegex(UnknownResultError, 'unknown disclosure audit'):
                read_disclosure(offline, 'audit-missing')
            with self.assertRaises(UnknownResultError):
                read_disclosure(offline, '')
