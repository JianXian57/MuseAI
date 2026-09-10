param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $MuseArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($null -eq $MuseArgs) {
    $MuseArgs = @()
}

# Keep the bootstrap protocol deterministic on Windows PowerShell 5.1.
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8NoBom
[Console]::InputEncoding = $Utf8NoBom
$OutputEncoding = $Utf8NoBom

function Exit-LauncherError {
    param(
        [Parameter(Mandatory = $true)][string] $Code,
        [Parameter(Mandatory = $true)][string] $Message,
        [int] $ExitCode = 2
    )

    [Console]::Error.WriteLine("MuseAI Launcher [$Code] $Message")
    exit $ExitCode
}

function Resolve-ConfiguredPath {
    param(
        [Parameter(Mandatory = $true)][string] $Value,
        [Parameter(Mandatory = $true)][string] $BaseDirectory
    )

    $expanded = [Environment]::ExpandEnvironmentVariables($Value.Trim())
    if ([string]::IsNullOrWhiteSpace($expanded)) {
        throw "Configured path is empty."
    }

    if ([IO.Path]::IsPathRooted($expanded)) {
        return [IO.Path]::GetFullPath($expanded)
    }

    return [IO.Path]::GetFullPath((Join-Path $BaseDirectory $expanded))
}

function Test-IsWithinProjectRoot {
    param(
        [Parameter(Mandatory = $true)][string] $Candidate,
        [Parameter(Mandatory = $true)][string] $ProjectRoot
    )

    $root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
    $candidateFull = [IO.Path]::GetFullPath($Candidate)
    $prefix = $root + [IO.Path]::DirectorySeparatorChar

    return $candidateFull.StartsWith(
        $prefix,
        [StringComparison]::OrdinalIgnoreCase
    )
}

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$RuntimeConfigPath = Join-Path $ProjectRoot "config\runtime.json"
$MuseEntryPath = Join-Path $ProjectRoot "muse.py"
$SettingsPath = Join-Path $ProjectRoot "setup\settings.ps1"

