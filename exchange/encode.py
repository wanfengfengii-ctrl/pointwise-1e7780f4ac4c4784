from exchange.contract import IssueReceipt, IssuedPiece, PieceBody, PieceSlot, piece_body_digest
from intake.revisions import PlateRevision
from selection.checks import SelectionError, validate_selection
from selection.freeze import SelectionRecord


class EncodingError(ValueError):
    """The exact selection cannot be made into an exchange piece."""


def encode_piece(revision: PlateRevision, selection: SelectionRecord, piece_id: str, receipt_id: str) -> IssuedPiece:
    try:
        validate_selection(revision, selection.scope, selection.masks)
        source = {row.key: row for row in revision.content.rows}
        slots = []
        for layout in selection.scope.layouts:
            for number in sorted(layout.slots):
                row = source[(layout.plate, number)]
                slots.append(PieceSlot(row.plate, row.slot, row.value, row.source_line))
    except (SelectionError, KeyError) as exc:
        raise EncodingError('selected source inventory and recorded rows do not match') from exc
    plates = selection.scope.plates
    masked = tuple(plate for plate in plates if plate in selection.masks.plates)
    body = PieceBody(revision.revision_id, selection.selection_id, revision.batch, plates, masked, tuple(slots))
    receipt = IssueReceipt(receipt_id, piece_id, revision.revision_id, selection.selection_id, plates,
                           piece_body_digest(body))
    return IssuedPiece(piece_id, body, receipt)
