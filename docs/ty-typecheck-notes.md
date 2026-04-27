# Ty Type Check Notes

## Quick Reference

When `ty check` reports many warnings, do not read them as a flat list first.
Use this quick triage flow:

### Step 1: Group By File

Ask:

- are most warnings concentrated in 1 to 5 files?
- do many lines repeat the same warning family?

If yes, the real problem is probably a small number of root causes.

### Step 2: Identify The Warning Pattern

Use this mapping:

- `possibly-unresolved-reference`
  Usually means a variable is only defined in one branch and used later elsewhere.
- `unresolved-attribute`
  Usually means a value may be `None`, but code accesses `.id`, `.title`, or another attribute directly.
- `invalid-argument-type`
  Usually means a value was typed too broadly, often as `object`.
- `invalid-return-type`
  Usually means an internal temporary structure lost precise typing before being returned.
- `call-non-callable`
  Usually means runtime duck typing is fine, but static typing still sees `object`.
- `no-matching-overload`
  Usually means a third-party SDK expects a more precise type than the local code provides.

### Step 3: Fix The Root Cause, Not Each Line

Prefer:

- one early variable initialization over six repeated guard failures
- one `None` guard over multiple attribute warnings
- one `TypedDict` over many `object`-based warnings
- one local boundary cast over redesigning the whole application immediately

### Step 4: Choose The Lowest-Risk Fix

Start with these, in order:

1. initialize variables with safe defaults
2. add explicit `None` checks
3. replace `object`-like temporary data with a structured type
4. narrow types at library boundaries
5. only then consider larger DTO or interface refactors

### Common Fix Templates

Variable maybe undefined:

```python
client = None
key: str | None = None
```

Then:

```python
if client is not None and key is not None:
    ...
```

Value may be `None`:

```python
if session is None:
    raise ServiceError("session not found")
```

Temporary dict too broad:

```python
class Item(TypedDict):
    chunk: DocumentChunk
    score: float
```

Runtime duck typing:

```python
if hasattr(document, "export_to_text"):
    return cast(TextExportable, document).export_to_text()
```

Third-party overload mismatch:

```python
messages = cast(list[ChatCompletionMessageParam], raw_messages)
```

### When Not To Rush

Pause before changing types globally if the fix would require:

- changing a widely used DTO
- redesigning service interfaces
- rewriting many callers
- changing runtime behavior just to satisfy typing

In those cases, first ask whether a local narrowing at the boundary is enough.

### Rule Of Thumb

If 20 warnings disappear after 2 or 3 small structural fixes, the report was healthy.
It means the checker found unclear contracts, not necessarily broken business logic.

This document summarizes the type-check fixes made during a `ty check` cleanup pass.
It is written as a study note for future maintenance, not just as a changelog.

## Goal

The goal of this pass was:

- fix low-risk type-check issues
- avoid broad refactors
- improve type clarity without changing business behavior
- leave behind repeatable patterns for future fixes

At the time of the cleanup, `ty check` reported 33 diagnostics, but they were concentrated in a small number of files because many warnings came from the same root cause repeated across several lines.

## Why Many Diagnostics Came From Few Files

Type checkers often emit one warning per use site, not one warning per root cause.

Examples:

- If `redis` is maybe undefined, every later `redis.delete(...)` and `redis.set(...)` can trigger a separate warning.
- If a dictionary is typed as `dict[str, object]`, every read such as `item["score"]` or `item["chunk"]` can trigger a separate warning.
- If a value may be `None`, every attribute access like `session.id` and `session.title` can trigger its own warning.

So 30+ diagnostics does not necessarily mean 30+ unrelated bugs.

## Files Involved

Most diagnostics were concentrated in these files:

- [`backend/ai/providers/llm/llm_service.py`](../backend/ai/providers/llm/llm_service.py)
- [`backend/services/vector_index_service.py`](../backend/services/vector_index_service.py)
- [`backend/workflow/chat_nonstream_workflow.py`](../backend/workflow/chat_nonstream_workflow.py)
- [`backend/workflow/chat_workflow.py`](../backend/workflow/chat_workflow.py)
- [`backend/workflow/knowledge_rag_workflow.py`](../backend/workflow/knowledge_rag_workflow.py)

