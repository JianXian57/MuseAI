---
name: task-management
description: Use for MuseAI Daily, Long, and Standing Task management: create/update tasks, manage status/archive/recurrence, handle Task relationships, and orchestrate Standing-to-Daily generation and recovery through the public Task CLI.
---

# MuseAI Task Management Skill

## Purpose

This Skill teaches Main how to interpret and orchestrate MuseAI Daily, Long, and Standing Tasks.

Use it for runtime requests involving:

- Daily Task creation, modification, status, or removal;
- Long Task creation, progress, state, deadline, archive, or restoration;
- Standing Task recurrence management;
- Daily ↔ Long relationships;
- Standing → Daily generation;
- Standing → Daily → Long relationships;
- recovery from interrupted Standing generation.

This Skill does not implement deterministic Task behavior.

Runtime mutations must still use the public Task interface:

`.\muse.cmd task ...`

The current Task CLI and Tool source are authoritative for exact command names, options, validation, and error codes.

## General Task Principles

### Tool Ownership

Use public Task Tools for deterministic runtime work.

Do not directly edit Task JSON to reproduce behavior already owned by the Task Tool.

Internal Services are implementation details during normal runtime.

### Preserve User Intent

Preserve explicit user-provided:

- Task IDs;
- dates;
- titles;
- descriptions;
- categories;
- relationships;
- completion intent;
- active/inactive intent;
- archive intent;
- deadline intent;
- recurrence schedules;
- enabled/disabled intent.

Do not infer a Task relationship from similar titles alone.

Do not invent deadlines, stages, recurrence dates, or completion state.

### Relationship Meaning

Task relationships are independent concepts.

A Daily Task may be related to:

- one Long Task through `long_task_id`;
- one Standing Task occurrence through `standing_task_id`.

A Standing Task may itself be related to a Long Task.

A generated Daily occurrence can therefore simultaneously represent:

- its Standing recurrence origin;
- its Long Task relationship.

Do not collapse these meanings into one field.

### Tool Results

Inspect every Tool Result before performing dependent operations.

If a prerequisite operation fails, do not continue as if it succeeded.

Treat idempotent success states explicitly described below as successful recovery, not as errors.

## Daily Task

### File Initialization

Daily add intentionally requires the target Daily file to exist.

When adding a Daily Task and the file may not exist:

1. ensure the target Daily file;
2. add the Daily Task.

This prerequisite does not require a separate user confirmation.

Do not create a Daily file merely to satisfy a read-only request.

### Daily ID Date

Daily IDs use the form:

`DYYYYMMDD-NNN`

When a user gives an explicit Daily Task ID and no conflicting date, use the date encoded in that ID to target the Daily file.

If the user explicitly provides a different date, do not silently choose one. Resolve the conflict before mutation.

### Daily Source

`source` describes how the Daily Task was created.

Known current sources include:

- `manual`;
- `carryover`;
- `standing`.

Do not change `source` merely because the Daily Task is linked to a Long or Standing Task.

### Daily Relationships

`long_task_id` is an optional Long Task relationship.

`standing_task_id` is an optional Standing Task relationship.

These relationships are independent of the Daily Task's own date and creation ID.

When a Standing-generated Daily occurrence is created, preserve:

```text
source = standing
standing_task_id = generating Standing Task ID
long_task_id = Standing Task's Long relation, when present
```

### Standing-Generated Daily Idempotency

Within one Daily file, a non-null `standing_task_id` identifies at most one Daily occurrence for that Standing rule.

When Daily add is retried with a `standing_task_id` that already exists for that Daily date, the Tool may return the existing Daily Task with:

`created=false`

Treat that result as successful idempotent recovery.

Do not create a second Daily occurrence merely because the first creation happened before Standing generation state was updated.

### Daily Status

Use the dedicated status operation for Daily completion state.

Do not update status by directly editing JSON.

### Daily Removal

Daily remove is physical deletion.

Use it only when the user clearly requests deletion/removal of that Daily Task.

Do not interpret phrases such as:

- "not doing this today";
- "leave it for later";
- "skip it";

as permission to physically delete the record unless the user's deletion intent is clear.

## Long Task

### Status and Active State

Long Task `status` and `active` represent different concepts.

Normal meanings:

- `pending + active=true` — currently being pursued;
- `pending + active=false` — paused or backlog;
- `done + active=false` — completed.

When a Long Task becomes `done`, the Tool sets `active=false`.

When a completed Long Task is reopened to `pending`, it remains inactive until explicitly activated.

Do not automatically reactivate a reopened Long Task.

### Stage

`stage` is an open user-defined string.

Do not impose a fixed enum unless project design explicitly changes.

Use the dedicated stage operation for stage changes.

### Deadline

A Long Task deadline is optional.

When present, use the explicit date supplied by the user or context.

Do not invent a deadline.

### Timeline

Use dedicated Tool operations for progress and notes.

Current user-progress record meanings include:

- `progress`;
- `note`.

Do not manually forge system-origin timeline events.

### Archive Versus Completion

Archive and completion are independent concepts.

Before archiving a Long Task:

1. obtain the current Task state;
2. determine whether completion intent is already clear;
3. if the Task is still pending and the user's intent is ambiguous, ask whether it should:
   - first be marked done; or
   - be archived while still incomplete.