# Bootstrap-only settings entry. This works before Python is configured.
if ($MuseArgs.Count -ge 1 -and $MuseArgs[0] -eq "--settings") {
    if (-not (Test-Path -LiteralPath $SettingsPath -PathType Leaf)) {
        Exit-LauncherError `
            -Code "SETTINGS_NOT_FOUND" `
            -Message ("Settings script not found: {0}" -f $SettingsPath) `
            -ExitCode 4
    }

    & $SettingsPath
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath $RuntimeConfigPath -PathType Leaf)) {
    Exit-LauncherError `
        -Code "RUNTIME_NOT_CONFIGURED" `
        -Message ("Runtime config is missing. Run '.\muse.cmd --settings' first. Expected: {0}" -f $RuntimeConfigPath) `
        -ExitCode 2
}

try {
    $rawConfig = Get-Content -LiteralPath $RuntimeConfigPath -Raw -Encoding UTF8
    $config = $rawConfig | ConvertFrom-Json
}
catch {
    Exit-LauncherError `
        -Code "RUNTIME_CONFIG_INVALID" `
        -Message ("Cannot parse runtime config '{0}': {1}" -f $RuntimeConfigPath, $_.Exception.Message) `
        -ExitCode 2
}

if ($null -eq $config) {
    Exit-LauncherError `
        -Code "RUNTIME_CONFIG_INVALID" `
        -Message "Runtime config must contain a JSON object." `
        -ExitCode 2
}

$propertyNames = @($config.PSObject.Properties.Name)

if (-not ($propertyNames -contains "schema_version")) {
    Exit-LauncherError `
        -Code "RUNTIME_CONFIG_INVALID" `
        -Message "runtime.json is missing 'schema_version'." `
        -ExitCode 2
}

if ([string]$config.schema_version -ne "1.0") {
    Exit-LauncherError `
        -Code "RUNTIME_SCHEMA_UNSUPPORTED" `
        -Message ("Unsupported runtime schema_version: {0}" -f $config.schema_version) `
        -ExitCode 2
}

if (-not ($propertyNames -contains "python_executable")) {
    Exit-LauncherError `
        -Code "PYTHON_NOT_CONFIGURED" `
        -Message "runtime.json is missing 'python_executable'." `
        -ExitCode 2
}

if (-not ($config.python_executable -is [string]) -or [string]::IsNullOrWhiteSpace($config.python_executable)) {
    Exit-LauncherError `
        -Code "PYTHON_NOT_CONFIGURED" `
        -Message "'python_executable' must be a non-empty string." `
        -ExitCode 2
}

try {
    $PythonExecutable = Resolve-ConfiguredPath `
        -Value $config.python_executable `
        -BaseDirectory $ProjectRoot
}
catch {
    Exit-LauncherError `
        -Code "PYTHON_PATH_INVALID" `
        -Message $_.Exception.Message `
        -ExitCode 2
}

if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    Exit-LauncherError `
        -Code "PYTHON_NOT_FOUND" `
        -Message ("Configured Python executable does not exist: {0}" -f $PythonExecutable) `
        -ExitCode 3
}

$TargetPath = $MuseEntryPath
$ForwardArgs = $MuseArgs

# Internal host-adapter mode. It intentionally permits only Python scripts
# located inside the MuseAI project root.
if ($MuseArgs.Count -ge 1 -and $MuseArgs[0] -eq "--script") {
    if ($MuseArgs.Count -lt 2 -or [string]::IsNullOrWhiteSpace($MuseArgs[1])) {
        Exit-LauncherError `
            -Code "SCRIPT_PATH_REQUIRED" `
            -Message "'--script' requires a Python script path." `
            -ExitCode 2
    }

    try {
        $TargetPath = Resolve-ConfiguredPath `
            -Value $MuseArgs[1] `
            -BaseDirectory $ProjectRoot
    }
    catch {
        Exit-LauncherError `
            -Code "SCRIPT_PATH_INVALID" `
            -Message $_.Exception.Message `
            -ExitCode 2
    }

    if (-not (Test-IsWithinProjectRoot -Candidate $TargetPath -ProjectRoot $ProjectRoot)) {
        Exit-LauncherError `
            -Code "SCRIPT_OUTSIDE_PROJECT" `
            -Message ("Internal --script target must be inside the MuseAI project: {0}" -f $TargetPath) `
            -ExitCode 4
    }

    if ([IO.Path]::GetExtension($TargetPath) -ne ".py") {
        Exit-LauncherError `
            -Code "SCRIPT_PATH_INVALID" `
            -Message ("Internal --script target must be a .py file: {0}" -f $TargetPath) `
            -ExitCode 4
    }

    if (-not (Test-Path -LiteralPath $TargetPath -PathType Leaf)) {
        Exit-LauncherError `
            -Code "SCRIPT_NOT_FOUND" `
            -Message ("Internal Python script does not exist: {0}" -f $TargetPath) `
            -ExitCode 4
    }

    if ($MuseArgs.Count -gt 2) {
        $ForwardArgs = @($MuseArgs[2..($MuseArgs.Count - 1)])
    }
    else {
        $ForwardArgs = @()
    }
}
else {
    if (-not (Test-Path -LiteralPath $MuseEntryPath -PathType Leaf)) {
        Exit-LauncherError `
            -Code "MUSE_ENTRY_NOT_FOUND" `
            -Message ("MuseAI runtime entry does not exist: {0}" -f $MuseEntryPath) `
            -ExitCode 4
    }
}

$previousPythonUtf8 = $env:PYTHONUTF8
$previousPythonIoEncoding = $env:PYTHONIOENCODING

try {
    # Make MuseAI child-process protocol deterministic on Windows.
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    try {
        & $PythonExecutable $TargetPath @ForwardArgs
        $childExitCode = $LASTEXITCODE
    }
    catch {
        Exit-LauncherError `
            -Code "PYTHON_START_FAILED" `
            -Message ("Failed to start configured Python '{0}': {1}" -f $PythonExecutable, $_.Exception.Message) `
            -ExitCode 3
    }
}
finally {
    if ($null -eq $previousPythonUtf8) {
        Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONUTF8 = $previousPythonUtf8
    }

    if ($null -eq $previousPythonIoEncoding) {
        Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONIOENCODING = $previousPythonIoEncoding
    }
}

if ($null -eq $childExitCode) {
    exit 1
}

exit [int]$childExitCode
