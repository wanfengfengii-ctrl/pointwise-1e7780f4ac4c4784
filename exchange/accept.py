import sqlite3

from exchange.contract import AcceptedPiece, PieceFormatError, decode_piece, encode_envelope
from exchange.read import get_accepted_piece
from intake.repository import new_id, open_database, write_transaction
from ledger.snapshots import build_snapshot, init_snapshots, store_snapshot


class AcceptError(ValueError):
    """The piece was not accepted into the offline archive."""


def _init_acceptances(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS accepted_pieces (
            acceptance_id TEXT PRIMARY KEY NOT NULL,
            piece_id TEXT NOT NULL UNIQUE,
            envelope TEXT NOT NULL
        )
    ''')


def open_offline(path) -> sqlite3.Connection:
    from review.results import init_reviews

    return open_database(path, _init_acceptances, init_snapshots, init_reviews)


def accept(db: sqlite3.Connection, payload: str | bytes) -> AcceptedPiece:
    try:
        piece = decode_piece(payload)
        canonical = encode_envelope(piece)
        with write_transaction(db):
            existing = db.execute(
                'SELECT acceptance_id FROM accepted_pieces WHERE piece_id = ?', (piece.piece_id,),
            ).fetchone()
            if existing is not None:
                accepted = get_accepted_piece(db, existing[0])
                if accepted.piece != piece:
                    raise AcceptError('conflicting content for the issued piece number')
                return accepted
            acceptance_id = new_id('accepted')
            db.execute('INSERT INTO accepted_pieces (acceptance_id, piece_id, envelope) VALUES (?, ?, ?)',
                       (acceptance_id, piece.piece_id, canonical))
            store_snapshot(db, piece.piece_id, build_snapshot(piece.body))
            return AcceptedPiece(acceptance_id, piece)
    except (PieceFormatError, sqlite3.Error) as exc:
        raise AcceptError(f'offline acceptance failed: {exc}') from exc
