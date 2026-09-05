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

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def home() -> str:
    """Where `models.yaml` and `roles/` live.

    They sit at the checkout root rather than inside the package on purpose:
    they are operator-editable configuration, not library data. You change a
    price or reword a role contract by editing a file you can see, and a copy
    buried in site-packages is the opposite of that. Which does mean the
    factory is a checkout-mode feature — `pip install curricle` gets you the
    compiler, the renderers, and the web app, but the factory needs the files.

    `CURRICLE_HOME` overrides, for an installed copy that keeps its
    configuration somewhere deliberate. Resolved per call rather than pinned
    at import, so setting it late still works.
    """
    from .coursehome import checkout_home
    return checkout_home()


def models_path() -> str:
    return os.path.join(home(), "models.yaml")


def roles_dir() -> str:
    return os.path.join(home(), "roles")


class BudgetExceeded(RuntimeError):
    pass


class NoApiKey(RuntimeError):
    """The SDK found no credential at all, anywhere it looks.

    Its own exception for the same reason `BudgetExceeded` is one: the
    worker turns it into a failure reason the wizard has a sentence for, and
    a stranger's first run of a fresh checkout is far more likely to end
    here than anywhere else.

    Raised only by translating the SDK's own refusal, never by a check of
    our own beforehand — the chain that resolves a credential is the SDK's
    (an API key, an auth token, a profile, workload identity), and a
    pre-flight gate over the two places *this* repo knows about would fail
    people whose credential comes from one of the others.
    """


class BadApiKey(RuntimeError):
    """A credential was found, sent, and refused by the API.

    Distinct from `NoApiKey` because the instruction to the learner is
    different: not "put a key somewhere" but "the one you have is not
    accepted — replace it". Told apart on the SDK's own error class, so
    nothing here reads a 401 body or the credential inside it.
    """


class FactoryConfigMissing(RuntimeError):
    """`models.yaml` or a role contract is not where the factory looked.

    Its own exception because the usual cause is structural rather than a
    typo — an installed copy with no checkout beside it — and a bare
    `FileNotFoundError` out of `yaml.safe_load` sends people looking for the
    wrong bug.
    """

    @staticmethod
    def for_path(path: str, what: str) -> FactoryConfigMissing:
        return FactoryConfigMissing(
            f"{what} not found at {path}. The factory reads its configuration "
            f"from the checkout root (currently {home()!r}); an installed "
            f"curricle has no such files. Run the factory from a clone, or "
            f"point CURRICLE_HOME at a directory holding models.yaml and "
            f"roles/.")


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


def load_models_config(path: str | None = None) -> ModelsConfig:
    path = path or models_path()
    if not os.path.isfile(path):
        raise FactoryConfigMissing.for_path(path, "models.yaml")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ModelsConfig(tiers=data["tiers"], prices=data["prices"],
                        roles=data["roles"], budgets=data["budgets"])


@dataclass(frozen=True)
class Role:
    name: str
    system: str


def load_role(name: str, roles: str | None = None) -> Role:
    path = os.path.join(roles or roles_dir(), f"{name}.md")
    if not os.path.isfile(path):
        raise FactoryConfigMissing.for_path(path, f"the {name!r} role contract")
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
    None lets the SDK try its own credential chain — which is wider than
    these two places (an auth token, a profile, workload identity), and is
    why nothing here decides in advance that there is no credential."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return None
    key_path = os.path.join(REPO_ROOT, "local", "anthropic-key")
    if os.path.exists(key_path):
        with open(key_path, encoding="utf-8") as f:
            return f.read().strip() or None
    return None


# How the SDK opens its complaint when its whole credential chain came up
# empty ("Could not resolve authentication method. Expected one of api_key,
# auth_token, or credentials to be set…"). The rest of the sentence names
# the arguments it wanted and has changed between SDK versions; the opening
# has not, and a prefix is what a version bump is least likely to break.
# If it ever does, the failure is a `worker_error` again — honest, and the
# thing to fix here.
NO_CREDENTIAL_PREFIX = "Could not resolve authentication method"


def _anthropic_send(model: str, system: str, prompt: str,
                    max_tokens: int) -> tuple[str, dict]:
    """The real transport: streams (large max_tokens requires it) and
    returns (text, usage-dict). Isolated so tests inject their own.

    The two credential failures are translated here, and only here, into
    exceptions the worker can word for a learner (`no_api_key`,
    `bad_api_key`). Both are told apart the way the SDK reports them —
    nothing pre-empts the SDK's credential chain, and nothing reads the
    credential or the 401's body. The client constructs happily with no
    credential at all; the complaint comes at request time.
    """
    import anthropic

    try:
        client = anthropic.Anthropic(api_key=_api_key())
        with client.messages.stream(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        # A credential was sent and refused: a typo, a revoked key, the
        # wrong organisation. Its own fixed detail — the SDK's message is
        # the 401's body, which is an operator's to read in a log.
        raise BadApiKey("the Anthropic API refused this credential") from exc
    except TypeError as exc:
        # The SDK's "no credential anywhere" refusal, which it raises as a
        # bare TypeError at request time. The class alone is far too broad
        # to classify on — every ordinary bug in this call would arrive as
        # one — so the message's fixed prefix has to match too, and anything
        # else is re-raised as the bug it is.
        if not str(exc).startswith(NO_CREDENTIAL_PREFIX):
            raise
        raise NoApiKey(
            "the Anthropic SDK found no credential: set ANTHROPIC_API_KEY, "
            "or put a key in local/anthropic-key beside the checkout") from exc
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
                 roles: str | None = None):
        self.engine = engine
        self.scope = scope
        self.config = config or load_models_config()
        self.send = send or _anthropic_send
        self.roles = roles or roles_dir()

    def spent(self, stage: str) -> Decimal:
        with self.engine.begin() as conn:
            value = conn.execute(self.scope.ledger_stage_cost(stage)).scalar_one()
        return Decimal(value)

    def run_role(self, role_name: str, prompt: str,
                 max_tokens: int = 32000) -> RunResult:
        role = load_role(role_name, self.roles)
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
