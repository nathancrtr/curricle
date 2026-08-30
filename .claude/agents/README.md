# `.claude/agents/`

Project-scoped subagent definitions. Claude Code resolves these **ahead of** the
copies in `~/.claude/agents/`, so a file here shadows the personal version for
anyone working in this repository.

## Where they come from

The bodies are portable role definitions maintained outside this repository —
originally the author's user-level `~/.claude/agents/` and a sibling project.
Each file then carries an appended `## In this repo` section holding only what
that role additionally needs to know about curricle.

That upstream is personal and not public, so treat these two files as the
authoritative copies here. Nothing depends on the upstream existing.

Keep project context in the appended section and nowhere else, so re-syncing an
upstream improvement stays a mechanical diff above the `---`.

## What is here, and why only these two

`analyst`, `architect`, `designer`, `historian`, `implementer`, `integrator`,
`ops`, `reviewer`, `ux-researcher`, and `verifier` already exist at user level
and resolve fine unshadowed. Only the roles that are **missing** there, or that
need curricle-specific framing, live here:

- **`art-director`** — pinned to `model: fable`. Judgment quality is the
  product for this role; it is never run cheap, and the aesthetic ceiling of
  this project is set by what this agent can see.
- **`copywriter`** — carries the one trap that matters here: the repo's
  internal prose voice is not the product voice.

## What belongs in `## In this repo`

Only what is role-specific and not already loaded. `CLAUDE.md` is in every
agent's context and carries the architecture, the invariants, and the phase
map — copying any of it here would create a second, independently-rotting
copy. Verify before you add.
