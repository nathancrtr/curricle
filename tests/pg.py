"""Throwaway Postgres for the test suite.

One initdb cluster per test process, in a temp dir, unix-socket only, torn
down at exit. Tests never read a database URL from the environment — the
suite cannot be pointed at a real database, by construction (the job-radar
lesson that cost a production database twice in four hours).

Migrations run via Alembic against the throwaway cluster, so every test run
also proves the migration chain.
"""

from __future__ import annotations

import atexit
import glob
import os
import shutil
import subprocess
import tempfile

import sqlalchemy as sa

_engine: sa.Engine | None = None
_datadir: str | None = None


def _pg_bin(name: str) -> str:
    """Find a Postgres binary without asking the environment: Homebrew's
    keg and prefix on macOS, then Debian's versioned directories (which are
    deliberately off PATH — that is how GitHub's Ubuntu runners ship
    Postgres), newest first. Falls back to PATH."""
    prefixes = ["/opt/homebrew/opt/postgresql@16/bin", "/opt/homebrew/bin",
                "/usr/local/bin", "/usr/bin"]
    prefixes += sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True)
    for prefix in prefixes:
        candidate = os.path.join(prefix, name)
        if os.path.exists(candidate):
            return candidate
    return name


def test_engine() -> sa.Engine:
    """The suite's engine, creating the cluster on first use."""
    global _engine, _datadir
    if _engine is not None:
        return _engine

    _datadir = tempfile.mkdtemp(prefix="curricle-pg-")
    sock = os.path.join(_datadir, "sock")
    os.makedirs(sock)
    data = os.path.join(_datadir, "data")
    subprocess.run([_pg_bin("initdb"), "-D", data, "--no-sync", "-E", "UTF8"],
                   check=True, capture_output=True)
    # NB: never capture pg_ctl start's output — the postmaster inherits the
    # pipes and holds them open, so run() would block forever. Log to a file.
    subprocess.run(
        [_pg_bin("pg_ctl"), "-D", data, "-w",
         "-l", os.path.join(_datadir, "pg.log"), "-o",
         f"-F -k {sock} -c listen_addresses=''", "start"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(_teardown)
    subprocess.run([_pg_bin("createdb"), "-h", sock, "curricle_test"],
                   check=True, capture_output=True)

    url = f"postgresql+psycopg:///curricle_test?host={sock}"
    _engine = sa.create_engine(url)
    _migrate(_engine)
    return _engine


def _migrate(engine: sa.Engine) -> None:
    from alembic import command
    from alembic.config import Config

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "migrations"))
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        conn.commit()


def _teardown() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
    if _datadir:
        subprocess.run(
            [_pg_bin("pg_ctl"), "-D", os.path.join(_datadir, "data"),
             "-m", "immediate", "stop"],
            capture_output=True)
        shutil.rmtree(_datadir, ignore_errors=True)
