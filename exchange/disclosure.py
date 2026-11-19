"""Formats and hiding evidence for per-plate disclosure (V2).

Every plate is committed independently under a fresh random opening salt.
The credential publishes only a Merkle root over the ordered plate
commitments, so a receiver can authenticate a disclosed plate without
learning the slots, measured values or source lines of any other plate.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import re
import secrets

from intake.parse import decimal_text, read_decimal, valid_name


VERSION = 2
ALGORITHM = 'sha256-plate-merkle-v2'

_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_SALT = re.compile(r'[0-9a-f]{64}\Z')
_LEAF_PREFIX = b'\x00'
_NODE_PREFIX = b'\x01'


class DisclosureFormatError(ValueError):
    """A disclosure credential or plate piece is malformed or unverified."""


def _json(document: object) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _unique_fields(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DisclosureFormatError(f'repeated disclosure field: {key}')
        result[key] = value
    return result


def _as_mapping(value: object, context: str) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (str, bytes)):
        text = value.decode('utf-8') if isinstance(value, bytes) else value
        try:
            parsed = json.loads(text, object_pairs_hook=_unique_fields)
        except (ValueError, RecursionError) as exc:
            raise DisclosureFormatError(f'invalid {context}: {exc}') from exc
        if not isinstance(parsed, dict):
            raise DisclosureFormatError(f'{context} must be a JSON object')
        return parsed
    raise DisclosureFormatError(f'{context} must be a mapping')


def _record(value: object, fields: set[str], context: str) -> dict:
    if not isinstance(value, dict) or value.keys() != fields:
        raise DisclosureFormatError(f'invalid {context} fields')
    return value


def _name(value: object) -> str:
    if not valid_name(value):
        raise DisclosureFormatError('invalid name in disclosure material')
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise DisclosureFormatError('invalid disclosure digest')
    return value


def _salt(value: object) -> str:
    if not isinstance(value, str) or _SALT.fullmatch(value) is None:
        raise DisclosureFormatError('invalid plate opening material')
    return value


def _plate_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise DisclosureFormatError('a disclosure issue requires an ordered plate list')
    names = tuple(map(_name, value))
    if len(set(names)) != len(names):
        raise DisclosureFormatError('repeated plate in disclosure credential')
    return names


@dataclass(frozen=True, slots=True)
class Credential:
    issue_id: str
    revision_id: str
    plates: tuple[str, ...]
    root: str

    def as_dict(self) -> dict:
        return {
            'version': VERSION,
            'issue_id': self.issue_id,
            'revision_id': self.revision_id,
            'plates': list(self.plates),
            'proof': {'algorithm': ALGORITHM, 'root': self.root},
        }


@dataclass(frozen=True, slots=True)
class PlatePiece:
    issue_id: str
    plate: str
    rows: tuple[tuple[int, int | None, int], ...]
    salt: str
    commitment: str
    path: tuple[str | None, ...]

    def as_dict(self) -> dict:
        return {
            'version': VERSION,
            'issue_id': self.issue_id,
            'plate': self.plate,
            'rows': [{'slot': decimal_text(slot),
                      'value': None if value is None else decimal_text(value),
                      'source_line': decimal_text(line)}
                     for slot, value, line in self.rows],
            'proof': {
                'algorithm': ALGORITHM,
                'salt': self.salt,
                'commitment': self.commitment,
                'path': list(self.path),
            },
        }


def pack_rows(rows) -> list:
    return [[decimal_text(slot), None if value is None else decimal_text(value), decimal_text(line)]
            for slot, value, line in rows]


def unpack_rows(records: object) -> tuple[tuple[int, int | None, int], ...]:
    if not isinstance(records, list):
        raise DisclosureFormatError('stored plate rows must be an ordered list')
    return tuple((read_decimal(slot), None if value is None else read_decimal(value), read_decimal(line))
                 for slot, value, line in records)


def canonical_leaf(issue_id: str, revision_id: str, plate: str, rows) -> str:
    return _json({
        'version': VERSION,
        'issue_id': issue_id,
        'revision_id': revision_id,
        'plate': plate,
        'rows': [{'slot': decimal_text(slot),
                  'value': None if value is None else decimal_text(value),
                  'source_line': decimal_text(line)} for slot, value, line in rows],
    })


def new_salt() -> str:
    return secrets.token_hex(32)


def plate_commitment(salt: str, leaf: str) -> str:
    material = _LEAF_PREFIX + bytes.fromhex(salt) + leaf.encode('utf-8')
    return hashlib.sha256(material).hexdigest()


def _node_hash(left: str, right: str) -> str:
    return hashlib.sha256(_NODE_PREFIX + bytes.fromhex(left) + bytes.fromhex(right)).hexdigest()


def merkle_levels(commitments: tuple[str, ...]) -> list[list[str]]:
    if not commitments:
        raise DisclosureFormatError('a disclosure issue requires at least one plate')
    levels = [list(commitments)]
    while len(levels[-1]) > 1:
        level = levels[-1]
        following = [_node_hash(level[index], level[index + 1])
                     for index in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            following.append(level[-1])
        levels.append(following)
    return levels


def merkle_root(commitments: tuple[str, ...]) -> str:
    return merkle_levels(commitments)[-1][0]


def merkle_path(commitments: tuple[str, ...], index: int) -> tuple[str | None, ...]:
    levels = merkle_levels(commitments)
    if not 0 <= index < len(commitments):
        raise DisclosureFormatError('plate position lies outside the issue')
    path = []
    position = index
    for level in levels[:-1]:
        if position % 2 == 0:
            path.append(level[position + 1] if position + 1 < len(level) else None)
        else:
            path.append(level[position - 1])
        position //= 2
    return tuple(path)


def verify_merkle(leaf: str, index: int, path, root: str) -> bool:
    node = leaf
    position = index
    for sibling in path:
        if sibling is None:
            if position % 2:
                return False
        elif position % 2 == 0:
            node = _node_hash(node, sibling)
        else:
            node = _node_hash(sibling, node)
        position //= 2
    return node == root


def build_credential(issue_id: str, revision_id: str, plates, root: str) -> dict:
    return Credential(issue_id, revision_id, tuple(plates), root).as_dict()


def build_piece(issue_id: str, plate: str, rows, salt: str, commitment: str, path) -> dict:
    return PlatePiece(issue_id, plate, tuple(rows), salt, commitment, tuple(path)).as_dict()


def _decode_rows(records: object) -> tuple[tuple[int, int | None, int], ...]:
    if not isinstance(records, list):
        raise DisclosureFormatError('plate rows must be an ordered list')
    rows = []
    preceding = 0
    for record in records:
        row = _record(record, {'slot', 'value', 'source_line'}, 'plate row')
        slot = read_decimal(row['slot'])
        line = read_decimal(row['source_line'])
        if slot <= 0 or line <= 0 or slot <= preceding:
            raise DisclosureFormatError('plate rows require strict ascending positive numeric slots')
        value = None if row['value'] is None else read_decimal(row['value'])
        rows.append((slot, value, line))
        preceding = slot
    return tuple(rows)


def parse_credential(value: object) -> Credential:
    try:
        record = _record(_as_mapping(value, 'credential'),
                         {'version', 'issue_id', 'revision_id', 'plates', 'proof'}, 'credential')
        if type(record['version']) is not int or record['version'] != VERSION:
            raise DisclosureFormatError('unsupported disclosure credential format')
        proof = _record(record['proof'], {'algorithm', 'root'}, 'credential proof')
        if proof['algorithm'] != ALGORITHM:
            raise DisclosureFormatError('unsupported disclosure evidence')
        return Credential(_name(record['issue_id']), _name(record['revision_id']),
                          _plate_list(record['plates']), _digest(proof['root']))
    except DisclosureFormatError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise DisclosureFormatError(f'invalid disclosure credential: {exc}') from exc


def parse_piece(value: object) -> PlatePiece:
    try:
        record = _record(_as_mapping(value, 'plate piece'),
                         {'version', 'issue_id', 'plate', 'rows', 'proof'}, 'plate piece')
        if type(record['version']) is not int or record['version'] != VERSION:
            raise DisclosureFormatError('unsupported plate piece format')
        proof = _record(record['proof'], {'algorithm', 'salt', 'commitment', 'path'}, 'plate proof')
        if proof['algorithm'] != ALGORITHM:
            raise DisclosureFormatError('unsupported plate evidence')
        raw_path = proof['path']
        if not isinstance(raw_path, list):
            raise DisclosureFormatError('plate evidence path must be an ordered list')
        path = tuple(None if entry is None else _digest(entry) for entry in raw_path)
        return PlatePiece(_name(record['issue_id']), _name(record['plate']), _decode_rows(record['rows']),
                          _salt(proof['salt']), _digest(proof['commitment']), path)
    except DisclosureFormatError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise DisclosureFormatError(f'invalid plate piece: {exc}') from exc