## Pattern 1: Variables Defined Only Inside a Branch

### Symptom

Warnings like:

- `possibly-unresolved-reference`
- "`redis` used when possibly not defined"
- "`lock_key` used when possibly not defined"

This happened in:

- [`backend/workflow/chat_nonstream_workflow.py`](../backend/workflow/chat_nonstream_workflow.py)
- [`backend/workflow/chat_workflow.py`](../backend/workflow/chat_workflow.py)

### Original Problem

The code only assigned `redis` and `lock_key` inside:

```python
if client_request_id:
    redis = await redis_client.init()
    lock_key = ...
```

Later, multiple error-handling paths used those names.

From a runtime perspective, the logic was mostly fine because those branches were intended to run only when `client_request_id` existed.
From a type-checking perspective, the names were not guaranteed to exist in the whole function scope.

### Fix

Initialize them before the branch:

```python
redis = None
lock_key: str | None = None
```

Then guard usage precisely:

```python
if redis is not None and lock_key is not None:
    await redis.delete(lock_key)
```

### Why This Fix

This approach is better than relying on:

```python
if client_request_id:
```

because the type checker reasons about variable binding and nullability, not about the developer's intention.

This fix is low-risk because:

- it does not change the main business flow
- it makes the control flow explicit
- it improves both static safety and readability

### Reusable Rule

If a variable is created only in one branch but used later in the function, define it early with a safe default.

Good candidates:

- clients
- locks
- cache handles
- optional repo results
- temporary resources used in `except` or `finally`

## Pattern 2: Accessing Attributes on a Value That May Be `None`

### Symptom

Warnings like:

- `unresolved-attribute`
- "`session.id` may be accessed on `None`"

This happened in:

- [`backend/workflow/chat_nonstream_workflow.py`](../backend/workflow/chat_nonstream_workflow.py)

### Original Problem

The repository call could return `None`:

```python
session = await self.uow.chat_repo.get_session(msg.session_id)
return ChatQueryResponse(
    session_id=session.id,
    session_title=session.title,
    ...
)
```

Even if the application expects the session to exist, the type checker correctly sees that the function signature allows `None`.

### Fix

Add an explicit guard:

```python
if session is None:
    raise ServiceError("会话不存在")
```

### Why This Fix

This is not just to satisfy the type checker.
It is also a real runtime hardening improvement.

If the database is inconsistent or the session was removed, the code now fails explicitly instead of crashing with an attribute error.

### Reusable Rule

When a repository/service method returns `T | None`, do not treat it as always present unless you explicitly narrow it first.

Typical narrowing forms:

- `if value is None: raise ...`
- `if value is None: return ...`
- `assert value is not None` only when the invariant is truly internal and guaranteed

Prefer a real guard over `assert` in request-handling code.

## Pattern 3: Dictionaries Typed Too Broadly

### Symptom

Warnings like:

- `invalid-argument-type`
- `invalid-return-type`

This happened in:

- [`backend/services/vector_index_service.py`](../backend/services/vector_index_service.py)

### Original Problem

The fusion dictionary was typed too loosely:

```python
fused: dict[str, dict[str, object]] = {}
```

That makes:

- `item["score"]` become `object`
- `item["chunk"]` become `object`

Once that happens, every numeric operation and typed return value becomes suspicious.

### Fix

Define a typed structure:

```python
class _HybridHit(TypedDict):
    chunk: DocumentChunk
    score: float
```

Then use:

```python
fused: dict[str, _HybridHit] = {}
```

### Why This Fix

This is the cleanest local fix because it preserves the existing data shape while making the shape explicit.

Alternative options could have been:

- introducing a dataclass
- changing the algorithm to use tuples
- adding repeated casts everywhere

`TypedDict` was the best fit here because:

- the code already used dictionary-shaped temporary state
- the change stays local
- it eliminates multiple downstream warnings at once

### Reusable Rule

If you see temporary dictionaries with known keys and values, avoid `dict[str, object]`.

Prefer:

- `TypedDict` for dictionary-shaped state
- `dataclass` for richer local objects
- a small model/class if the structure is reused broadly

## Pattern 4: Runtime Duck Typing Needs Static Type Hints

### Symptom

Warnings like:

- `call-non-callable`

