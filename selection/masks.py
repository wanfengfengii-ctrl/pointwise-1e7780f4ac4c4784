from dataclasses import dataclass

from intake.parse import valid_name


@dataclass(frozen=True, slots=True)
class InitialMasks:
    plates: frozenset[str]


def read_initial_masks(plates) -> InitialMasks:
    if not isinstance(plates, (list, tuple)) or any(not valid_name(plate) for plate in plates):
        raise ValueError('initial masks require a list of plate names')
    if len(set(plates)) != len(plates):
        raise ValueError('a plate was masked more than once')
    return InitialMasks(frozenset(plates))
