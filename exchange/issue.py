import json
import sqlite3

from exchange.contract import IssuedPiece, encode_envelope
from exchange.disclosure import (
    build_credential,
    build_piece,
    canonical_leaf,
    merkle_path,
    merkle_root,
    new_salt,
    pack_rows,
    plate_commitment,
    unpack_rows,
)
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
    db.execute('''
        CREATE TABLE IF NOT EXISTS disclosure_issues (
            issue_id TEXT PRIMARY KEY NOT NULL,
            selection_id TEXT NOT NULL REFERENCES selections (selection_id),
            revision_id TEXT NOT NULL,
            plates TEXT NOT NULL,
            root TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS disclosure_plates (
            issue_id TEXT NOT NULL REFERENCES disclosure_issues (issue_id),
            plate TEXT NOT NULL,
            rows TEXT NOT NULL,
            salt TEXT NOT NULL,
            commitment TEXT NOT NULL,
            path TEXT NOT NULL,
            PRIMARY KEY (issue_id, plate)
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


def issue_disclosure(db: sqlite3.Connection, selection_id: str):
    """Freeze the whole selection scope into a new issue; return (issue_id, credential)."""
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
            source = {row.key: row for row in revision.content.rows}
            plates = selection.scope.plates
            issue_id = new_id('disclosure')
            commitments = []
            plate_records = []
            for layout in selection.scope.layouts:
                rows = tuple((number, source[(layout.plate, number)].value,
                              source[(layout.plate, number)].source_line)
                             for number in sorted(layout.slots))
                leaf = canonical_leaf(issue_id, revision.revision_id, layout.plate, rows)
                salt = new_salt()
                plate_records.append((layout.plate, rows, salt, plate_commitment(salt, leaf)))
                commitments.append(plate_records[-1][3])
            root = merkle_root(tuple(commitments))
            db.execute(
                'INSERT INTO disclosure_issues (issue_id, selection_id, revision_id, plates, root) '
                'VALUES (?, ?, ?, ?, ?)',
                (issue_id, selection_id, revision.revision_id, json.dumps(list(plates)), root),
            )
            for index, (plate, rows, salt, commitment) in enumerate(plate_records):
                db.execute(
                    'INSERT INTO disclosure_plates (issue_id, plate, rows, salt, commitment, path) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    (issue_id, plate, json.dumps(pack_rows(rows)), salt, commitment,
                     json.dumps(list(merkle_path(tuple(commitments), index)))),
                )
            return issue_id, build_credential(issue_id, revision.revision_id, plates, root)
    except (KeyError, EncodingError, sqlite3.Error) as exc:
        raise IssueError(f'disclosure issuance failed: {exc}') from exc


def disclose_plate(db: sqlite3.Connection, issue_id: str, plate: str) -> dict:
    """Return the fixed plate piece for a plate inside the issue's frozen scope."""
    if not valid_name(issue_id) or not valid_name(plate):
        raise IssueError('invalid issue or plate name')
    row = db.execute(
        'SELECT rows, salt, commitment, path FROM disclosure_plates WHERE issue_id = ? AND plate = ?',
        (issue_id, plate),
    ).fetchone()
    if row is None:
        raise IssueError(f'plate is not part of the issue: {plate}')
    rows, salt, commitment, path = row
    return build_piece(issue_id, plate, unpack_rows(json.loads(rows)), salt, commitment, json.loads(path))
