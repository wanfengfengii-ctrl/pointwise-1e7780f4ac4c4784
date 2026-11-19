from dataclasses import dataclass
import json
import sqlite3

from exchange.contract import PieceBody
from intake.parse import decimal_text, read_decimal
from ledger.rows import LedgerRow, project_rows
from ledger.totals import PlateTotal, sum_by_plate


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    rows: tuple[LedgerRow, ...]
    totals: tuple[PlateTotal, ...]


def init_snapshots(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS ledger_snapshots (
            result_id TEXT PRIMARY KEY NOT NULL,
            payload TEXT NOT NULL
        )
    ''')


def build_snapshot(body: PieceBody) -> LedgerSnapshot:
    rows = project_rows(body)
    return LedgerSnapshot(rows, sum_by_plate(body.plates, body.masked, rows))


def store_snapshot(db: sqlite3.Connection, result_id: str, snapshot: LedgerSnapshot) -> None:
    rows = []
    for row in snapshot.rows:
        value = None if row.value is None else decimal_text(row.value)
        rows.append([row.plate, decimal_text(row.slot), value, row.revision_id, decimal_text(row.source_line)])
    totals = [[item.plate, item.masked, decimal_text(item.count), decimal_text(item.total)]
              for item in snapshot.totals]
    payload = json.dumps({'rows': rows, 'totals': totals}, ensure_ascii=False, separators=(',', ':'))
    db.execute('INSERT INTO ledger_snapshots (result_id, payload) VALUES (?, ?)', (result_id, payload))


def load_snapshot(db: sqlite3.Connection, result_id: str) -> LedgerSnapshot | None:
    stored = db.execute('SELECT payload FROM ledger_snapshots WHERE result_id = ?', (result_id,)).fetchone()
    if stored is None:
        return None
    document = json.loads(stored[0])
    rows = tuple(
        LedgerRow(plate, read_decimal(slot), None if value is None else read_decimal(value), revision,
                  read_decimal(line))
        for plate, slot, value, revision, line in document['rows']
    )
    totals = tuple(PlateTotal(plate, masked, read_decimal(count), read_decimal(total))
                   for plate, masked, count, total in document['totals'])
    return LedgerSnapshot(rows, totals)
