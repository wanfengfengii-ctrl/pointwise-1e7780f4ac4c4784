from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from intake.parse import SourceRow, valid_name, valid_slot


class LayoutError(ValueError):
    """The inventory or its correspondence to the instrument rows is invalid."""


@dataclass(frozen=True, slots=True)
class PlateLayout:
    plate: str
    slots: tuple[int, ...]


def validate_layout(inventory: Sequence[Mapping], rows: tuple[SourceRow, ...]) -> tuple[PlateLayout, ...]:
    if not isinstance(inventory, (list, tuple)) or not inventory:
        raise LayoutError('inventory requires at least one plate')
    plates = set()
    declared = set()
    layouts = []
    for record in inventory:
        if not isinstance(record, Mapping) or set(record) != {'plate', 'slots'}:
            raise LayoutError('inventory entry requires plate and slots')
        plate, slots = record['plate'], record['slots']
        if not valid_name(plate) or plate in plates:
            raise LayoutError('invalid or repeated inventory plate')
        if not isinstance(slots, (list, tuple)) or any(not valid_slot(slot) for slot in slots):
            raise LayoutError(f'invalid slot inventory for plate {plate}')
        if len(set(slots)) != len(slots):
            raise LayoutError(f'repeated inventory slot for plate {plate}')
        plates.add(plate)
        declared.update((plate, slot) for slot in slots)
        layouts.append(PlateLayout(plate, tuple(slots)))

    seen = set()
    for row in rows:
        if row.key in seen:
            raise LayoutError(f'line {row.source_line} repeats a plate slot')
        if row.key not in declared:
            raise LayoutError(f'line {row.source_line} refers outside the inventory')
        seen.add(row.key)
    if declared != seen:
        raise LayoutError('each declared slot requires its own instrument row, including empty slots')
    return tuple(layouts)
