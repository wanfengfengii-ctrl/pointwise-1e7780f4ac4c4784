from dataclasses import dataclass

from exchange.contract import PieceBody


@dataclass(frozen=True, slots=True)
class LedgerRow:
    plate: str
    slot: int
    value: int | None
    revision_id: str
    source_line: int


def project_rows(body: PieceBody) -> tuple[LedgerRow, ...]:
    """Project the canonical piece slot order into visible ledger rows."""
    masked = set(body.masked)
    return tuple(
        LedgerRow(slot.plate, slot.slot, slot.value, body.revision_id, slot.source_line)
        for slot in body.slots
        if slot.plate not in masked
    )
