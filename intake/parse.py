from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
import re


class BoardParseError(ValueError):
    """A recorded instrument row is malformed."""


@dataclass(frozen=True, slots=True)
class SourceRow:
    plate: str
    slot: int
    value: int | None
    source_line: int

    @property
    def key(self) -> tuple[str, int]:
        return self.plate, self.slot


def valid_name(value: object) -> bool:
    return isinstance(value, str) and value.isprintable() and value == value.strip()


def valid_slot(value: object) -> bool:
    return type(value) is int and value > 0


def decimal_text(value: int) -> str:
    """Render an exact integer without a floating-point or SQLite integer conversion."""
    return str(Decimal(value))


def read_decimal(text: object) -> int:
    if not isinstance(text, str) or re.fullmatch(r'0|-?[1-9][0-9]*', text) is None:
        raise ValueError('expected a canonical decimal integer')
    return int(Decimal(text))


def parse_board(rows: Sequence[Mapping]) -> tuple[SourceRow, ...]:
    if not isinstance(rows, (list, tuple)):
        raise BoardParseError('board rows must be an ordered list or tuple')
    parsed = []
    for line, row in enumerate(rows, 1):
        if not isinstance(row, Mapping) or set(row) != {'plate', 'slot', 'value'}:
            raise BoardParseError(f'line {line} requires plate, slot and explicit value')
        plate, slot, value = row['plate'], row['slot'], row['value']
        if not valid_name(plate) or not valid_slot(slot):
            raise BoardParseError(f'line {line} has an invalid plate or slot')
        if value is not None and type(value) is not int:
            raise BoardParseError(f'line {line} requires an integer or explicit null')
        parsed.append(SourceRow(plate, slot, value, line))
    return tuple(parsed)
