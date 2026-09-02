"""curricle — a personalized-learning platform.

At the foundation, the manifest layer: the course manifest schema, a compiler
over the corpus's curriculum.md conventions, and validation that turns house
rules into refusals. Everything else — renderers, progress, profile, factory,
web app, tutor export — reads the manifest that layer emits.
"""

from .schema import Manifest, SchemaError  # noqa: F401