This happened in:

- [`backend/workflow/knowledge_rag_workflow.py`](../backend/workflow/knowledge_rag_workflow.py)

### Original Problem

The code accepted `document: object` and then used runtime checks:

```python
if hasattr(document, "export_to_markdown"):
    return document.export_to_markdown()
```

This works at runtime, but static analysis still sees `document` as `object`.
`hasattr(...)` alone is often not enough for strict type narrowing in Python type systems.

### Fix

Use small `Protocol`s plus `cast`:

```python
class _DoclingMarkdownExportable(Protocol):
    def export_to_markdown(self) -> str: ...

class _DoclingTextExportable(Protocol):
    def export_to_text(self) -> str: ...
```

Then:

```python
if hasattr(document, "export_to_markdown"):
    return cast(_DoclingMarkdownExportable, document).export_to_markdown()
```

### Why This Fix

This keeps the runtime behavior unchanged while expressing the minimum callable interface needed at that point.

It is a good compromise when:

- the third-party object type is not easily imported
- the concrete type is complex or unstable
- only one or two methods are needed

### Reusable Rule

When code relies on duck typing:

- runtime checks like `hasattr(...)` are good for behavior
- `Protocol` or `cast` is often needed for static typing

Use the smallest possible interface that matches what you actually call.

## Pattern 5: Third-Party SDK Overloads Need Narrower Input Types

### Symptom

Warnings like:

- `no-matching-overload`

This happened in:

- [`backend/ai/providers/llm/llm_service.py`](../backend/ai/providers/llm/llm_service.py)

### Original Problem

The OpenAI SDK expects `messages` to match a specific typed schema such as `ChatCompletionMessageParam`.
But the local DTO exposed:

```python
conversation_history: list[dict]
```

That is too broad for overload matching.

### Fix

Narrow the local helper method:

```python
def _build_messages(query: LLMQueryDTO) -> list[ChatCompletionMessageParam]:
```

and cast the already-built history when present:

```python
return cast(list[ChatCompletionMessageParam], query.conversation_history)
```

### Why This Fix

This was intentionally a local fix rather than a full DTO redesign.

A broader redesign would mean:

- tightening `LLMQueryDTO`
- updating prompt assembly outputs
- aligning all producer and consumer types across the workflow stack

That may be worth doing later, but it is a larger refactor.
For this pass, a local narrowing was the right tradeoff:

- low blast radius
- enough to satisfy the SDK overload
- no behavior change

### Reusable Rule

When a library has rich overloads, generic types like `list[dict]` are often too vague.

Fix strategy:

1. narrow the value at the boundary where the library is called
2. only redesign upstream DTOs if that pattern spreads widely

## What Was Intentionally Avoided

This cleanup intentionally did not use `# type: ignore` as the default solution.

Reason:

- it hides the warning without improving the code model
- it makes future refactors harder
- it can mask real bugs

This pass also avoided broad architectural changes.

Reason:

- the stated goal was to fix simple issues first
- local type narrowing is safer when business behavior must remain stable

## General Heuristics For Future `ty` Cleanup

When reading a `ty` report, use this order:

1. group diagnostics by file
2. identify repeated wording
3. find the shared root cause
4. prefer one structural fix over many local suppressions

Useful questions:

- Is this variable maybe undefined?
- Is this value maybe `None`?
- Is this dictionary typed too broadly?
- Is this third-party API expecting a more precise type?
- Is the checker missing a runtime invariant that I should state explicitly?

## Preferred Fix Order

In this repository, a practical order is:

1. initialize maybe-defined variables
2. add explicit `None` guards
3. replace `object` or broad dicts with `TypedDict` / `Protocol` / specific types
4. narrow values at third-party boundaries
5. only then consider wider DTO refactors

This order tends to maximize signal while minimizing risk.

## Result

After these changes:

```bash
ty check
```

returned:

```text
All checks passed!
```

## Takeaway

Most static type issues in application code are not about the type checker being picky.
They usually reveal one of these facts:

- the control flow is less explicit than it should be
- the nullability contract is not documented in code
- a temporary data structure is too weakly typed
- a library boundary expects more precision than the local code provides

If you fix the code so that those facts are explicit, the warnings usually disappear naturally.
