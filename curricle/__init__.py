"""curricle — the manifest layer of a personalized-learning platform.

Phase 0 scope (see ~/repos/learning/platform-design.md §9): the course
manifest schema, a compiler over the corpus's curriculum.md conventions,
and validation that turns house rules into refusals.
"""

from .schema import Manifest, SchemaError  # noqa: F401
