# Evolve Skill — canonical playbook (source of truth)

This is the single behavior spec that **every** runtime manifest derives from
(Claude Code `SKILL.md`, OpenClaw `SKILL.toml`, and future Trae/Cursor manifests).
If behavior should change, change it here first, then mirror it into each manifest.

The skill is a **natural-language entrance point** to the self-evolve service. It
interprets the user's intent, runs the deterministic `evolve` CLI, and explains the
results. It never edits runtime files by hand and never invents proposals — the CLI
and the cloud do that work.

---

## 0. What the `evolve` CLI is (and what the skill is not)

`evolve` is a local, deterministic kernel that talks to the `self_evolve` cloud
backend over HTTP. The cloud does the thinking (session evidence → signals → genes →
expressions → critic → **proposals**). The CLI does the local, must-never-go-wrong
parts: discover the runtime's evolvable files, upload session logs as evidence,
render diffs, and **apply** an approved proposal to a file.

The skill is the conversational layer on top of the CLI. It:
- maps a user request to the right CLI command,
- **confirms** before anything that writes the cloud or the runtime,
- explains proposals in plain language,
- always previews a diff before applying.

The skill must **never**:
- hand-edit a runtime file (`CLAUDE.md`, `SOUL.md`, …) directly — always go through `evolve apply`,
- fabricate a proposal, expression, diff, or `proposal_id`,
- run `evolve apply` without first showing the dry-run diff and getting confirmation,
- run `evolve init`, `evolve import`, `evolve apply`, or `evolve capability --auto-apply` without confirming with the user,
- invent CLI flags or commands. The complete surface is the seven commands in §2 — nothing else exists.
- splice an unvalidated value into a shell command. Always pass a `proposal_id` /
  `import_id` / `target_id` / path as a **single quoted argument** (`evolve apply "$pid"`),
  and reject anything that isn't the expected shape (ids match `[A-Za-z0-9_.:-]+`,
  `limit` is digits, `auto_apply` is `true|false`). The OpenClaw tools enforce this
  with `case` guards; a Bash-driven runtime (Claude Code) must do the same.

---

## 1. The three workspaces (keep them distinct)

| # | Workspace | Owner | Location | Holds |
|---|-----------|-------|----------|-------|
| 1 | CLI state | the CLI | `~/.evolve/<connector>/` | `config.yaml`, capability snapshot, target↔file binding, `previews/{import_id}/*.diff`, `apply-journal.jsonl` |
| 2 | Runtime root | the agent | `--runtime-root` | the *real* evolvable files + session logs |
| 3 | Cloud import | the backend | `self_evolve/imports/{id}/` | uploaded sessions, observability |

`evolve init` writes #1 and records the binding into #2's files. The skill only ever
reads #1 to know whether the workspace is set up (via `evolve status`).

