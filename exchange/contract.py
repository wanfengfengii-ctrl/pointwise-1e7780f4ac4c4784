from dataclasses import dataclass
import hashlib
import json

from intake.parse import decimal_text, read_decimal, valid_name


VERSION = 1
KIND = 'material-plate-piece'


class PieceFormatError(ValueError):
    """The exchange envelope or its issuance binding is invalid."""


@dataclass(frozen=True, slots=True)
class PieceSlot:
    plate: str
    slot: int
    value: int | None
    source_line: int

    @property
    def key(self) -> tuple[str, int]:
        return self.plate, self.slot


@dataclass(frozen=True, slots=True)
class PieceBody:
    revision_id: str
    selection_id: str
    batch: str
    plates: tuple[str, ...]
    masked: tuple[str, ...]
    slots: tuple[PieceSlot, ...]


@dataclass(frozen=True, slots=True)
class IssueReceipt:
    receipt_id: str
    piece_id: str
    revision_id: str
    selection_id: str
    plates: tuple[str, ...]
    body_digest: str


@dataclass(frozen=True, slots=True)
class IssuedPiece:
    piece_id: str
    body: PieceBody
    receipt: IssueReceipt


@dataclass(frozen=True, slots=True)
class AcceptedPiece:
    acceptance_id: str
    piece: IssuedPiece


def _json(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _body_record(body: PieceBody) -> dict:
    return {
        'revision_id': body.revision_id,
        'selection_id': body.selection_id,
        'batch': body.batch,
        'plates': list(body.plates),
        'masked': list(body.masked),
        'slots': [
            {'plate': slot.plate, 'slot': decimal_text(slot.slot),
             'value': None if slot.value is None else decimal_text(slot.value),
             'source_line': decimal_text(slot.source_line)}
            for slot in body.slots
        ],
    }


def canonical_piece_body(body: PieceBody) -> str:
    return _json(_body_record(body))


def piece_body_digest(body: PieceBody) -> str:
    return hashlib.sha256(canonical_piece_body(body).encode('utf-8')).hexdigest()


def encode_envelope(piece: IssuedPiece) -> str:
    receipt = piece.receipt
    return _json({
        'version': VERSION,
        'kind': KIND,
        'piece_id': piece.piece_id,
        'body': _body_record(piece.body),
        'receipt': {
            'receipt_id': receipt.receipt_id,
            'piece_id': receipt.piece_id,
            'revision_id': receipt.revision_id,
            'selection_id': receipt.selection_id,
            'plates': list(receipt.plates),
            'body_digest': receipt.body_digest,
        },
    })


def _unique_fields(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PieceFormatError(f'repeated envelope field: {key}')
        result[key] = value
    return result


def _record(value: object, fields: set[str], context: str) -> dict:
    if not isinstance(value, dict) or value.keys() != fields:
        raise PieceFormatError(f'invalid {context} fields')
    return value


def _name(value: object) -> str:
    if not valid_name(value):
        raise PieceFormatError('invalid name in exchange envelope')
    return value


def _plate_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PieceFormatError('expected a plate list')
    names = tuple(map(_name, value))
    if len(set(names)) != len(names):
        raise PieceFormatError('repeated plate in exchange envelope')
    return names


def _decode_slots(records: object, plates: tuple[str, ...]) -> tuple[PieceSlot, ...]:
    if not isinstance(records, list):
        raise PieceFormatError('slots must be an ordered list')
    plate_order = {plate: index for index, plate in enumerate(plates)}
    preceding = (-1, 0)
    lines = set()
    slots = []
    for record in records:
        row = _record(record, {'plate', 'slot', 'value', 'source_line'}, 'slot')
        plate = _name(row['plate'])
        number = read_decimal(row['slot'])
        line = read_decimal(row['source_line'])
        if plate not in plate_order or number <= 0 or line <= 0 or line in lines:
            raise PieceFormatError('invalid slot identity or repeated instrument line')
        index = (plate_order[plate], number)
        if index <= preceding:
            raise PieceFormatError('slot order must be strict within the declared plate order')
        value = None if row['value'] is None else read_decimal(row['value'])
        slots.append(PieceSlot(plate, number, value, line))
        lines.add(line)
        preceding = index
    return tuple(slots)


def _decode_body(value: object) -> PieceBody:
    record = _record(value, {'revision_id', 'selection_id', 'batch', 'plates', 'masked', 'slots'}, 'body')
    plates = _plate_list(record['plates'])
    masked = _plate_list(record['masked'])
    masked_set = set(masked)
    if not plates or tuple(plate for plate in plates if plate in masked_set) != masked:
        raise PieceFormatError('masked plates must be an ordered subset of the piece scope')
    return PieceBody(_name(record['revision_id']), _name(record['selection_id']), _name(record['batch']),
                     plates, masked, _decode_slots(record['slots'], plates))


def _decode_receipt(value: object, piece_id: str, body: PieceBody) -> IssueReceipt:
    record = _record(value, {'receipt_id', 'piece_id', 'revision_id', 'selection_id', 'plates', 'body_digest'},
                     'receipt')
    receipt = IssueReceipt(_name(record['receipt_id']), _name(record['piece_id']), _name(record['revision_id']),
                           _name(record['selection_id']), _plate_list(record['plates']), _name(record['body_digest']))
    if (receipt.piece_id, receipt.revision_id, receipt.selection_id, receipt.plates, receipt.body_digest) != (
        piece_id, body.revision_id, body.selection_id, body.plates, piece_body_digest(body),
    ):
        raise PieceFormatError('receipt does not bind the supplied piece body and source')
    return receipt


def decode_piece(payload: str | bytes) -> IssuedPiece:
    try:
        if isinstance(payload, bytes):
            payload = payload.decode('utf-8')
        if not isinstance(payload, str):
            raise PieceFormatError('exchange envelope must be text or UTF-8 bytes')
        document = json.loads(payload, object_pairs_hook=_unique_fields)
        record = _record(document, {'version', 'kind', 'piece_id', 'body', 'receipt'}, 'envelope')
        if type(record['version']) is not int or record['version'] != VERSION or record['kind'] != KIND:
            raise PieceFormatError('unsupported exchange format')
        piece_id = _name(record['piece_id'])
        if not piece_id.startswith('piece-') or piece_id == 'piece-':
            raise PieceFormatError('invalid piece number')
        body = _decode_body(record['body'])
        return IssuedPiece(piece_id, body, _decode_receipt(record['receipt'], piece_id, body))
    except PieceFormatError:
        raise
    except (ValueError, RecursionError) as exc:
        raise PieceFormatError(f'invalid exchange envelope: {exc}') from exc
