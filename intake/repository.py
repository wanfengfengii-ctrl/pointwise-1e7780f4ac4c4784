from contextlib import contextmanager
import sqlite3
from uuid import uuid4

from intake.revisions import PlateRevision, RevisionContent, canonical_revision_content, restore_revision_content


def new_id(prefix: str) -> str:
    return f'{prefix}-{uuid4().hex}'


@contextmanager
def write_transaction(db: sqlite3.Connection):
    """Own one write transaction, including rollback when COMMIT itself raises."""
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def open_database(path, *initializers) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys = ON')
        with write_transaction(db):
            for initialize in initializers:
                initialize(db)
    except BaseException:
        db.close()
        raise
    return db


def _init_revisions(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS revisions (
            revision_id TEXT PRIMARY KEY NOT NULL,
            batch TEXT NOT NULL,
            content TEXT NOT NULL,
            UNIQUE (batch, content)
        )
    ''')


def open_source(path) -> sqlite3.Connection:
    from exchange.issue import init_issuance
    from selection.freeze import init_selections

    return open_database(path, _init_revisions, init_selections, init_issuance)


class RevisionStore:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def match_content(self, batch: str, content: RevisionContent) -> str | None:
        row = self.db.execute(
            'SELECT revision_id FROM revisions WHERE batch = ? AND content = ?',
            (batch, canonical_revision_content(content)),
        ).fetchone()
        return row[0] if row else None

    def has_batch(self, batch: str) -> bool:
        return self.db.execute('SELECT 1 FROM revisions WHERE batch = ? LIMIT 1', (batch,)).fetchone() is not None

    def get(self, revision_id: str) -> PlateRevision | None:
        row = self.db.execute(
            'SELECT batch, content FROM revisions WHERE revision_id = ?', (revision_id,),
        ).fetchone()
        if row is None:
            return None
        batch, content = row
        return PlateRevision(revision_id, batch, restore_revision_content(content))

    def append(self, batch: str, content: RevisionContent) -> str:
        revision_id = new_id('rev')
        self.db.execute(
            'INSERT INTO revisions (revision_id, batch, content) VALUES (?, ?, ?)',
            (revision_id, batch, canonical_revision_content(content)),
        )
        return revision_id
