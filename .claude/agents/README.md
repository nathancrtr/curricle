# `.claude/agents/`

Subagent roles come from [rolecall](https://github.com/nathancrtr/rolecall) and are
loaded from `~/.claude/agents/` in every session, so this directory is normally
empty. The portable role bodies are maintained once, there, for every repository
that uses them.

What curricle adds to a role lives in the `## Agent roles` section of `CLAUDE.md`,
which is already in every subagent's context — one `### <role>` entry per role, and
the place for repo-specific commands, paths and conventions. Keep a full copy of a
role here only when its **frontmatter** must differ from the shared one (a different
model pin, a narrower tool list): a file here shadows the shared role by name, so
such a copy carries `extends: rolecall/<name>@<commit>` to record what it diverged
from.
