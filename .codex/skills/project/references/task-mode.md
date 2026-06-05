# Task Mode Selection

Use this reference when a request could fit more than one local skill.

## Modes

- `read`: inspect, explain, summarize, compare, diagnose, or answer without file changes.
- `task-plan`: create or update durable work-item artifacts when the task needs persistent tracking, checkpoint updates, dependency alignment, or complex multi-stage/multi-PR planning.
- `write`: create new code, docs, config, migrations, scripts, or skill assets.
- `edit`: change existing code, docs, config, migrations, scripts, or skill assets.
- `add-tests`: create or update pytest coverage.

## Ambiguity Rule

Prefer the least invasive mode that satisfies the latest user request. If implementation intent is explicit, choose `write`, `edit`, or `add-tests`; if durable task identity is required, choose `task-plan`; if a planning request looks complex but persistence is not explicit, use `task-plan` to ask whether to persist; if intent is unclear and risk is high, ask one concise question.

## Collaboration Flow

- For broad implementation planning, prefer Claude Code built-in `/plan`; use `task-plan` to persist approved conclusions and checkpoint state into `work-items/`.
- For complex方案/计划/里程碑 requests with multiple PRs, phases, dependencies, or rollout checkpoints, use `task-plan` to confirm whether the user wants durable `work-items/` tracking before producing only an in-chat plan.
- After `task-plan`, switch to the mode skill that owns the next executable step.
- After `write` or `edit`, consider `add-tests` when coverage gaps exist or behavior changed.

## agents/openai.yaml

Each skill may include `agents/openai.yaml` with `display_name`, `short_description`, and `default_prompt`. Keep these files as generated UI metadata for Codex/OpenAI agent skill lists and chips; they are not runtime backend code.
