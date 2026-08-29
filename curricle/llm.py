"""The one metered executor. Every LLM call in the platform goes through
``Runner.run_role`` — streams, carries a stage label, writes the token
ledger, and refuses once the stage's budget is spent (invariants L1–L2).

Roles are markdown contracts under roles/ (frontmatter: name, then the
system prompt as body); tiers and prices live in models.yaml, the only
file that names a model. The Anthropic client is injectable so the entire
factory tests without a network.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
import yaml

from . import db

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_PATH = os.path.join(REPO_ROOT, "models.yaml")
ROLES_DIR = os.path.join(REPO_ROOT, "roles")

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelsConfig:
    tiers: dict[str, str]
    prices: dict[str, dict[str, float]]
    roles: dict[str, str]           # role name -> tier
    budgets: dict[str, float]       # stage -> USD ceiling; "default" fallback

    def model_for_role(self, role: str) -> str:
        tier = self.roles.get(role)
        if tier is None:
            raise KeyError(f"role {role!r} has no tier in models.yaml")
        return self.tiers[tier]

    def budget_for_stage(self, stage: str) -> Decimal:
        return Decimal(str(self.budgets.get(stage, self.budgets["default"])))

    def cost(self, model: str, input_tokens: int, output_tokens: int,
             cache_write: int = 0, cache_read: int = 0) -> Decimal:
        p = self.prices[model]
        per_m = Decimal(1_000_000)
        return (Decimal(input_tokens) * Decimal(str(p["input"]))
                + Decimal(output_tokens) * Decimal(str(p["output"]))
                + Decimal(cache_write) * Decimal(str(p["cache_write"]))
                + Decimal(cache_read) * Decimal(str(p["cache_read"]))) / per_m


def load_models_config(path: str = MODELS_PATH) -> ModelsConfig:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ModelsConfig(tiers=data["tiers"], prices=data["prices"],
                        roles=data["roles"], budgets=data["budgets"])


@dataclass(frozen=True)
class Role:
    name: str
    system: str


def load_role(name: str, roles_dir: str = ROLES_DIR) -> Role:
    path = os.path.join(roles_dir, f"{name}.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"{path}: role file needs frontmatter")
    meta = yaml.safe_load(m.group(1))
    if meta.get("name") != name:
        raise ValueError(f"{path}: frontmatter name {meta.get('name')!r} != {name!r}")
    return Role(name=name, system=text[m.end():].strip())


@dataclass
class RunResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


def _api_key() -> str | None:
    """Env first; else the gitignored local/anthropic-key file. Returning
    None lets the SDK try its own credential chain."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return None
    key_path = os.path.join(REPO_ROOT, "local", "anthropic-key")
    if os.path.exists(key_path):
        with open(key_path, encoding="utf-8") as f:
            return f.read().strip() or None
    return None


def _anthropic_send(model: str, system: str, prompt: str,
                    max_tokens: int) -> tuple[str, dict]:
    """The real transport: streams (large max_tokens requires it) and
    returns (text, usage-dict). Isolated so tests inject their own."""
    import anthropic

    client = anthropic.Anthropic(api_key=_api_key())
    with client.messages.stream(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = stream.get_final_message()
    text = "".join(b.text for b in message.content if b.type == "text")
    u = message.usage
    return text, {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_write_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }


class Runner:
    """Executes roles: budget check → call → meter. One per factory run."""

    def __init__(self, engine: sa.Engine, scope: db.TenantScope,
                 config: ModelsConfig | None = None, send=None,
                 roles_dir: str = ROLES_DIR):
        self.engine = engine
        self.scope = scope
        self.config = config or load_models_config()
        self.send = send or _anthropic_send
        self.roles_dir = roles_dir

    def spent(self, stage: str) -> Decimal:
        with self.engine.begin() as conn:
            value = conn.execute(self.scope.ledger_stage_cost(stage)).scalar_one()
        return Decimal(value)

    def run_role(self, role_name: str, prompt: str,
                 max_tokens: int = 32000) -> RunResult:
        role = load_role(role_name, self.roles_dir)
        model = self.config.model_for_role(role_name)
        budget = self.config.budget_for_stage(role_name)
        already = self.spent(role_name)
        if already >= budget:
            raise BudgetExceeded(
                f"stage {role_name!r} has spent ${already:.2f} of its "
                f"${budget:.2f} budget — raise it in models.yaml deliberately")

        text, usage = self.send(model, role.system, prompt, max_tokens)

        cost = self.config.cost(
            model, usage["input_tokens"], usage["output_tokens"],
            usage.get("cache_write_tokens", 0), usage.get("cache_read_tokens", 0))
        with self.engine.begin() as conn:
            conn.execute(self.scope.ledger_insert(
                stage=role_name, model=model,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cache_write_tokens=usage.get("cache_write_tokens", 0),
                cache_read_tokens=usage.get("cache_read_tokens", 0),
                cost_usd=cost))
        return RunResult(text=text, model=model,
                         input_tokens=usage["input_tokens"],
                         output_tokens=usage["output_tokens"], cost_usd=cost)
