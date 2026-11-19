from collections.abc import Mapping
from dataclasses import dataclass
import json

from intake.parse import decimal_text, valid_name, valid_slot


class OrderError(ValueError):
    """The paper review order has malformed or ambiguous instructions."""


@dataclass(frozen=True, slots=True)
class ValueChange:
    plate: str
    slot: int
    value: int

    @property
    def key(self) -> tuple[str, int]:
        return self.plate, self.slot


@dataclass(frozen=True, slots=True)
class AmendOrder:
    changes: tuple[ValueChange, ...]
    reveal: tuple[str, ...]


def parse_order(changes, reveal) -> AmendOrder:
    if not isinstance(changes, (list, tuple)) or not isinstance(reveal, (list, tuple)):
        raise OrderError('changes and reveals must be lists or tuples')
    if any(not valid_name(plate) for plate in reveal) or len(set(reveal)) != len(reveal):
        raise OrderError('reveal list has an invalid or repeated plate')
    parsed = []
    seen = set()
    for position, record in enumerate(changes, 1):
        if not isinstance(record, Mapping) or set(record) != {'plate', 'slot', 'value'}:
            raise OrderError(f'change {position} requires plate, slot and value')
        plate, slot, value = record['plate'], record['slot'], record['value']
        if not valid_name(plate) or not valid_slot(slot) or type(value) is not int:
            raise OrderError(f'change {position} requires an original plate and slot and an integer')
        change = ValueChange(plate, slot, value)
        if change.key in seen:
            raise OrderError(f'change {position} repeats an original slot')
        seen.add(change.key)
        parsed.append(change)
    return AmendOrder(tuple(parsed), tuple(reveal))


def archive_order(order: AmendOrder) -> str:
    return json.dumps({
        'changes': [{'plate': change.plate, 'slot': decimal_text(change.slot), 'value': decimal_text(change.value)}
                    for change in order.changes],
        'reveal': list(order.reveal),
    }, ensure_ascii=False, separators=(',', ':'))
