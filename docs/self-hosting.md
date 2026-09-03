# Self-hosting curricle

The quickstart in the README runs curricle out of a terminal, which is the
right shape while you are working on it and the wrong one once you want the
course to be there tomorrow. This is the other shape: a container image, a
Postgres, and a reverse proxy that supplies the authentication curricle
deliberately does not have.

Read [Security posture](../README.md#security-posture) first. Everything
below assumes you have and that you accept the consequence.

## The one thing to get right

**curricle has no authentication.** Anyone who can reach the port is the
tenant — not a user of the tenant's, *the* tenant, with the ledger and the
profile and the API budget that implies. There is no login page to bypass
because there is no login page.

So a deployment is two decisions, and the second is the one that matters:

1. `--host 0.0.0.0`, because a container's `127.0.0.1` is its own loopback and
   nothing outside reaches it.
2. Something in front that authenticates, plus a publish narrow enough that
   the something cannot be walked around.

These are a pair. Widening the bind without narrowing the publish, or
narrowing the publish without putting a gate on the proxy, gives you an
unauthenticated app on a network — and it will look like it is working
perfectly, which is what makes it worth stating twice.

The deployment below publishes on the host's loopback only
(`127.0.0.1:8765:8765`) so the sole route in is a reverse proxy on that host,
and the gate lives there.

## The image

```
ghcr.io/nathancrtr/curricle:<tag>
```

Pin a tag. `:latest` moves, and "which version is running" should be a
question the deployment can answer.

The image is a checkout at `/app` rather than just an installed wheel,
because `models.yaml` and `roles/` are operator-editable configuration that
`llm.home()` resolves from the checkout root — so `CURRICLE_HOME=/app` is
baked in. `alembic.ini` and `migrations/` are there for the same class of
reason: schema changes go through Alembic, never `create_all`, so the image
has to be able to run the migration itself. `examples/tinylang` ships too, as
a course known to compile clean — useful for proving a fresh deployment works
before you point it at anything you care about.

There is no `ENTRYPOINT`, because curricle is two processes.

## The two processes

| | command | talks to a model? |
|---|---|---|
| the app | `python -m curricle serve --tenant … --host 0.0.0.0` | **never** |
| the worker | `python -m curricle work` | yes, this is the only thing that does |

This split is invariant **L1**: no LLM on a request path, ever. The web app
writes request rows; the worker claims them, spends the money, and appends
the outcome. They share a database and nothing else.

You can run the app alone. The onboarding wizard will then accept your
answers and queue its model-calling stages, and nothing will run them — so if
you are not deploying the worker, know that the wizard is a half-open door.

## Configuration

| variable | who needs it | notes |
|---|---|---|
| `CURRICLE_DATABASE_URL` | both | `postgresql+psycopg://user:pw@host/db`. No default — an unconfigured caller gets an exception. |
| `CURRICLE_COURSES_DIR` | both | Where wizard-created courses live, one directory per course. No default. |
| `CURRICLE_HOME` | worker | Already `/app` in the image. Only set it if you mount your own `roles/`. |
| `ANTHROPIC_API_KEY` | worker only | The app must never be given it. |

`--course <root>` still works alongside the courses home for courses that
live in their own repositories.

A course in the courses home is a directory carrying a sidecar at
`learning/course.yaml` or `course.yaml`. **Name the directory the same as the
sidecar's `course.id`** — registration keys on the directory basename, and a
disagreement between the two is a course the lazy lookup path cannot find.

## A worked deployment

```yaml
name: curricle

services:
  curricle-db:
    image: postgres:16
    environment:
      POSTGRES_DB: curricle
      POSTGRES_PASSWORD: ${CURRICLE_DB_PASSWORD:?}
    volumes:
      - ./db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d curricle"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  curricle:
    image: ghcr.io/nathancrtr/curricle:v0.1.1
    command: >
      python -m curricle serve
      --tenant you --port 8765 --host 0.0.0.0
    # Loopback on the HOST. The container binds 0.0.0.0 because it must;
    # this line is what keeps that from meaning anything to the network.
    ports:
      - "127.0.0.1:8765:8765"
    environment:
      CURRICLE_DATABASE_URL: postgresql+psycopg://postgres:${CURRICLE_DB_PASSWORD:?}@curricle-db/curricle
      CURRICLE_COURSES_DIR: /courses
    volumes:
      - ./courses:/courses
    depends_on:
      curricle-db:
        condition: service_healthy
    restart: unless-stopped

  curricle-worker:
    image: ghcr.io/nathancrtr/curricle:v0.1.1
    command: python -m curricle work
    environment:
      CURRICLE_DATABASE_URL: postgresql+psycopg://postgres:${CURRICLE_DB_PASSWORD:?}@curricle-db/curricle
      CURRICLE_COURSES_DIR: /courses
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:?}
    volumes:
      - ./courses:/courses
    depends_on:
      curricle-db:
        condition: service_healthy
    restart: unless-stopped
```

Migrate before first serve, and after every image bump:

```sh
docker compose up -d curricle-db
docker compose run --rm --no-deps curricle alembic upgrade head
docker compose up -d
```

`alembic upgrade head` is a no-op when already at head, so it is safe to run
on every deploy — and running it on every deploy is the point.

Then provision the tenant once (skip this if you restored a database that
already has one):

```sh
docker compose run --rm --no-deps curricle python -m curricle tenant create you
```

## Backups

Back up two things, differently:

- **The courses directory** is ordinary files; copy it.
- **The database** is the ledger — every progress mark and every piece of
  profile evidence you have accumulated. Do not file-copy a live Postgres
  datadir. Take a logical dump: `docker exec <db container> pg_dumpall
  --clean --if-exists --username=postgres | gzip > dump.sql.gz`.

The ledger is append-only and everything else is a projection, so the dump is
genuinely the whole of your state.

## What does not work remotely

`python -m curricle mcp` (the tutor export) is a stdio server, and it needs
**both** the course files and the progress database on the machine it runs
on. If the database is on a server, running the MCP export from your laptop
is not a matter of configuration — neither half is local. Nothing here solves
that; it is a real limitation, recorded rather than papered over.

`--profile-skill-out` has the same shape of problem: it renders the
learner-profile projection to a path on the machine running `serve`, so a
remote deployment cannot write it to your laptop's skills directory. Render
it from a checkout instead.
