# One Click Launch

`one-click-launch` is a MuseAI Custom Function for launching one explicitly
selected user-defined launch group on Windows.

## Run

```powershell
.\muse.cmd function run one-click-launch <group-id>
```

Example:

```powershell
.\muse.cmd function run one-click-launch work
```

The group ID maps to:

```text
func/one-click-launch/config/groups/<group-id>.yaml
```

The Function never scans the group directory and never guesses which group to
run.

## Machine-local applications

Browser executable paths are resolved through:

```text
config/applications.yaml
```

Example:

```yaml
schema_version: "1.0"

applications:
  edge:
    type: browser
    executable: "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
```

`config/applications.yaml` is machine-local and ignored by Git. The repository
format reference is `config/applications.example.yaml`.

## Group schema

Each YAML file describes one launch group:

```yaml
schema_version: "1.0"
name: "Work"

launches:
  - name: "API Prices"
    type: browser
    application: edge
    tabs:
      - "https://example.com/"
      - "https://github.com/"

  - name: "Development"
    type: terminal
    tabs:
      - name: "MuseAI"
        shell: powershell
        cwd: "."
      - name: "CMD"
        shell: cmd
        cwd: "."

  - name: "Project Folder"
    type: folder
    target: "."
```

Supported launch types:

- `browser`
- `terminal`
- `folder`
- `exe`
- `powershell`
- `windows_powershell`
- `cmd`

A `browser` launch unit creates one explicitly requested browser window with all
configured URLs as tabs. Multiple browser units therefore represent separate
browser windows. Grouped browser windows currently support Edge, Chrome,
Chromium, and Firefox executable names.

A `terminal` launch unit creates one Windows Terminal window through `wt.exe`.
Its `tabs` may use `powershell`, `windows_powershell`, or `cmd`.

`folder` delegates one folder-open request to Explorer. Explorer decides its
own final window/tab placement.

Relative filesystem paths are resolved from the MuseAI project root.

## Failure behavior

The complete YAML structure is validated before launch begins.

During execution, one launch unit failing does not prevent later units from
being attempted. The Function reports each unit and returns:

```text
all launch units succeeded  -> exit 0
one or more units failed    -> exit 1
invalid group/config        -> exit 2
```

"Success" means MuseAI successfully started or dispatched the requested launch
action. It does not claim that a web page finished loading or that an
application completed its own business workflow.

## Git ownership

`example.yaml` is repository-tracked. Other files under
`config/groups/*.yaml` are user/machine-specific and ignored by Git by default.
