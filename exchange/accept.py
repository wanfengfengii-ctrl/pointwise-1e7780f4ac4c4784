import json
import sqlite3

from exchange.contract import AcceptedPiece, PieceFormatError, decode_piece, encode_envelope
from exchange.disclosure import (
    DisclosureFormatError,
    canonical_leaf,
    parse_credential,
    parse_piece,
    plate_commitment,
    verify_merkle,
)
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


def _init_disclosure(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS disclosure_bindings (
            issue_id TEXT PRIMARY KEY NOT NULL,
            credential TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS disclosure_acceptances (
            audit_id TEXT PRIMARY KEY NOT NULL,
            issue_id TEXT NOT NULL REFERENCES disclosure_bindings (issue_id),
            plate TEXT NOT NULL,
            piece TEXT NOT NULL,
            UNIQUE (issue_id, plate)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS disclosure_ledger (
            audit_id TEXT PRIMARY KEY NOT NULL REFERENCES disclosure_acceptances (audit_id),
            payload TEXT NOT NULL
        )
    ''')


def open_offline(path) -> sqlite3.Connection:
    from review.results import init_reviews

    return open_database(path, _init_acceptances, init_snapshots, init_reviews, _init_disclosure)


def _canonical(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _bind_and_archive(db: sqlite3.Connection, credential, piece, canonical_credential: str) -> str:
    issue_id = credential.issue_id
    existing_binding = db.execute(
        'SELECT credential FROM disclosure_bindings WHERE issue_id = ?', (issue_id,),
    ).fetchone()
    if existing_binding is not None and existing_binding[0] != canonical_credential:
        raise AcceptError('issue number is bound to a different credential')

    index = credential.plates.index(piece.plate)
    leaf = canonical_leaf(issue_id, credential.revision_id, piece.plate, piece.rows)
    commitment = plate_commitment(piece.salt, leaf)
    depth = (len(credential.plates) - 1).bit_length()
    if (commitment != piece.commitment or len(piece.path) != depth
            or not verify_merkle(commitment, index, piece.path, credential.root)):
        raise AcceptError('plate evidence does not bind the disclosed plate to the issued scope')

    canonical_piece = _canonical(piece.as_dict())
    archived = db.execute(
        'SELECT audit_id, piece FROM disclosure_acceptances WHERE issue_id = ? AND plate = ?',
        (issue_id, piece.plate),
    ).fetchone()
    if archived is not None:
        audit_id, stored = archived
        if stored != canonical_piece:
            raise AcceptError('conflicting content for the disclosed plate')
        return audit_id

    if existing_binding is None:
        db.execute('INSERT INTO disclosure_bindings (issue_id, credential) VALUES (?, ?)',
                   (issue_id, canonical_credential))
    audit_id = new_id('audit')
    db.execute(
        'INSERT INTO disclosure_acceptances (audit_id, issue_id, plate, piece) VALUES (?, ?, ?, ?)',
        (audit_id, issue_id, piece.plate, canonical_piece),
    )
    snapshot = _issue_ledger(db, issue_id, credential)
    db.execute('INSERT INTO disclosure_ledger (audit_id, payload) VALUES (?, ?)',
               (audit_id, _store_ledger(snapshot)))
    return audit_id


def _issue_ledger(db: sqlite3.Connection, issue_id: str, credential) -> dict:
    verified = {}
    for plate, stored in db.execute(
        'SELECT plate, piece FROM disclosure_acceptances WHERE issue_id = ?', (issue_id,),
    ).fetchall():
        verified[plate] = parse_piece(stored).rows
    items = []
    for plate in credential.plates:
        if plate not in verified:
            items.append({'plate': plate, 'status': 'undisclosed'})
            continue
        rows = [{'slot': slot, 'value': value, 'source_line': line}
                for slot, value, line in verified[plate]]
        measured = [row['value'] for row in rows if row['value'] is not None]
        items.append({'plate': plate, 'status': 'verified', 'rows': rows,
                      'count': len(measured), 'total': sum(measured)})
    return {'issue_id': issue_id, 'revision_id': credential.revision_id, 'plates': items}


def _store_ledger(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


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


def accept_disclosure(db: sqlite3.Connection, credential, payload) -> str:
    """Verify one disclosed plate against a separately received credential."""
    try:
        parsed_credential = parse_credential(credential)
        piece = parse_piece(payload)
        if piece.issue_id != parsed_credential.issue_id:
            raise AcceptError('plate piece belongs to a different issue')
        if piece.plate not in parsed_credential.plates:
            raise AcceptError('plate piece lies outside the issued scope')
        canonical_credential = _canonical(parsed_credential.as_dict())
        with write_transaction(db):
            return _bind_and_archive(db, parsed_credential, piece, canonical_credential)
    except AcceptError:
        raise
    except (DisclosureFormatError, sqlite3.Error) as exc:
        raise AcceptError(f'offline disclosure acceptance failed: {exc}') from exc
