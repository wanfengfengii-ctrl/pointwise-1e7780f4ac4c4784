from exchange.contract import PieceBody
from review.orders import AmendOrder


class TargetError(ValueError):
    """A requested value change cannot be applied to its original slot."""


def resolve_targets(body: PieceBody, order: AmendOrder) -> dict[tuple[str, int], int]:
    original = {slot.key: slot for slot in body.slots}
    changes = {}
    for change in order.changes:
        slot = original.get(change.key)
        if slot is None:
            raise TargetError(f'unknown original slot on plate {change.plate}')
        if slot.value is None:
            raise TargetError(f'cannot amend an empty slot on plate {change.plate}')
        changes[slot.key] = change.value
    return changes
