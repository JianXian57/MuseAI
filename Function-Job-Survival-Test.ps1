param(
    [int] $ChildLifetimeSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$MuseCmd = Join-Path $ProjectRoot "muse.cmd"
$RuntimeConfig = Join-Path $ProjectRoot "config\runtime.json"
$FuncRoot = Join-Path $ProjectRoot "func"

if (-not (Test-Path -LiteralPath $MuseCmd -PathType Leaf)) {
    throw "muse.cmd not found: $MuseCmd"
}

if (-not (Test-Path -LiteralPath $RuntimeConfig -PathType Leaf)) {
    throw "runtime.json not found. Configure MuseAI Runtime first: .\muse.cmd --settings"
}

$runtime = Get-Content -LiteralPath $RuntimeConfig -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    $null -eq $runtime -or
    -not ($runtime.PSObject.Properties.Name -contains "python_executable") -or
    -not ($runtime.python_executable -is [string]) -or
    [string]::IsNullOrWhiteSpace($runtime.python_executable)
) {
    throw "runtime.json does not contain a valid python_executable."
}

$PythonExe = [Environment]::ExpandEnvironmentVariables($runtime.python_executable.Trim())
if (-not [IO.Path]::IsPathRooted($PythonExe)) {
    $PythonExe = [IO.Path]::GetFullPath((Join-Path $ProjectRoot $PythonExe))
}
else {
    $PythonExe = [IO.Path]::GetFullPath($PythonExe)
}

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Configured Python does not exist: $PythonExe"
}

$stamp = Get-Date -Format "yyyyMMddHHmmss"
$FunctionId = "job-survival-test-$stamp-$PID"
$PackageRoot = Join-Path $FuncRoot $FunctionId
$ConfigDir = Join-Path $PackageRoot "config"
$ScriptDir = Join-Path $PackageRoot "script"
$ConfigPath = Join-Path $ConfigDir "function.yaml"
$ChildScriptPath = Join-Path $ScriptDir "job_child_launcher.py"

$Registered = $false
$ChildPid = $null
$FinalPass = $false

function Invoke-MuseJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $Arguments,
        [Parameter(Mandatory = $true)]
        [string] $Label
    )

    $rawLines = @(& $MuseCmd @Arguments)
    $exitCode = $LASTEXITCODE
    $raw = ($rawLines -join [Environment]::NewLine).Trim()

    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "$Label returned no stdout. exit=$exitCode"
    }

    try {
        $json = $raw | ConvertFrom-Json
    }
    catch {
        throw "$Label did not return valid JSON. exit=$exitCode`n$raw"
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Json = $json
        Raw = $raw
    }
}

try {
    Write-Host "MuseAI Custom Function Job Survival Test"
    Write-Host "=========================================="
    Write-Host "Function ID: $FunctionId"
    Write-Host "Python:      $PythonExe"
    Write-Host ""

    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
    New-Item -ItemType Directory -Path $ScriptDir -Force | Out-Null

    $childScript = @'
import subprocess
import sys

child = subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import time; time.sleep(CHILD_LIFETIME_PLACEHOLDER)",
    ],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    close_fds=True,
)

print(f"CHILD_PID={child.pid}", flush=True)
print("FUNCTION_LAUNCHER_EXITING=1", flush=True)
'@

    $childScript = $childScript.Replace(
        "CHILD_LIFETIME_PLACEHOLDER",
        [string]$ChildLifetimeSeconds
    )

    [IO.File]::WriteAllText(
        $ChildScriptPath,
        $childScript,
        (New-Object System.Text.UTF8Encoding($false))
    )

    # JSON string syntax is valid YAML and safely quotes Windows paths.
    $pythonYaml = $PythonExe | ConvertTo-Json -Compress
    $functionConfig = @"
schema_version: "1.0"
process:
  command: $pythonYaml
  args:
    - "script/job_child_launcher.py"
  cwd: "."
  timeout_seconds: 10
"@

    [IO.File]::WriteAllText(
        $ConfigPath,
        $functionConfig,
        (New-Object System.Text.UTF8Encoding($false))
    )

    Write-Host "[1/4] Register temporary Function..."
    $register = Invoke-MuseJson -Label "function register" -Arguments @(
        "function", "register", $FunctionId,
        "--name", "Job Survival Test",
        "--description", "Temporary Custom Function used to test background child survival."
    )

    if ($register.ExitCode -ne 0 -or $register.Json.ok -ne $true) {
        throw "Function registration failed:`n$($register.Raw)"
    }
    $Registered = $true
    Write-Host "      PASS"

    Write-Host "[2/4] Run Function through MuseAI Function Runtime..."
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $run = Invoke-MuseJson -Label "function run" -Arguments @(
        "function", "run", $FunctionId
    )
    $sw.Stop()

    if ($run.ExitCode -ne 0 -or $run.Json.ok -ne $true) {
        throw "Function run failed:`n$($run.Raw)"
    }

    $stdout = [string]$run.Json.data.stdout
    $pidMatch = [regex]::Match($stdout, '(?m)^CHILD_PID=(\d+)\s*$')
    if (-not $pidMatch.Success) {
        throw "Function completed but CHILD_PID was not found in stdout:`n$stdout"
    }

    $ChildPid = [int]$pidMatch.Groups[1].Value
    Write-Host ("      Function returned in {0:N2}s; child PID={1}" -f $sw.Elapsed.TotalSeconds, $ChildPid)

    Write-Host "[3/4] Check whether background child survived Function completion..."
    Start-Sleep -Milliseconds 800

    $child = Get-Process -Id $ChildPid -ErrorAction SilentlyContinue
    if ($null -eq $child) {
        Write-Host "      FAIL - child process is no longer alive."
        Write-Host ""
        Write-Host "RESULT: FAIL"
        Write-Host "The Function Runtime or Job lifecycle does not preserve this background child."
        $FinalPass = $false
    }
    else {
        Write-Host "      PASS - child is still alive after Function returned."
        Write-Host ""
        Write-Host "RESULT: PASS"
        Write-Host "A normally completed Custom Function can leave an intentional background child alive."
        $FinalPass = $true
    }
}
catch {
    Write-Host ""
    Write-Host "RESULT: ERROR"
    Write-Host $_.Exception.Message
    $FinalPass = $false
}
finally {
    Write-Host ""
    Write-Host "[4/4] Cleanup..."

    if ($null -ne $ChildPid) {
        $child = Get-Process -Id $ChildPid -ErrorAction SilentlyContinue
        if ($null -ne $child) {
            Stop-Process -Id $ChildPid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 200
        }
    }

    if ($Registered) {
        try {
            $null = Invoke-MuseJson -Label "function unregister" -Arguments @(
                "function", "unregister", $FunctionId
            )
        }
        catch {
            Write-Host "      Warning: unregister cleanup failed: $($_.Exception.Message)"
        }
    }

    if (Test-Path -LiteralPath $PackageRoot) {
        Remove-Item -LiteralPath $PackageRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host "      Temporary process/package cleanup complete."
}

if ($FinalPass) {
    exit 0
}

exit 1
