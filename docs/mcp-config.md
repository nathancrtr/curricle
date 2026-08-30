# Connecting the tutor: the MCP config

curricle can export a course to your own assistant as an [MCP](https://modelcontextprotocol.io)
server over stdio. This page is the config block to paste, and what the block
actually gets you.

## What the tutor export is

The course pages in the browser are one way to work. The tutor export is the
other: `python -m curricle mcp` serves the same course — the manifest, your
learner profile, your progress, the lesson guides, the question bank — as
tools that your assistant calls.

Two things follow from that, and they are the design rather than a limitation:

- **The conversation happens on your assistant, on your inference bill.** This
  server hands out context and accepts evidence. It never calls a model itself,
  which is the same rule the web app keeps: no model on a request path, ever.
- **It runs on your machine, against your database.** Auth is process
  ownership, exactly as it is for `serve`. Anyone who can run the command is
  the tenant.

What the tutor can write is deliberately narrow. Progress events go straight
in — marking a unit done is a fact about what you did. Profile evidence does
not: the tools emit *proposals* that render nowhere until you accept them on
`/profile`, and a proposal arriving over the wire has to name its source. The
agent proposes; the human publishes.

## The config

Most MCP clients read a JSON file of servers. The block is the same shape
wherever it goes — fill in the course directory and your tenant slug:

```json
{
  "mcpServers": {
    "curricle-tutor": {
      "command": "python",
      "args": ["-m", "curricle", "mcp",
               "--course", "/path/to/your/course",
               "--tenant", "your-tenant-slug"]
    }
  }
}
```

- `--course` is a course repo root — the directory holding `learning/course.yaml`.
  Repeat the flag to export more than one course through a single server.
- `--tenant` is a tenant slug that already exists. There is no default tenant:
  an unknown slug is a refusal at startup, not an empty account.
- `command` should be whichever interpreter has curricle installed. If you run
  the repo out of a virtualenv, spell that interpreter's full path here — an
  MCP client does not inherit your shell's activated environment.

The server also needs `CURRICLE_DATABASE_URL` set in the environment it starts
in, the same one `serve` and `work` use.

## Where a filled-in copy comes from

The onboarding wizard prints this block already filled in — real course path,
real tenant slug — on the card it lands you on when your course is published.
That is the copy to take if you have just finished setting up. This page is
here for the day the tab is closed.
