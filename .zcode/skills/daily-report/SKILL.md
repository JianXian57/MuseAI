---
name: daily-report
description: Use when the user asks for a MuseAI daily report, daily status summary, or overview of today's Tasks, carryovers, active Long Tasks, deadlines, and recent progress.
---

# MuseAI Daily Report Skill

## Purpose

This Skill teaches Main how to turn MuseAI's deterministic Daily Report Snapshot into a concise human-readable daily report.

The deterministic report entry point is:

`python muse.py report daily`

For an explicit date:

`python muse.py report daily --date YYYY-MM-DD`

The Report Tool returns structured facts. Main is responsible only for presentation, light prioritization of already-computed facts, and natural-language phrasing.

The Report Tool and its current Snapshot contract are authoritative for exact runtime fields, warnings, and error behavior.

## Core Principle

Daily Report follows MuseAI's architecture rule:

> Programs determine facts. Skills teach method. Main expresses the result.

Do not move deterministic report calculations back into Main.

Do not independently re-read or reinterpret raw Task JSON when `report.daily` already provides the required facts.

## Runtime Boundary

Daily Report is read-only.

It must not:

- create, update, complete, remove, archive, or restore Tasks;
- run Standing generation logic;
- calculate Standing recurrence independently;
- modify Long Task state;
- call internal Task services directly during normal runtime;
- directly edit any Task JSON;
- silently run Task Maintenance as part of report rendering.

Task Maintenance and Daily Report are separate responsibilities.

The intended daily initialization order is:

```text
Task Maintenance
→ Daily Report
→ Main renders the report
```

When this Skill runs inside the normal daily initialization workflow, Maintenance is expected to have completed before `report.daily`.

## Source of Truth

For the report itself, use one Report Tool result as the primary source:

```text
python muse.py report daily
```

or:

```text
python muse.py report daily --date YYYY-MM-DD
```

Do not call Daily, Long, or Standing read commands merely to recreate data that is already present in the Report Snapshot.

Additional Task reads are justified only when the user asks a separate question that the Report Snapshot does not answer.

## Tool Result Handling

Always inspect the public Tool Result.

Expected success shape:

```json
{
  "ok": true,
  "operation": "report.daily",
  "data": {},
  "warnings": [],
  "error": null
}
```

If `ok=false`:

1. do not fabricate a report;
2. do not bypass the failure by directly reading Task JSON;
3. state the failure concisely;
4. surface the minimum useful error information;
5. only perform a separate recovery action when the user request or higher-level workflow explicitly authorizes it.

Do not hide warnings.

## Snapshot Meaning

The current Daily Report Snapshot contains these major sections:

```text
date
generated_at
today
previous
long
attention
```

Treat Snapshot fields as already-normalized report facts.

Do not infer hidden Task state from omitted fields.

## Today

`today` represents the target Daily collection.

Important fields include:

```text
today.exists
today.counts
today.pending
today.done
today.carryover
today.standing
```

### Today Counts

Use `today.counts` for concise overview numbers.

Current useful counts include:

```text
total
pending
done
manual
carryover
standing
other_source
```

Do not manually recount raw Task storage when these values are present.

### Pending Versus Done

For the main "today" work section, emphasize pending Tasks.

Completed Tasks may be summarized separately when useful, especially if the user asks for progress rather than only remaining work.

Do not present a completed Task as current unfinished work.

### Carryover

A Task with:

```text
source = carryover
```

was mechanically carried into the target Daily by Task Maintenance.

Do not describe carryover as proof that the prior Task was completed.

Carryover means:

> the work remains relevant today.

If a carryover Task has already been completed today, it may still appear in `today.carryover`, but it must not be described as unfinished.

For "needs attention" wording, use the deterministic attention count rather than assuming every carryover is still pending.

### Standing Occurrences

A Task with:

```text
source = standing
```

is today's Daily occurrence of a Standing recurrence.

Do not independently calculate whether the underlying Standing rule is due.

For normal report rendering, the Daily occurrence is the report fact.

`today.counts.standing` counts all Tasks whose `source=standing` in the target
Daily, regardless of whether those occurrences are currently `pending` or
`done`.

Do not describe `today.counts.standing` by itself as the number of unfinished
Standing Tasks. When completion state matters, use the Task status already
present in `today.pending`, `today.done`, or the individual occurrence data.

Do not re-read Standing merely to duplicate this information.

## Previous

`previous` represents the nearest earlier Daily collection, not necessarily the literal previous calendar day.

Important fields include:

```text
previous.exists
previous.date
previous.days_gap
previous.counts
previous.completed
```

### "Yesterday" Versus "Last Record"

Use `previous.days_gap` when choosing language.

If:

```text
days_gap == 1
```

phrasing such as "昨日" / "昨天" is appropriate.

If:

```text
days_gap > 1
```

do not call it "yesterday".

Prefer wording such as:

```text
上次记录（09-03）
最近一次记录（2026-09-03）
```

Use the actual `previous.date`.

### Previous Pending Tasks

The Snapshot intentionally does not need to repeat previous pending Tasks in full.

If Maintenance carried them forward, today's carryover data is the current report fact.

Do not duplicate the same unfinished work under both "previous" and "today" unless the distinction materially helps the user.

### Previous Completed Tasks

Use `previous.completed` to summarize recent progress.

Keep this section compact.

The purpose is to answer:

> What was completed in the nearest prior working record?

It is not a full historical audit.

## Long Tasks

The `long` section contains deterministic deadline/status groupings.

Current groups include:

```text
long.active
long.due_today
long.overdue
```

### Active

`long.active` means currently active, pending Long Tasks.

