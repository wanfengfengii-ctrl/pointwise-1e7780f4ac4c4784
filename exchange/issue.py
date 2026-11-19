import sqlite3

from exchange.contract import IssuedPiece, encode_envelope
from exchange.encode import EncodingError, encode_piece
from intake.parse import valid_name
from intake.repository import RevisionStore, new_id, write_transaction
from selection.freeze import SelectionStore


class IssueError(ValueError):
    """The requested exchange piece and its receipt were not issued."""


def init_issuance(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS issued_pieces (
            piece_id TEXT PRIMARY KEY NOT NULL,
            selection_id TEXT NOT NULL REFERENCES selections (selection_id),
            envelope TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS issue_receipts (
            receipt_id TEXT PRIMARY KEY NOT NULL,
            piece_id TEXT NOT NULL UNIQUE REFERENCES issued_pieces (piece_id)
        )
    ''')


def issue(db: sqlite3.Connection, selection_id: str) -> IssuedPiece:
    if not valid_name(selection_id):
        raise IssueError('invalid frozen selection number')
    try:
        with write_transaction(db):
            selection = SelectionStore(db).get(selection_id)
            if selection is None:
                raise IssueError('unknown frozen selection')
            revision = RevisionStore(db).get(selection.scope.revision_id)
            if revision is None:
                raise IssueError('frozen selection has no readable revision')
            piece = encode_piece(revision, selection, new_id('piece'), new_id('issue'))
            db.execute('INSERT INTO issued_pieces (piece_id, selection_id, envelope) VALUES (?, ?, ?)',
                       (piece.piece_id, selection_id, encode_envelope(piece)))
            db.execute('INSERT INTO issue_receipts (receipt_id, piece_id) VALUES (?, ?)',
                       (piece.receipt.receipt_id, piece.piece_id))
            return piece
    except (EncodingError, sqlite3.Error) as exc:
        raise IssueError(f'issuance failed: {exc}') from exc
