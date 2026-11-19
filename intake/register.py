import sqlite3

from intake.layout import LayoutError, validate_layout
from intake.parse import BoardParseError, parse_board, valid_name
from intake.repository import RevisionStore, write_transaction
from intake.revisions import RevisionContent


class RegistrationError(ValueError):
    """The board could not be registered as a complete fixed revision."""


def register(db: sqlite3.Connection, batch: str, inventory, rows, *, correction: bool = False) -> str:
    if not valid_name(batch) or type(correction) is not bool:
        raise RegistrationError('invalid batch or correction flag')
    try:
        source_rows = parse_board(rows)
        content = RevisionContent(validate_layout(inventory, source_rows), source_rows)
        store = RevisionStore(db)
        with write_transaction(db):
            existing = store.match_content(batch, content)
            if existing is not None:
                return existing
            if store.has_batch(batch) != correction:
                if correction:
                    raise RegistrationError('correction requires a registered batch')
                raise RegistrationError('different content for this batch requires an explicit correction')
            return store.append(batch, content)
    except (BoardParseError, LayoutError, sqlite3.Error) as exc:
        raise RegistrationError(f'board registration failed: {exc}') from exc
