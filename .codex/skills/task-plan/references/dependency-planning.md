# Dependency Planning Reference

Use this reference when a work item has multiple requirements, unclear ordering, several possible checkpoints, or independent workstreams that should be tracked durably.

## Labels

These map directly to `manifest.yaml` `workstreams[]` fields: `kind` carries the
ordering intent, `deps` lists the workstream ids a workstream waits on.

- `kind: parallel`: can run alongside other ready workstreams after all of its own `deps` are satisfied; it may use `deps: []` or wait on earlier work.
- `deps: [N]`: should wait for workstream N because it needs that output or decision.
- `kind: blocking`: must happen first because it determines scope, architecture, or the next checkpoint choice.
- `kind: serial`: cannot safely overlap because it touches the same files, state, or shared checkpoint.

Open questions and prerequisites are not ordering. Track those in
`manifest.yaml` `open_decisions`, not as workstream labels.

## Decomposition Heuristics

- Start from the stable work-item goal, not implementation layers.
- Split read-only discovery from write tasks.
- Split checkpoint alignment from implementation work when human approval is required between them.
- Keep shared contract/schema changes before dependent endpoint, service, repository, or worker work.
- Keep validation close to the workstream it proves.
- Convert approved `/plan` conclusions into durable workstreams and next choices instead of copying the whole conversation.

## Example

Keep `manifest.yaml` examples in English because they model the machine-readable
work-item state. Put Chinese narrative in `task-plan.md`.

```yaml
# manifest.yaml
workstreams:
  - id: 1
    title: Confirm task scope and align the current checkpoint.
    status: done
    kind: blocking
    deps: []
  - id: 2
    title: Capture the approved implementation path in task-plan.md.
    status: in_progress
    kind: parallel
    deps: []
  - id: 3
    title: Start implementation once scope and path are stable.
    status: pending
    kind: serial
    deps: [1, 2]
  - id: 4
    title: Run focused validation and update the next checkpoint choice.
    status: pending
    kind: serial
    deps: [3]
```