Do not automatically mark a Long Task done merely because it is being archived.

If the user clearly states that the Task is incomplete, abandoned, permanently paused, or should be archived without completion, that instruction is sufficient.

### Archive and Restore

Use the dedicated archive/unarchive operations.

Do not manually move Long Task objects between active and archived storage.

Unarchive restores the Task but leaves it inactive.

Activate it only when the user explicitly wants to resume it.

### No Normal Physical Long Remove

The current Long V1 runtime interface has no normal physical remove operation.

Do not simulate one by directly editing Task Data.

## Standing Task

### Enabled State

`enabled` controls whether the recurrence participates in schedule checking.

It is not completion status.

Standing V1 does not use Long-style `active`.

If the user wants a recurrence paused but preserved, disable it.

### Supported Schedule Types

Standing V1 supports:

- daily;
- weekly;
- monthly;
- yearly.

Weekly schedules may contain multiple weekdays, for example:

```json
{
  "type": "weekly",
  "weekdays": ["wednesday", "thursday"]
}
```

Monthly schedules use an exact calendar day:

```json
{
  "type": "monthly",
  "day": 31
}
```

A monthly day does not silently slide to month-end.

For example, day 31 does not become April 30.

Yearly schedules use an exact month/day pair:

```json
{
  "type": "yearly",
  "month": 2,
  "day": 29
}
```

February 29 triggers only in leap years.

Do not invent nearest-date, last-day, or end-of-month behavior.

### Standing Long Relationship

A Standing Task may optionally be related to a Long Task.

When a due Standing occurrence generates a Daily Task, that Long relationship is inherited by the generated Daily payload when present.

Do not infer the Long relation from similar titles.

### Due State

Use the Standing due operation to determine recurrence state for a target date.

A Standing Task is due only when its deterministic Tool result says it is due.

Typical reasons for a non-due result include:

- disabled;
- schedule not matched;
- already generated.

Do not independently reproduce schedule calculations in Main when the Tool already provides the result.

### Standing to Daily Generation

The normal generation sequence is:

1. resolve the target date;
2. run Standing due;
3. process only items returned as due;
4. ensure the target Daily file exists;
5. create each Daily occurrence using the due item's deterministic `daily_payload`;
6. confirm that the Daily occurrence exists;
7. mark that Standing occurrence generated.

For Daily creation, both of these results are acceptable:

- `created=true` — a new Daily occurrence was created;
- `created=false` — the same Standing occurrence already exists for that Daily date and was recovered idempotently.

Do not call mark-generated before the corresponding Daily occurrence is confirmed.

### Interrupted Generation Recovery

Standing generation spans separate Daily and Standing writes.

A possible interruption is:

```text
Standing due
→ Daily add succeeds
→ process stops
→ Standing mark-generated did not happen
```

Recovery is:

1. run the due/generation workflow again;
2. retry Daily add with the same `standing_task_id`;
3. accept the existing Daily occurrence when returned with `created=false`;
4. mark the Standing occurrence generated.

Do not create a duplicate Daily occurrence during recovery.

### Generation State

`last_generated_date` records the latest confirmed generated calendar date for the Standing rule.

Mark-generated is idempotent for the same date.

Do not attempt to move generation state backward.

Do not mark a date that does not match the recurrence.

### Schedule Updates

Use the dedicated Standing schedule operation.

Changing a schedule does not imply that generation history should be erased.

Do not manually reset generation state.

### Standing Removal

Standing remove physically deletes the recurrence rule.

Use remove only when deletion intent is clear.

Disable and remove are different:

- **disable** — preserve the recurrence but stop participation;
- **remove** — delete the recurrence rule.

Prefer disable when the user's intent is pause/suspend rather than delete.

## Cross-Kind Orchestration

Main owns sequencing between Task kinds.

Services remain single-kind writers.

For example:

```text
Standing Tool
→ returns due item + Daily payload

Main
→ Daily ensure
→ Daily add
→ Standing mark-generated
```

Do not make Standing Service directly write Daily Data during normal architecture.

Likewise, a Long relationship does not require Long Service to create or modify Daily Data.

When a Daily Task should be related to a known Long Task, pass that relation through the Daily Tool operation.

## Failure and Recovery

If a Task Tool call fails:

1. preserve the returned failure;
2. do not bypass it with direct JSON mutation;
3. determine whether a safe prerequisite is missing;
4. retry only when the retry is semantically justified;
5. otherwise report the failure and the minimum next action.

Examples of safe prerequisite/recovery behavior include:

- ensure a missing Daily file before add;
- accept idempotent Standing-generated Daily recovery;
- inspect Long state before ambiguous archive.

Do not convert a deterministic validation failure into an AI guess.

## Runtime Completion Check

Before finishing a Task runtime request, verify that:

- the applicable Task Tool handled each deterministic mutation;
- the user's explicit Task intent was preserved;
- relationships were not inferred from title similarity;
- dependent operations were sequenced correctly;
- Standing mark-generated happened only after Daily existence was confirmed;
- archive completion intent was resolved when required;
- physical deletion was used only when deletion intent was clear;
- Tool failures or warnings were not hidden.