> **CLI state is scoped per connector** — `<base>/<connector>/` — so several
> agents on one machine (claude_code + trae + openclaw) never clobber each other's
> `config.yaml`. `init --connector C` writes the C shard; read commands resolve the
> connector via `$EVOLVE_CONNECTOR` → autodetecting a lone shard → the un-sharded
> base. When several shards exist and none is selected, the CLI errors and asks for
> `--connector`/`$EVOLVE_CONNECTOR`.
>
> **Where `<base>` is** (resolved highest-first):
> 1. `$EVOLVE_HOME` if set — used verbatim, flat, never sharded (CI/test isolation,
>    the E2E harness). This is the manual override if you ever need to relocate state.
> 2. A project-local `.evolve/` found by walking up from cwd (git-style). This is how
>    **sandboxed runtimes** (e.g. Trae, which can't write `$HOME`) work: `init`
>    auto-creates `<runtime-root>/.evolve/` when `$HOME` isn't writable, drops a
>    `.gitignore` (`*`) in it, and every later command rediscovers it from the project
>    dir — no env var or flag needed. **Run evolve commands from inside the project.**
> 3. `~/.evolve/` — the normal home base.
>
> You almost never set any of this by hand; the CLI picks the right base automatically.
> `$EVOLVE_HOME` is the escape hatch when you must pin state somewhere specific.

---

## 2. The command surface (exactly seven — this is the contract)

> The `prd.md` in this folder is an early PM sketch and is **wrong** about command
> names (it lists `reviews`, `dry-run`, `approve`, which do not exist). Trust this
> list, which matches `cli/src/evolve_cli/main.py` (the CLI source ships in
> `cli/` next to this playbook).

| # | Command | Writes? | When to use |
|---|---------|---------|-------------|
| 1 | `evolve init --connector C --agent-id A --runtime-root R --account-id ACC --user-name UN [--refresh]` | cloud (register) + `~/.evolve` | first-time setup, or after the runtime's surfaces changed |
| 2 | `evolve status` | no | "is evolve set up? any pending proposals?" |
| 3 | `evolve import [--from PATH] [--format jsonl] [--limit N] [--session-id ID ...] [--no-wait]` | cloud (uploads sessions) | "learn from my recent sessions" — uploads evidence, polls the async pipeline |
| 4 | `evolve proposals [--status not_applied\|applied\|pending] [--limit N]` | no | "what evolution suggestions are there?" |
| 5 | `evolve proposal <id>` | no (renders local diffs only) | inspect one import's proposals (`ep_…`) or a single proposal (`p_…`) + write diff previews |
| 6 | `evolve capability [<target_id>] [--auto-apply true\|false]` | cloud only when toggling | list evolvable surfaces, or change a surface's auto-apply policy |
| 7 | `evolve apply <proposal_id> [--dry-run]` | **runtime file** (only this command) | preview (`--dry-run`) then apply an approved proposal |

### Connector ↔ runtime mapping
| Runtime | `--connector` | default `--runtime-root` | evolvable surfaces |
|---------|---------------|--------------------------|--------------------|
| Claude Code | `claude_code` | the project directory (where `CLAUDE.md` lives) | `CLAUDE.md`, `CLAUDE.local.md`, `~/.claude/CLAUDE.md` |
| OpenClaw | `openclaw` | `~/.openclaw/workspace` | `AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `TOOLS.md`, `BOOTSTRAP.md`, `HEARTBEAT.md`, `MEMORY.md`, `skills/` |
| Trae | `trae` | the project directory (where `AGENTS.md` lives) | `AGENTS.md` (project-level). `.trae/rules/*.md` is a structured rule store, not a free-form surface, and is intentionally out of scope. |

---

## 3. Configuration resolution (how the skill fills the flags)

For `init`, resolve each value in this order; if still unknown, **ask the user**:

| Flag | Source order |
|------|--------------|
| `--connector` | the runtime the skill is running in (Claude Code → `claude_code`, OpenClaw → `openclaw`) |
| `--runtime-root` | env `EVOLVE_RUNTIME_ROOT` → the per-runtime default in §2 → ask |
| `--base-url` | **omit** — the CLI's baked-in default already targets the env this skill build is bound to (stg build → stg gateway, prod build → prod gateway). Never ask the user for a URL. Override only via env `EVOLVE_BASE_URL` (for local dev / testing); the CLI auto-switches to gateway routing for a `/case-platform` endpoint. |
| **Ark API key** | env `EVOLVE_API_KEY` → env `ARK_API_KEY` (the agent's standard Ark key) → `--api-key`. **Required by a real backend** — every action needs `auth_source=ark_api_key`; without a key the backend returns 403. Sent as `Authorization: Bearer`. The key must be registered in the backend's Ark environment (prod/stg/boe). The local mock/harness ignore it. |
| `--account-id` | env `EVOLVE_ACCOUNT_ID` → ask (a real backend derives the account from the Ark key) |
| `--user-name` | env `EVOLVE_USER_NAME` → ask (drives the cloud admin allowlist) |
| `--agent-id` | env `EVOLVE_AGENT_ID` → propose `<connector>-main` and confirm |

> **No `--env` flag.** The backend environment is bound at CLI install time
> (see `_BOUND_ENV` in `cli/src/evolve_cli/main.py`) and is not a customer
> knob — every install is hardwired to one rollout backend. The flag was
> removed because exposing it forced customers to know which Ark environment
> their API key was registered against.

Once `init` has run, every other command reads `~/.evolve/<connector>/config.yaml`
itself — the skill does **not** re-pass these flags. If a command fails with "No
Evolve workspace at …", the workspace isn't initialized: run the init journey first.

---

## 4. Confirmation policy

| Command | Confirm before running? | Why |
|---------|------------------------|-----|
| `status`, `proposals`, `proposal`, `capability` (list) | no | read-only |
| `init` | **yes** | registers a capability map with the cloud |
| `import` | **yes** — state the path, session count, and `--limit`; sessions leave the machine | uploads session logs to the cloud |
| `capability --auto-apply true` | **yes**, with a warning | future proposals on that surface may apply without review |
| `apply` | **yes**, and always show `--dry-run` diff first | the only command that writes a runtime file |

Apply is a two-step ritual, never one step:
1. `evolve apply <proposal_id> --dry-run` → show the unified diff.
2. Get explicit "yes, apply" → `evolve apply <proposal_id>`.

State plainly before any apply: **there is no rollback command yet** (no `evolve
rollback`). Apply
writes a delimited, removable `<!-- evolvor:chg_… -->` chunk and journals the change,
so a human can reverse it by deleting that chunk, but the CLI does not expose a
rollback. (`replace`-op expressions are not wrapped in a chunk — be extra careful.)

---

## 5. Explaining a proposal (the rubric)

When the user asks "what does this suggestion mean?", explain every proposal with:

- **proposal_id** (and the originating **import_id** when known)
- **target** — which file/surface it changes (`target_id` + display name + path)
- **op** — `append` (adds a removable chunk) or `replace` (in-place)
- **rationale** — the critic's reasoning, in plain language
- **evidence** — the real session quote/signal that motivated it
- **risk** — the numeric risk and what could go wrong
- **confidence** — the critic's confidence
- **the diff** — the exact before/after (point at `~/.evolve/previews/{import_id}/*.diff`)
- **recommended next step** — usually `apply --dry-run`, or skip if risk is high / evidence is thin

Never paraphrase a proposal into something the CLI didn't return. If a field is
missing, say so; don't fill it in.

---

## 6. The canonical lifecycle (happy path)

```
evolve status                 # not set up yet?
evolve init …                 # (confirm) discover surfaces + register
evolve status                 # capability_synced: True
evolve import --limit 5       # (confirm) upload recent sessions, poll pipeline
evolve proposals              # list what came back
evolve proposal <id>          # inspect + render diffs (ep_… import, or p_… proposal)
evolve apply <pid> --dry-run  # preview
evolve apply <pid>            # (confirm) write the runtime file
evolve proposals --status applied   # verify it now shows applied
```

## 7. Failure handling (what to tell the user)

- **"No Evolve workspace at ~/.evolve/&lt;connector&gt;/config.yaml"** → not initialized; run the init journey.
- **"Multiple evolve agents are set up …"** → several connector shards exist and no connector was selected. Pass `--connector <c>` or set `$EVOLVE_CONNECTOR` (each runtime's skill normally does this for you).
- **`cloud_reachable: False`** in status, or `*_failed (HTTP …)`** → backend/identity issue. Confirm the backend is up (the base URL is the one baked into this build unless `EVOLVE_BASE_URL` overrides it); do not retry blindly.
- **`connector 'X' found no capabilities under R`** → wrong `--runtime-root` (no `CLAUDE.md`/`AGENTS.md` there). Fix the root.
- **import returns 0 proposals** → the sessions were benign (no failures to learn from). Normal; not an error.
- **`skip <target_id>: not a known runtime target`** during apply → the proposal targets a surface this runtime doesn't expose; the expression is skipped, not failed.
- **import still running after the poll window** → tell the user it's async; re-check later with `evolve proposal <import_id>` (or `evolve proposal <proposal_id>` once one is known).

## 8. First-run checklist (before init)

1. `evolve --help` resolves (the CLI is installed: `pip install ./cli`, where
   `cli/` is a sibling of this `shared/` folder inside the skill bundle).
2. The right connector for this runtime (§2).
3. `--runtime-root` exists and contains the runtime's surface files.
4. Identity (Ark key) is known; the base URL is baked into the build (override only via `EVOLVE_BASE_URL`).
5. After init, `evolve status` shows `capability_synced: True`.