Do not treat every active Long Task as urgent.

### Due Today

`long.due_today` contains pending Long Tasks whose deadline equals the report date.

These deserve clear visibility in the report.

Use factual wording such as:

```text
今日到期
截止今天
```

Do not add urgency beyond what the deadline supports.

### Overdue

`long.overdue` contains pending Long Tasks whose deadline is earlier than the report date.

When `days_overdue` is present, use it directly.

Example:

```text
已逾期 2 天
```

Do not recalculate the number in Main unless the field is unavailable.

### Long Task Overlap

A Long Task may appear in both:

```text
active
```

and a deadline-risk group such as:

```text
overdue
```

This is intentional.

`active` describes work state.

`overdue` describes deadline state.

Do not treat this as duplicate or inconsistent data.

## Attention

The `attention` section is a deterministic compact signal.

Current fields include:

```text
has_attention
carryover_count
due_today_long_count
overdue_long_count
```

Use it to decide whether a "需要关注" section is useful.

Do not turn it into an AI-generated priority score.

Do not invent numeric priority, severity, urgency, or "most important task" unless the user explicitly asks for prioritization or planning.

Current `carryover_count` represents pending carryover requiring attention, not every historical carryover source in today's Daily.

## Missing Target Daily

The normal daily workflow expects Task Maintenance to initialize the target Daily before reporting.

If the Report Tool succeeds but returns a warning such as:

```text
TARGET_DAILY_NOT_INITIALIZED
```

then:

- do not silently create the Daily file;
- do not pretend today's Task state is initialized;
- state that today's Daily Task state has not been initialized;
- continue to report other valid Snapshot facts when useful.

Report remains read-only even in this state.

If the surrounding orchestration explicitly owns daily initialization, that higher-level workflow may run Maintenance separately before retrying Report.

This Skill itself does not hide that boundary.

## Warnings

Warnings are meaningful runtime facts.

When warnings exist:

- reflect warnings that affect interpretation;
- omit low-value implementation noise when it has no user impact;
- never claim complete or normal report state when a warning says otherwise.

Do not convert a warning into a success assumption.

## Natural-Language Rendering

The final report should be concise and information-dense.

A normal ordering is:

```text
概览
→ 今日任务
→ 长期任务
→ 上次进展
→ 需要关注
```

The exact headings may follow the Daily Report template when available.

Empty or meaningless sections may be omitted.

Do not produce a large block of "暂无" sections.

## Presentation Priority

Without inventing new Task priority, prefer this visibility order when relevant:

```text
1. overdue Long Tasks
2. Long Tasks due today
3. pending carryover
4. other pending Daily Tasks
5. recent completed work
```

This is presentation ordering only.

It does not modify Task state and does not assert that one user's Task is objectively more important than another.

If the user explicitly asks for planning, prioritization, scheduling, or recommendations, that is a separate reasoning task and may go beyond this Skill.

## Tone

Use concise, operational language.

Prefer concrete statements:

```text
今天共有 5 项任务，3 项待完成。
1 项长期任务今日到期。
有 2 项工作从上次记录顺延。
```

Avoid filler such as:

```text
新的一天，加油！
今天也要元气满满！
相信你一定可以完成！
```

unless the active Character explicitly calls for that style.

Character affects expression only.

Character must not alter:

- counts;
- Task status;
- dates;
- deadline meaning;
- carryover meaning;
- warning meaning;
- Report Tool facts.

## No Fabrication

Never invent:

- Tasks not present in the Snapshot;
- deadlines;
- completion state;
- Standing schedule state;
- reasons a Task is overdue;
- reasons a Task was carried over;
- priority scores;
- progress percentages;
- inferred relationships from similar titles.

When information is absent, omit it or state that it is unavailable.

## Avoid Raw JSON Dumping

The user normally wants a readable daily report, not a serialization of the Snapshot.

Do not paste the full Tool JSON unless:

- the user explicitly requests raw data;
- debugging requires exact fields;
- another technical workflow needs the structured payload.

Otherwise summarize the structured facts.

## Template Use

When `templates/daily-report.md` exists, use it as the preferred human-facing skeleton.

The template is a presentation structure, not a second source of business truth.

If a template section has no meaningful content, it may be omitted according to this Skill.

Do not let template placeholders override Snapshot facts.

## Example Rendering Logic

Given a Snapshot equivalent to:

```text
today:
  pending = 4
  carryover = 1 pending
  standing = 2 total occurrences

long:
  due_today = 1
  overdue = 1

previous:
  days_gap = 1
  completed = 2
```

a concise report may say:

```text
今日共有 4 项待办，其中 1 项为昨日顺延。今天的全部任务记录中，有 2 项来源于常驻任务。

长期任务方面，1 项今日到期，另有 1 项已逾期，需要关注。

昨日完成了 2 项工作。
```

The Standing sentence above intentionally reports provenance, not unfinished
count. Do not turn `standing = 2 total occurrences` into "2 项常驻任务待办"
unless the Snapshot's status data separately supports that statement.

Do not add invented task importance or causal explanations.

## Runtime Completion Check

Before finishing a Daily Report request, verify that:

- `report.daily` was used as the primary report source;
- the Tool result succeeded before facts were presented;
- warnings were not hidden;
- no Task data was mutated by the reporting flow;
- no raw Task JSON was read merely to duplicate Snapshot facts;
- previous-day wording respects `days_gap`;
- completed carryover was not presented as still pending;
- deadline wording came from `due_today` / `overdue`;
- `days_overdue` was used when available;
- Standing recurrence was not recalculated in Main;
- no Task priority or relationship was invented;
- the final answer is concise and human-readable.
