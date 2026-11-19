import sqlite3

from exchange.contract import AcceptedPiece, IssuedPiece, decode_piece
from intake.parse import valid_name


class UnknownPieceError(LookupError):
    """The requested issue or acceptance number is absent."""


def get_issued_piece(db: sqlite3.Connection, piece_id: str) -> IssuedPiece:
    if not valid_name(piece_id):
        raise UnknownPieceError('invalid issued piece number')
    row = db.execute('SELECT envelope FROM issued_pieces WHERE piece_id = ?', (piece_id,)).fetchone()
    if row is None:
        raise UnknownPieceError(f'unknown issued piece: {piece_id}')
    return decode_piece(row[0])


def get_accepted_piece(db: sqlite3.Connection, acceptance_id: str) -> AcceptedPiece:
    if not valid_name(acceptance_id):
        raise UnknownPieceError('invalid acceptance number')
    row = db.execute('SELECT envelope FROM accepted_pieces WHERE acceptance_id = ?', (acceptance_id,)).fetchone()
    if row is None:
        raise UnknownPieceError(f'unknown acceptance: {acceptance_id}')
    return AcceptedPiece(acceptance_id, decode_piece(row[0]))
