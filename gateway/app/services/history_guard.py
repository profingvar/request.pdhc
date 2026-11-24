"""#1054: request.pdhc's version history is APPEND-ONLY.

The pattern of cdr.pdhc's `cdr_app/app/models/history_guard.py` (#984),
applied to `service_request_history` and `care_plan_history`. Three layers:

  1. no code path updates or deletes a history row;
  2. an ORM event raises on UPDATE or DELETE of a history object;
  3. a database trigger refuses both, which holds against raw SQL and bulk
     `query.delete()` (which skips ORM events).

THE ONE ESCAPE is a deliberate purge of SYNTHETIC data (the test suite's
per-test cleanup, or a fresh-start wipe like 2026-08-09). It must be asked for
by name, inside `history_purge()`; it allows DELETE only, never UPDATE, and the
permission ends with that transaction.
"""
from __future__ import annotations

import contextlib
import contextvars

from sqlalchemy import event, text

GUARDED_TABLES = ("service_request_history", "care_plan_history")
PG_FLAG = "request.allow_history_purge"
SQLITE_FLAG_TABLE = "request_history_purge_flag"

_purging = contextvars.ContextVar("request_history_purge", default=False)


class HistoryIsAppendOnly(RuntimeError):
    pass


@contextlib.contextmanager
def history_purge(session):
    """Allow DELETING history rows, for a purge of synthetic data.

    Its own transaction: commits on a clean exit, rolls back on an error.
    On Postgres the permission is a SET LOCAL; on SQLite a flag row that is
    removed before the same commit, so it cannot outlive the purge.
    """
    dialect = session.get_bind().dialect.name
    token = _purging.set(True)
    try:
        if dialect == "postgresql":
            session.execute(text(f"SET LOCAL {PG_FLAG} = 'on'"))
        elif dialect == "sqlite":
            session.execute(text(f"CREATE TABLE IF NOT EXISTS {SQLITE_FLAG_TABLE} (x INTEGER)"))
            session.execute(text(f"INSERT INTO {SQLITE_FLAG_TABLE} VALUES (1)"))
        yield
        if dialect == "sqlite":
            session.execute(text(f"DELETE FROM {SQLITE_FLAG_TABLE}"))
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        _purging.reset(token)


def _pg_ddl(table: str) -> list[str]:
    fn = f"{table}_append_only"
    return [
        f"""CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF coalesce(current_setting('{PG_FLAG}', true), '') = 'on' AND TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION '{table} is append-only (#1054): % refused', TG_OP;
END $$""",
        f"DROP TRIGGER IF EXISTS {fn}_trg ON {table}",
        f"CREATE TRIGGER {fn}_trg BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {fn}()",
    ]


def _pg_drop_ddl(table: str) -> list[str]:
    fn = f"{table}_append_only"
    return [f"DROP TRIGGER IF EXISTS {fn}_trg ON {table}",
            f"DROP FUNCTION IF EXISTS {fn}()"]


def _sqlite_ddl(table: str) -> list[str]:
    return [
        f"CREATE TABLE IF NOT EXISTS {SQLITE_FLAG_TABLE} (x INTEGER)",
        f"""CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table}
BEGIN SELECT RAISE(ABORT, '{table} is append-only (#1054): UPDATE refused'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table}
WHEN NOT EXISTS (SELECT 1 FROM {SQLITE_FLAG_TABLE})
BEGIN SELECT RAISE(ABORT, '{table} is append-only (#1054): DELETE refused'); END""",
    ]


def ddl_for(table: str, dialect: str) -> list[str]:
    if dialect == "postgresql":
        return _pg_ddl(table)
    if dialect == "sqlite":
        return _sqlite_ddl(table)
    return []


def drop_ddl_for(table: str, dialect: str) -> list[str]:
    if dialect == "postgresql":
        return _pg_drop_ddl(table)
    if dialect == "sqlite":
        return [f"DROP TRIGGER IF EXISTS {table}_no_update",
                f"DROP TRIGGER IF EXISTS {table}_no_delete"]
    return []


_installed = False


def install() -> None:
    """Attach the ORM guard and the create_all DDL to both history classes.
    Idempotent (create_app may run more than once in a process)."""
    global _installed
    if _installed:
        return
    from app.models.history_models import CarePlanHistory, ServiceRequestHistory
    for cls in (ServiceRequestHistory, CarePlanHistory):
        table = cls.__table__

        @event.listens_for(cls, "before_update", propagate=True)
        def _no_update(mapper, connection, target, _t=table.name):
            raise HistoryIsAppendOnly(f"{_t} is append-only (#1054): UPDATE refused")

        @event.listens_for(cls, "before_delete", propagate=True)
        def _no_delete(mapper, connection, target, _t=table.name):
            if not _purging.get():
                raise HistoryIsAppendOnly(f"{_t} is append-only (#1054): DELETE refused")

        @event.listens_for(table, "after_create")
        def _ddl(target, connection, **kw):
            for stmt in ddl_for(target.name, connection.dialect.name):
                connection.execute(text(stmt))
    _installed = True
