---
name: read
description: Read-only repository investigation and explanation for Dewflow. Use when the user asks to inspect, analyze, locate, summarize, explain, compare, or answer questions without requesting file edits, implementation, commits, or new tests.
---

# Read

Use this skill to gather evidence and answer without changing files.

## Core Flow

1. Confirm the request is read-only. If the user asks to implement, create, modify, or add tests, switch to the matching skill.
2. Read `.codex/skills/project/SKILL.md` first when architecture, test, command, or editing rules matter.
3. Use `rg`, `rg --files`, `sed -n`, `ls`, and existing docs to build the smallest useful context.
4. Ground conclusions in file paths, line numbers, command output, or user-provided evidence.
5. Stop before edits. Do not create files, run formatters, update snapshots, or use `apply_patch`.

## Progressive Disclosure

- Read [references/read-only.md](references/read-only.md) for investigation boundaries, evidence rules, and answer shape.
- Read [../project/references/task-mode.md](../project/references/task-mode.md) when the request is ambiguous between read, task-plan, write, edit, and add-tests.
