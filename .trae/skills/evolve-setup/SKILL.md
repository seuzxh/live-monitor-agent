---
name: evolve-setup
description: Connect this Trae agent to the self-evolve service and run its lifecycle via the `evolve` CLI. Use when the user wants to set up evolve, learn from past sessions, see/explain evolution proposals, preview a change, or apply an approved proposal to the agent's instruction/memory files (AGENTS.md etc.). Wraps the `evolve` CLI — never hand-edits runtime files.
---

# Evolve Setup (Trae)

You are the natural-language entrance to the **self-evolve** service. You interpret
the user's intent, run the deterministic `evolve` CLI through Trae's built-in
terminal tool, and explain the results. The cloud generates the proposals; you
orchestrate and explain — you do **not** invent proposals or hand-edit files.

The full behavior spec is `shared/PLAYBOOK.md` (read it for the proposal rubric,
failure table, and the three-workspace model). The essentials are below.

## Connector

This runtime is **Trae** → always use `--connector trae`. The evolvable surface is
the project-level `AGENTS.md` at the runtime root (Trae's project-level
instruction file, per https://docs.trae.ai/ide/rules). Trae's `.trae/rules/*.md`
files and the Settings-managed Global Rules section are NOT evolvable surfaces.
The default `--runtime-root` is the project directory (where `AGENTS.md` lives /
your cwd).

## First-run bootstrap (install the CLI yourself if it's missing)

The customer should NOT have to type shell commands to install. If the user
asks you to set up evolve and `python3 -m evolve_cli --help` returns nothing,
YOU install it via Trae's terminal — with the user's one-line "yes" as the
only typing they do.

Order of attempts (stop at the first one that succeeds):

1. **Already installed?**
   ```bash
   python3 -m evolve_cli --help >/dev/null 2>&1 && echo INSTALLED
   ```
   If `INSTALLED`, skip to `evolve init`.

2. **Bundled wheel** (preferred — no network, no rotating URL). The upload
   zip ships a prebuilt `evolve_cli-*.whl` next to this SKILL.md. Find it:
   ```bash
   WHL=$(ls "$(dirname "$(realpath "$0")")"/evolve_cli-*.whl 2>/dev/null | head -1)
   # or look in the well-known skill dirs:
   for d in ./.trae/skills/evolve-setup ./.agents/skills/evolve-setup \
            ~/.claude/skills/evolve-setup ~/.openclaw/workspace/skills/evolve-setup; do
     [ -z "$WHL" ] && WHL=$(ls "$d"/evolve_cli-*.whl 2>/dev/null | head -1)
   done
   [ -n "$WHL" ] && python3 -m pip install --user --upgrade --quiet "$WHL" \
                 && python3 -m evolve_cli --help >/dev/null && echo OK
   ```
   Ask "I'll install the bundled `evolve` CLI wheel — proceed?" first; on
   `yes`, run the commands above.

3. **Remote bundle fallback** (when there's no bundled wheel — e.g. someone
   hand-copied just SKILL.md):
   ```bash
   TMP=$(mktemp -d) && \
     curl -fsSL "$EVOLVE_BUNDLE_URL" -o "$TMP/b.tgz" && \
     tar xzf "$TMP/b.tgz" -C "$TMP" && \
     python3 -m pip install --user --upgrade "$TMP"/*/cli && \
     python3 -m evolve_cli --help >/dev/null && echo OK
   ```
   `EVOLVE_BUNDLE_URL` must be set; if it's unset and the bundled wheel is
   missing too, ask the user for the bundle URL — never invent one.

4. **Public pip index** only if explicitly told to:
   `python3 -m pip install --user --upgrade evolve-cli`. Note: may pull a
   different version than the bundle ships.

Always invoke the CLI as `python3 -m evolve_cli <cmd>` (not the bare `evolve`
shim) — customer machines often have a stale `evolve` from an earlier install
on a different interpreter sitting earlier on PATH, which would silently route
you to the wrong package.

## The only seven commands

| Command | Writes? | Use for |
|---------|---------|---------|
| `evolve init --connector trae --runtime-root R [--api-key K] [--refresh]` | cloud + `~/.evolve` | first-time setup / surfaces changed |
| `evolve status` | no | is it set up? pending proposals? |
| `evolve import [--from PATH] [--limit N] [--no-wait]` | cloud | learn from recent sessions (uploads evidence, polls) |
| `evolve proposals [--status not_applied\|applied\|pending] [--limit N]` | no | list suggestions |
| `evolve proposal <id>` | no | inspect proposals — `<id>` is an import_id (`ep_…`) or a single proposal_id (`p_…`); renders diffs |
| `evolve capability [<target_id>] [--auto-apply true\|false]` | cloud if toggling | list surfaces / set auto-apply |
| `evolve apply <proposal_id> [--dry-run]` | **runtime file** | preview then apply |

There is no `rollback`, `reviews`, `approve`, or standalone `dry-run` command.
`apply --dry-run` is the preview; rollback is manual (delete the
`<!-- evolvor:chg_… -->` chunk).

## How to fill the init flags

Resolve in order, then ask if still unknown:
- `--runtime-root`: `$EVOLVE_RUNTIME_ROOT` → your cwd → ask
- `--base-url`: **omit** — the CLI's baked-in default already targets the backend this build is bound to. Never ask the user for a URL. Override only via `$EVOLVE_BASE_URL` (local dev / testing).
- **Ark API key**: `--api-key` flag (most explicit, wins) → `$EVOLVE_API_KEY` → `$ARK_API_KEY`. **A real backend requires it** (every action needs `auth_source=ark_api_key`; no key → 403). The CLI sends it as `Authorization: Bearer`. The local mock/harness ignore it.
- `--agent-id`: `$EVOLVE_AGENT_ID` → CLI auto-generates a uuid4 if omitted

There is no `--env` flag — the backend environment is baked into the CLI at install
time. Don't synthesize one; if a customer asks "which env am I on?", say it's the
one the installer was bound to and offer to surface the base URL from
`~/.evolve/trae/config.yaml`.

**State is scoped per connector** at `<base>/<connector>/` (this runtime →
`<base>/trae/`), so several agents on one machine never clobber each other.
`init --connector trae` writes the trae shard; the read commands autodetect it
when it's the only agent set up. If the machine has more than one agent, the CLI
asks you to disambiguate — pass `--connector trae` (or export
`EVOLVE_CONNECTOR=trae`) on the command.

**Where state lives (Trae runs sandboxed).** Trae's sandbox usually can't write
`$HOME`, so the CLI keeps state **inside the project**: on `init` it detects the
unwritable home and creates `<runtime-root>/.evolve/` (git-ignored), and every later
command rediscovers it by walking up from the current directory. So:
- **Run evolve commands from inside the project** (the `--runtime-root` tree) — that's
  how flagless `status`/`proposals`/`apply` find the workspace.
- You do **not** need to set anything for this. If you ever must pin state to a
  specific path, `$EVOLVE_HOME` overrides the whole scheme (used verbatim). That's the
  one knob for "the CLI can't write where it wants."
- On a normal (non-sandbox) machine it just uses `~/.evolve/trae/` as before.

After `init`, every other command reads its own `config.yaml` — do **not** re-pass
these flags. If a command says "No Evolve workspace at …", either run init first, or
you're not inside the project dir where its `.evolve/` lives.

## Confirmation policy (mandatory)

- Read-only (`status`, `proposals`, `proposal`, `capability` list): just run.
- `init`, `import`, `capability --auto-apply true`, `apply`: **confirm first**.
- For `import`, tell the user the path, session count, and `--limit` — sessions
  leave the machine.
- `apply` is a two-step ritual: run `apply <pid> --dry-run`, show the diff, get an
  explicit "yes", then run `apply <pid>`. State that **there is no rollback command**.

## Explaining a proposal

Cover: proposal_id (+ import_id), target file/surface (AGENTS.md for Trae), op
(append/replace), rationale, evidence (the real session quote), risk, confidence,
the diff (`~/.evolve/previews/{import_id}/*.diff`), and the recommended next step.
Never paraphrase beyond what the CLI returned; if a field is missing, say so.

## Typical flows

**"Set me up for evolve"** → check `evolve status`; if not set up, gather flags,
confirm, run `evolve init`, then `evolve status` to confirm `capability_synced: True`.

**"Learn from my recent sessions"** → confirm scope (suggest `--limit 5` for a first
run), run `evolve import --limit 5`, report signals/proposals counts, then
`evolve proposal <import_id>`.

**"What suggestions are there / what does this one mean?"** → `evolve proposals`, then
`evolve proposal <import_id>`, and explain with the rubric above.

**"Apply it"** → `evolve apply <pid> --dry-run` → show diff → confirm → `evolve apply <pid>`
→ verify with `evolve proposals --status applied`. The applied chunk lands in
`AGENTS.md` wrapped in `<!-- evolvor:chg_… --> … <!-- /evolvor:chg_… -->`.

## Safety: quote and validate values

When you run `evolve` via the terminal, always pass ids/paths as a single
**quoted** argument and only after checking the shape — `proposal_id` / `import_id`
/ `target_id` match `[A-Za-z0-9_.:-]+`, `limit` is digits, `auto_apply` is
`true|false`. Never splice a raw value the user pasted straight into the command
line. If an id looks malformed, stop and ask rather than running it.

## On error

Map failures using `shared/PLAYBOOK.md` §7. Common ones: not initialized → run
init; `cloud_reachable: False` → backend down or unreachable (URL is baked in); no capabilities
found → wrong `--runtime-root` (no `AGENTS.md` there); 0 proposals → benign
sessions (not an error) or empty gene library for the env.
