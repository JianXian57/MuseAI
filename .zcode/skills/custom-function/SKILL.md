# Custom Function

## Purpose

Use this Skill when the user asks about MuseAI Custom Functions, custom
functions, installing or adding a Function, registering a user script or
program, running a registered Function, changing Function metadata, enabling
or disabling a Function, or unregistering a Function.

Custom Function is a lightweight integration layer for relatively mature
user-provided scripts or programs.

MuseAI manages discovery and execution boundaries. It does not own the
Function implementation.

## Core Principle

Custom Function discovery is user-driven, not filesystem-driven.

Do not scan `func/` to discover candidate Functions.
Do not infer Function ID, name, description, purpose, or intended behavior
from filenames, README files, comments, scripts, or directory names unless
the user explicitly asks you to inspect a specific Function Package.

The user provides the semantic information for a Function.

The standard Function identity information is:

- Function ID
- Name
- Description

## Reference Package

When the user asks how to create, place, or install a Custom Function, point
them to the reference package:

```text
func/example-function/
```

Reference structure:

```text
func/<function-id>/
├─ README.md
├─ config/
│  └─ function.yaml
├─ data/
└─ script/
```

The user may copy `func/example-function/`, rename the directory to the
desired Function ID, replace the implementation, and adjust
`config/function.yaml`.

## Ownership Boundary

MuseAI-owned registry state:

```text
config/manifest.yaml
```

The registry stores:

- Function ID
- Name
- Description
- enabled

User-owned Function Package:

```text
func/<function-id>/
```

The package owns:

- runtime configuration
- scripts/programs
- Function-specific data

MuseAI must not automatically modify user script or data contents.

## Runtime Configuration

A Function's runtime configuration is:

```text
func/<function-id>/config/function.yaml
```

Expected shape:

```yaml
schema_version: "1.0"

process:
  command: python
  args:
    - script/main.py
  cwd: .
  timeout_seconds: null
```

`enabled` does not belong in `function.yaml`.
It is MuseAI registry state in `config/manifest.yaml`.

Relative `cwd` values are resolved from the Function root.

Configured arguments are passed as argv with `shell=False`.
When `function.run` includes per-invocation Function arguments, they are
appended after these fixed configured arguments.

Do not build a shell command string and do not infer script types.

## Installation / Registration Flow

When the user wants to add a Custom Function:

1. Tell the user to prepare and place the Function Package under:

   ```text
   func/<function-id>/
   ```

2. The user is responsible for adding the package files.

3. Obtain the following from the user explicitly:
   - Function ID
   - Name
   - Description

4. Do not scan `func/` and do not guess missing semantic information.

5. Once the user has explicitly identified the Function and package, use:

   ```text
   function.register
   ```

6. Registration validates the explicitly named existing package and its
   runtime configuration before adding it to the registry.

7. Report the Tool result to the user.

Registration must not create the Function Package.

## Running a Function

If the user explicitly provides a Function ID and execution intent, call:

```text
function.run
```

directly.

A Function may also accept explicit per-invocation argv. The public CLI form is:

```powershell
.\muse.cmd function run <function-id> <function-args...>
```

Arguments after `<function-id>` belong to the Function invocation. They are passed
as strings to the Function Runtime, which appends them after the fixed
`process.args` from `func/<function-id>/config/function.yaml`.

For example:

```powershell
.\muse.cmd function run one-click-launch work
```

means that `work` is Function-owned input. Main may select or provide those
arguments from explicit user intent, but MuseAI Function Runtime must not
interpret their script-specific business semantics.

Do not call `function.list` first when the Function ID is already explicit.

If the user expresses clear execution intent in natural language and one
registered Function is clearly intended, Main may select that Function.

If the target is uncertain, use:

```text
function.list
```

and optionally:

```text
function.get
```

to resolve the target.

If multiple plausible Functions remain, ask the user which one they mean.

A read-only question about a Function does not authorize execution.

## Updating Metadata

Use:

```text
function.update
```

to change only:

- name
- description

Do not use metadata update as a way to modify the Function implementation or
runtime configuration.

The semantic information should come from the user rather than being inferred
from Function files.

## Enable / Disable

Use:

```text
function.enable
function.disable
```

to change MuseAI registry state.

These operations update `config/manifest.yaml`.

They do not modify:

```text
func/<function-id>/config/function.yaml
```

Repeated enable/disable operations may succeed with `changed=false`.

## Unregister

Use:

```text
function.unregister
```

when the user wants MuseAI to stop managing or exposing a registered Function.

Unregister means:

- remove the registry entry;
- leave `func/<function-id>/` untouched.

Do not delete the Function Package, scripts, config, or data.

MuseAI currently has no automatic Function deletion workflow.

If the user asks to delete Function files, explain that unregistering does
not delete them and that destructive package deletion is outside the current
Custom Function management scope.

## Execution Result Handling

Function Runtime reports execution facts upward.

For a normal child-process exit:

```text
exit_code = 0
→ function.run ok=true
```

For a non-zero child-process exit:

```text
exit_code != 0
→ function.run ok=false
→ FUNCTION_PROCESS_FAILED
```

Preserve and report the returned execution information, including relevant:

- exit_code
- stdout
- stderr
- truncation flags

Do not automatically diagnose, repair, retry, modify the script, install
dependencies, or mutate the environment.

If the user asks for diagnosis after a failure, that is a separate request
and should be handled explicitly.

## Host Shortcuts

A ZCode custom command may act as a thin shortcut.

Recommended flow:

```text
ZCode shortcut
→ explicit Function ID + execution intent
→ Main
→ function.run <id>
```

Do not duplicate command paths, argv, or script logic inside the ZCode
shortcut.

`func/<id>/config/function.yaml` remains the single source of truth for how
the Function is started.

## User-Facing Installation Explanation

When the user asks how to install a Custom Function, explain approximately:

1. Copy or reference `func/example-function/`.
2. Create `func/<function-id>/`.
3. Put the implementation in `script/`.
4. Configure execution in `config/function.yaml`.
5. Use `data/` only if the Function needs its own runtime/business data.
6. Tell MuseAI the Function ID, Name, and Description.
7. MuseAI registers the existing package.
8. After registration and while enabled, it can be called through Main or
   `.\muse.cmd function run <function-id>`.

Keep this explanation concise unless the user requests more detail.
