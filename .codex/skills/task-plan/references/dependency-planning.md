# Dependency Planning Reference

Use this reference when a task has multiple requirements, unclear ordering, several possible checkpoints, or independent workstreams that should be tracked durably.

## Labels

- `parallel`: can start immediately and does not write the same files or checkpoint state as another task.
- `depends_on: N`: should wait for task N because it needs that output or decision.
- `blocking`: must happen first because it determines scope, architecture, or the next checkpoint choice.
- `serial`: cannot safely overlap because it touches the same files, state, or shared checkpoint.

## Decomposition Heuristics

- Start from the stable task goal, not implementation layers.
- Split read-only discovery from write tasks.
- Split checkpoint alignment from implementation work when human approval is required between them.
- Keep shared contract/schema changes before dependent endpoint, service, repository, or worker work.
- Keep validation close to the workstream it proves.
- Convert approved `/plan` conclusions into durable workstreams and next choices instead of copying the whole conversation.

## Example

```md
## Workstreams
1. [blocking] Confirm task scope and update `manifest.yaml` with the current checkpoint.
2. [parallel] Capture the approved implementation path in `task-plan.md`.
3. [parallel] Attach the current review checkpoint if findings already exist.
4. [depends_on: 1,2] Start implementation once the task identity and approved path are stable.
5. [depends_on: 4] Run focused validation and update the next checkpoint choice.
```
