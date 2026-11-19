import sqlite3

from intake.parse import valid_name
from ledger.rows import LedgerRow
from ledger.snapshots import load_snapshot
from ledger.totals import PlateTotal


class UnknownResultError(LookupError):
    """No fixed ledger exists for the supplied result number."""


def read(db: sqlite3.Connection, result_id: str, view: str = 'rows') -> tuple[LedgerRow, ...] | tuple[PlateTotal, ...]:
    if view not in ('rows', 'totals'):
        raise ValueError('ledger view must be rows or totals')
    if not valid_name(result_id):
        raise UnknownResultError('invalid ledger result number')
    snapshot = load_snapshot(db, result_id)
    if snapshot is None:
        raise UnknownResultError(f'unknown ledger result: {result_id}')
    return snapshot.rows if view == 'rows' else snapshot.totals
