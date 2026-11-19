from dataclasses import replace
import sqlite3

from exchange.contract import PieceFormatError
from exchange.read import UnknownPieceError, get_accepted_piece
from review.orders import OrderError, parse_order
from review.results import ReviewResult, commit_review
from review.reveal import RevealError, resolve_reveals
from review.targets import TargetError, resolve_targets


class AmendError(ValueError):
    """The full paper order failed and produced no review result."""


def amend(db: sqlite3.Connection, acceptance_id: str, changes=(), reveal=()) -> ReviewResult:
    try:
        order = parse_order(changes, reveal)
        accepted = get_accepted_piece(db, acceptance_id)
        body = accepted.piece.body
        values = resolve_targets(body, order)
        slots = tuple(replace(slot, value=values[slot.key]) if slot.key in values else slot for slot in body.slots)
        draft = replace(body, slots=slots)
        draft = replace(draft, masked=resolve_reveals(draft, order.reveal))
        return commit_review(db, accepted, order, draft)
    except (OrderError, TargetError, RevealError, UnknownPieceError, PieceFormatError, sqlite3.Error) as exc:
        raise AmendError(f'review order failed: {exc}') from exc
