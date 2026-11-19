import csv
from io import StringIO
import sqlite3

from intake.parse import decimal_text
from ledger.readback import read


def export_ledger(db: sqlite3.Connection, result_id: str, view: str = 'rows') -> str:
    records = read(db, result_id, view)
    output = StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    if view == 'rows':
        writer.writerow(('plate', 'slot', 'state', 'value', 'revision_id', 'source_line'))
        for row in records:
            empty = row.value is None
            value = '' if empty else decimal_text(row.value)
            writer.writerow((row.plate, decimal_text(row.slot), 'empty' if empty else 'measured',
                             value, row.revision_id, decimal_text(row.source_line)))
    else:
        writer.writerow(('plate', 'visibility', 'count', 'total'))
        for item in records:
            writer.writerow((item.plate, 'masked' if item.masked else 'visible',
                             decimal_text(item.count), decimal_text(item.total)))
    return output.getvalue()
