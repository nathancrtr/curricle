"""Alembic environment.

The URL comes from curricle.db.database_url() — the single engine factory —
unless the invoker hands us a live connection via config.attributes
["connection"], which the test harness does to run migrations inside its
own throwaway cluster.
"""

from __future__ import annotations

import os
import sys

from alembic import context

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from curricle import db  # noqa: E402

target_metadata = db.metadata


def run_migrations() -> None:
    connectable = context.config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = db.make_engine()
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("offline mode is not supported; run against a database")
run_migrations()
