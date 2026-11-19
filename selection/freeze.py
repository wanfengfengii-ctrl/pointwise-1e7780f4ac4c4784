from dataclasses import dataclass
import json
import sqlite3

from intake.parse import valid_name
from intake.repository import RevisionStore, new_id, write_transaction
from intake.revisions import pack_layouts, unpack_layouts
from selection.checks import SelectionError, validate_selection
from selection.masks import InitialMasks, read_initial_masks
from selection.scope import SelectionScope, choose_plates


@dataclass(frozen=True, slots=True)
class SelectionRecord:
    selection_id: str
    scope: SelectionScope
    masks: InitialMasks


def init_selections(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS selections (
            selection_id TEXT PRIMARY KEY NOT NULL,
            revision_id TEXT NOT NULL REFERENCES revisions (revision_id),
            layouts TEXT NOT NULL,
            masked TEXT NOT NULL
        )
    ''')


class SelectionStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, selection_id: str) -> SelectionRecord | None:
        row = self.db.execute(
            'SELECT revision_id, layouts, masked FROM selections WHERE selection_id = ?',
            (selection_id,),
        ).fetchone()
        if row is None:
            return None
        revision_id, layouts, masked = row
        scope = SelectionScope(revision_id, unpack_layouts(json.loads(layouts)))
        return SelectionRecord(selection_id, scope, read_initial_masks(json.loads(masked)))

    def save(self, scope: SelectionScope, masks: InitialMasks) -> str:
        selection_id = new_id('sel')
        masked = [plate for plate in scope.plates if plate in masks.plates]
        self.db.execute(
            'INSERT INTO selections (selection_id, revision_id, layouts, masked) VALUES (?, ?, ?, ?)',
            (selection_id, scope.revision_id, json.dumps(pack_layouts(scope.layouts)), json.dumps(masked)),
        )
        return selection_id


def stage(db: sqlite3.Connection, revision_id: str, plates, masked=()) -> str:
    if not valid_name(revision_id):
        raise SelectionError('invalid source revision number')
    try:
        with write_transaction(db):
            revision = RevisionStore(db).get(revision_id)
            if revision is None:
                raise SelectionError('unknown source revision')
            scope = choose_plates(revision, plates)
            masks = read_initial_masks(masked)
            validate_selection(revision, scope, masks)
            return SelectionStore(db).save(scope, masks)
    except SelectionError:
        raise
    except (ValueError, sqlite3.Error) as exc:
        raise SelectionError(f'cannot freeze selection: {exc}') from exc
