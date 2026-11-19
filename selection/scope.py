from dataclasses import dataclass

from intake.layout import PlateLayout
from intake.parse import valid_name
from intake.revisions import PlateRevision


class ScopeError(ValueError):
    """The chosen plates cannot be supplied by the given source revision."""


@dataclass(frozen=True, slots=True)
class SelectionScope:
    revision_id: str
    layouts: tuple[PlateLayout, ...]

    @property
    def plates(self) -> tuple[str, ...]:
        return tuple(layout.plate for layout in self.layouts)


def choose_plates(revision: PlateRevision, plates) -> SelectionScope:
    if not isinstance(plates, (list, tuple)) or not plates or any(not valid_name(plate) for plate in plates):
        raise ScopeError('select a nonempty ordered list of plate names')
    requested = set(plates)
    if len(requested) != len(plates):
        raise ScopeError('a plate was selected more than once')
    layouts = tuple(layout for layout in revision.content.layouts if layout.plate in requested)
    if len(layouts) != len(requested):
        raise ScopeError('a selected plate is absent from the revision')
    return SelectionScope(revision.revision_id, layouts)
