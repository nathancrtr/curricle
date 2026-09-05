# curricle as a container: the compiler, the renderers, the web app, the
# worker and the factory's role contracts, in one image that runs as two
# different processes.
#
# The image copies a checkout rather than just installing the wheel, and that
# is deliberate. `llm.home()` resolves `models.yaml` and `roles/` relative to
# the checkout root, because they are operator-editable configuration and
# burying them in site-packages defeats their purpose (CLAUDE.md says so in
# as many words). So the checkout lands at /app and CURRICLE_HOME points at
# it, which is exactly the escape hatch `llm.home()` documents for an
# installed copy. Same reasoning puts `alembic.ini` and `migrations/` here:
# schema changes go through Alembic and never `create_all`, so the image has
# to be able to run `alembic upgrade head` with /app as its working directory.
#
# There is no ENTRYPOINT. curricle is two processes — `serve`, which may
# never touch a model (invariant L1), and `work`, which is the only thing
# that may — and an image that presumed one of them would be lying about the
# other. The caller names the command.

FROM python:3.12-slim

# Bytecode caching buys nothing in a container that runs one command, and
# unbuffered stdout means `docker logs` shows the greeting and the worker's
# poll line as they happen rather than when a buffer happens to flush.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, on their own layer: pyproject changes rarely and the
# package source changes every build, so this keeps the slow pip install out
# of the common rebuild. README.md and LICENSE come along because pyproject
# names them (`readme`, `license-files`) and the build fails without them.
COPY pyproject.toml README.md LICENSE ./
COPY curricle/ ./curricle/
# setuptools builds in place, so it leaves `build/` and `curricle.egg-info/`
# behind in the working directory. Neither is read at runtime, and `build/`
# in particular is a name this repo uses for committed artifacts — leaving a
# setuptools staging copy sitting at /app/build would be actively confusing
# to anyone who exec'd into the container to look around.
RUN pip install --no-cache-dir . \
 && rm -rf build curricle.egg-info

# The rest of the checkout: everything that is configuration or contract
# rather than package code. `examples/` earns its place as the one course
# that is known to compile clean — a way to prove a fresh deployment works
# before pointing it at real content.
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY roles/ ./roles/
COPY models.yaml ./
COPY examples/ ./examples/
# `docs/` because the app serves `docs/mcp-config.md` itself at /docs/
# (the landing card links it); a checkout without it 404s that link.
COPY docs/ ./docs/

# Where the factory looks for models.yaml and roles/ — see the header.
ENV CURRICLE_HOME=/app

# Documentation, not a binding: `serve --port` decides the real one.
EXPOSE 8765

# A default that is honest about needing configuration rather than one that
# guesses a tenant. There is no default tenant anywhere in this codebase and
# this is not the place to invent one.
CMD ["python", "-m", "curricle", "--help"]
