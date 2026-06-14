# Task Mode Selection

Use this reference when a request could fit more than one local skill.

## Modes

All modes cover both backend and frontend assets; load the matching project reference (`context.md` for backend, `frontend.md` for frontend) first.

- `read`: inspect, explain, summarize, compare, diagnose, or answer without file changes.
- `task-plan`: create or update durable work-item artifacts when the task needs persistent tracking, checkpoint updates, dependency alignment, or complex multi-stage/multi-PR planning.
- `write`: create new code, docs, config, migrations, scripts, or skill assets.
- `edit`: change existing code, docs, config, migrations, scripts, or skill assets.
- `add-tests`: create or update test coverage (pytest, Vitest, Playwright).

## Ambiguity Rule

Prefer the least invasive mode that satisfies the latest user request. If implementation intent is explicit, choose `write`, `edit`, or `add-tests`; if durable work-item identity is required, choose `task-plan`; if a planning request looks complex but persistence is not explicit, use `task-plan` to ask whether to persist; if intent is unclear and risk is high, ask one concise question.

## Collaboration Flow

- For broad implementation planning, prefer Claude Code built-in `/plan`; use `task-plan` to persist approved conclusions and checkpoint state into `work-items/`.
- For complex 方案/计划/里程碑 requests with multiple PRs, phases, dependencies, or rollout checkpoints, use `task-plan` to confirm whether the user wants durable work-item tracking in `work-items/` before producing only an in-chat plan.
- After `task-plan`, switch to the mode skill that owns the next executable step.
- After `write` or `edit`, consider `add-tests` when coverage gaps exist or behavior changed.

## `agents/openai.yaml` Role

The `agents/openai.yaml` file in each skill directory only provides UI metadata (`display_name`, `short_description`, `default_prompt`) for Codex/OpenAI agent lists; it is not a runtime constraint. Claude Code does not read these files. Runtime behavior is governed by the `SKILL.md` frontmatter and body.

## Serena Security Layers

- **Source of Truth**: The `fixed_tools` in `.serena/project.yml` is the server-side hard constraint, exposing only 5 read-only tools.
- **Client Auto-Approve**: The `enabled_tools` in `.codex/config.toml` and `allow` in `.claude/settings.json` mirror this list solely to bypass confirmation dialogs.
- **Defensive Fallback**: The `deny` list in `.claude/settings.json` explicitly blocks 9 write-oriented tools. Since `fixed_tools` already prevents their exposure, this deny list has no actual trigger scenario and is kept purely as a defensive measure—in case `fixed_tools` is accidentally removed.

## Serena Fallback Strategy

On the Codex side, Serena is configured with `required = false` and silently falls back if startup times out after 60 seconds. This is intentional: in WSL or cold-start environments where Serena might start slowly, it shouldn't block the agent's main workflow. After fallback, the agent automatically reverts to plain text search (like `rg`/`grep`). Semantic navigation becomes unavailable, but core workflows are unaffected.
