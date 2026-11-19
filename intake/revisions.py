from dataclasses import dataclass
import json

from intake.layout import PlateLayout
from intake.parse import SourceRow, decimal_text, read_decimal


@dataclass(frozen=True, slots=True)
class RevisionContent:
    layouts: tuple[PlateLayout, ...]
    rows: tuple[SourceRow, ...]


@dataclass(frozen=True, slots=True)
class PlateRevision:
    revision_id: str
    batch: str
    content: RevisionContent


def pack_layouts(layouts: tuple[PlateLayout, ...]) -> list:
    return [[layout.plate, [decimal_text(slot) for slot in layout.slots]] for layout in layouts]


def unpack_layouts(records: list) -> tuple[PlateLayout, ...]:
    return tuple(PlateLayout(plate, tuple(map(read_decimal, slots))) for plate, slots in records)


def canonical_revision_content(content: RevisionContent) -> str:
    rows = []
    for row in content.rows:
        value = None if row.value is None else decimal_text(row.value)
        rows.append([row.plate, decimal_text(row.slot), value, decimal_text(row.source_line)])
    return json.dumps({'layouts': pack_layouts(content.layouts), 'rows': rows},
                      ensure_ascii=False, separators=(',', ':'))


def restore_revision_content(text: str) -> RevisionContent:
    document = json.loads(text)
    rows = tuple(
        SourceRow(plate, read_decimal(slot), None if value is None else read_decimal(value),
                  read_decimal(line))
        for plate, slot, value, line in document['rows']
    )
    return RevisionContent(unpack_layouts(document['layouts']), rows)
