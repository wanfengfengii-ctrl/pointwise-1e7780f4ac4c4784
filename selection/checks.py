from intake.revisions import PlateRevision
from selection.masks import InitialMasks
from selection.scope import ScopeError, SelectionScope, choose_plates


class SelectionError(ValueError):
    """The selection cannot be frozen against the requested source revision."""


def validate_selection(revision: PlateRevision, scope: SelectionScope, masks: InitialMasks) -> None:
    try:
        expected_scope = choose_plates(revision, scope.plates)
    except ScopeError as exc:
        raise SelectionError(str(exc)) from exc
    if scope != expected_scope:
        raise SelectionError('frozen scope differs from the source inventory')
    if not masks.plates.issubset(scope.plates):
        raise SelectionError('masked plate lies outside the selection')
