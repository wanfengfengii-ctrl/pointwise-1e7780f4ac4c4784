from dataclasses import dataclass

from ledger.rows import LedgerRow


@dataclass(frozen=True, slots=True)
class PlateTotal:
    plate: str
    masked: bool
    count: int
    total: int


def sum_by_plate(plates: tuple[str, ...], masked: tuple[str, ...],
                 rows: tuple[LedgerRow, ...]) -> tuple[PlateTotal, ...]:
    hidden = set(masked)
    counts = dict.fromkeys(plates, 0)
    totals = dict.fromkeys(plates, 0)
    for row in rows:
        if row.plate not in hidden and row.value is not None:
            counts[row.plate] += 1
            totals[row.plate] += row.value
    return tuple(PlateTotal(plate, plate in hidden, counts[plate], totals[plate]) for plate in plates)
