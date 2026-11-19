from dataclasses import dataclass
import sqlite3

from exchange.contract import AcceptedPiece, PieceBody
from intake.repository import new_id, write_transaction
from ledger.snapshots import build_snapshot, store_snapshot
from review.orders import AmendOrder, archive_order


@dataclass(frozen=True, slots=True)
class ReviewReceipt:
    receipt_id: str
    result_id: str
    acceptance_id: str
    piece_id: str


@dataclass(frozen=True, slots=True)
class ReviewResult:
    result_id: str
    acceptance_id: str
    piece_id: str
    receipt: ReviewReceipt


def init_reviews(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS review_results (
            result_id TEXT PRIMARY KEY NOT NULL REFERENCES ledger_snapshots (result_id),
            acceptance_id TEXT NOT NULL REFERENCES accepted_pieces (acceptance_id),
            paper_order TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS review_receipts (
            receipt_id TEXT PRIMARY KEY NOT NULL,
            result_id TEXT NOT NULL UNIQUE REFERENCES review_results (result_id)
        )
    ''')


def commit_review(db: sqlite3.Connection, accepted: AcceptedPiece, order: AmendOrder, draft: PieceBody) -> ReviewResult:
    result_id = new_id('review')
    acceptance_id = accepted.acceptance_id
    piece_id = accepted.piece.piece_id
    receipt = ReviewReceipt(new_id('receipt'), result_id, acceptance_id, piece_id)
    snapshot = build_snapshot(draft)
    with write_transaction(db):
        store_snapshot(db, result_id, snapshot)
        db.execute('INSERT INTO review_results (result_id, acceptance_id, paper_order) VALUES (?, ?, ?)',
                   (result_id, acceptance_id, archive_order(order)))
        db.execute('INSERT INTO review_receipts (receipt_id, result_id) VALUES (?, ?)',
                   (receipt.receipt_id, result_id))
    return ReviewResult(result_id, acceptance_id, piece_id, receipt)
