from exchange.contract import PieceBody


class RevealError(ValueError):
    """A reveal command names a plate outside the accepted piece."""


def resolve_reveals(body: PieceBody, reveal: tuple[str, ...]) -> tuple[str, ...]:
    requested = set(reveal)
    unknown = requested.difference(body.plates)
    if unknown:
        raise RevealError(f'unknown reveal plate: {min(unknown)}')
    return tuple(plate for plate in body.masked if plate not in requested)
