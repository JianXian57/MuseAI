Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    [Console]::Error.WriteLine("MuseAI Settings currently supports Windows only.")
    exit 1
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

[System.Windows.Forms.Application]::EnableVisualStyles()

$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ConfigDirectory = Join-Path $ProjectRoot "config"
$RuntimeConfigPath = Join-Path $ConfigDirectory "runtime.json"
$MuseEntryPath = Join-Path $ProjectRoot "muse.py"

$script:LastCheckedPath = $null
$script:LastCheckReady = $false

function ConvertTo-WindowsCommandLineArgument {
    param([AllowEmptyString()][string] $Value)

    if ($null -eq $Value -or $Value.Length -eq 0) {
        return '""'
    }

    if ($Value -notmatch '[\s"]') {
        return $Value
    }

    $result = '"'
    $backslashes = 0

    foreach ($ch in $Value.ToCharArray()) {
        if ([int]$ch -eq 92) {
            $backslashes += 1
            continue
        }

        if ($ch -eq '"') {
            if ($backslashes -gt 0) {
                $result += (('\' * ($backslashes * 2)) -join '')
            }
            $result += '\"'
            $backslashes = 0
            continue
        }

        if ($backslashes -gt 0) {
            $result += (('\' * $backslashes) -join '')
            $backslashes = 0
        }

        $result += $ch
    }

    if ($backslashes -gt 0) {
        $result += (('\' * ($backslashes * 2)) -join '')
    }

    return $result + '"'
}

function Invoke-PythonProcess {
    param(
        [Parameter(Mandatory = $true)][string] $PythonExecutable,
        [Parameter(Mandatory = $true)][string[]] $Arguments
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $PythonExecutable
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.Arguments = (($Arguments | ForEach-Object {
        ConvertTo-WindowsCommandLineArgument $_
    }) -join " ")

    $psi.EnvironmentVariables["PYTHONUTF8"] = "1"
    $psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"

    if ($psi.PSObject.Properties.Name -contains "StandardOutputEncoding") {
        $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
    }

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi

    try {
        if (-not $process.Start()) {
            return [pscustomobject]@{
                Started = $false
                ExitCode = $null
                Stdout = ""
                Stderr = "Process.Start() returned false."
            }
        }

        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()

        return [pscustomobject]@{
            Started = $true
            ExitCode = $process.ExitCode
            Stdout = $stdout.Trim()
            Stderr = $stderr.Trim()
        }
    }
    catch {
        return [pscustomobject]@{
            Started = $false
            ExitCode = $null
            Stdout = ""
            Stderr = $_.Exception.Message
        }
    }
    finally {
        $process.Dispose()
    }
}

function Resolve-SelectedPythonPath {
    param([string] $Text)

    $candidate = [Environment]::ExpandEnvironmentVariables($Text.Trim())
    if ([string]::IsNullOrWhiteSpace($candidate)) {
        throw "Please select a Python executable."
    }

    if ([IO.Path]::IsPathRooted($candidate)) {
        return [IO.Path]::GetFullPath($candidate)
    }

    return [IO.Path]::GetFullPath((Join-Path $ProjectRoot $candidate))
}

function Test-MuseRuntime {
    param([Parameter(Mandatory = $true)][string] $PythonExecutable)

    $lines = New-Object System.Collections.Generic.List[string]
    $ready = $true

    $lines.Add("Python executable")
    $lines.Add("  $PythonExecutable")

    if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
        $lines.Add("  [FAIL] File does not exist.")
        return [pscustomobject]@{
            Ready = $false
            Text = ($lines -join [Environment]::NewLine)
        }
    }

    $versionResult = Invoke-PythonProcess `
        -PythonExecutable $PythonExecutable `
        -Arguments @(
            "-X", "utf8", "-c",
            "import sys; print('.'.join(map(str, sys.version_info[:3])))"
        )

    if (-not $versionResult.Started -or $versionResult.ExitCode -ne 0) {
        $ready = $false
        $lines.Add("Python version")
        $lines.Add("  [FAIL] Python could not be started.")
        if ($versionResult.Stderr) {
            $lines.Add("  $($versionResult.Stderr)")
        }
    }
    else {
        $versionText = $versionResult.Stdout.Trim()
        $lines.Add("Python version")
        if ($versionText -match '^3\.13\.\d+$') {
            $lines.Add("  [PASS] $versionText")
        }
        else {
            $ready = $false
            $lines.Add("  [FAIL] $versionText")
            $lines.Add("  MuseAI Runtime V1 requires Python >=3.13,<3.14.")
        }
    }

    $yamlResult = Invoke-PythonProcess `
        -PythonExecutable $PythonExecutable `
        -Arguments @(
            "-X", "utf8", "-c",
            "import yaml; print(getattr(yaml, '__version__', 'installed'))"
        )

    $lines.Add("PyYAML")
    if ($yamlResult.Started -and $yamlResult.ExitCode -eq 0) {
        $lines.Add("  [PASS] $($yamlResult.Stdout)")
    }
    else {
        $ready = $false
        $lines.Add("  [FAIL] Missing or unusable.")
        if ($yamlResult.Stderr) {
            $lines.Add("  $($yamlResult.Stderr)")
        }
    }

    $tzdataResult = Invoke-PythonProcess `
        -PythonExecutable $PythonExecutable `
        -Arguments @(
            "-X", "utf8", "-c",
            "import tzdata; print(getattr(tzdata, '__version__', 'installed'))"
        )

    $lines.Add("tzdata")
    if ($tzdataResult.Started -and $tzdataResult.ExitCode -eq 0) {
        $lines.Add("  [PASS] $($tzdataResult.Stdout)")
    }
    else {
        $ready = $false
        $lines.Add("  [FAIL] Missing or unusable.")
        if ($tzdataResult.Stderr) {
            $lines.Add("  $($tzdataResult.Stderr)")
        }
    }

    $lines.Add("MuseAI CLI")
    if (-not (Test-Path -LiteralPath $MuseEntryPath -PathType Leaf)) {
        $ready = $false
        $lines.Add("  [FAIL] muse.py not found.")
    }
    else {
        $museResult = Invoke-PythonProcess `
            -PythonExecutable $PythonExecutable `
            -Arguments @("-X", "utf8", $MuseEntryPath, "time", "current")

        if ($museResult.Started -and $museResult.ExitCode -eq 0) {
            $lines.Add("  [PASS] muse.py time current")
        }
        else {
            $ready = $false
            $lines.Add("  [FAIL] muse.py time current")
            if ($museResult.Stderr) {
                $lines.Add("  $($museResult.Stderr)")
            }
            elseif ($museResult.Stdout) {
                $lines.Add("  $($museResult.Stdout)")
            }
        }
    }

    $lines.Add("")
    if ($ready) {
        $lines.Add("Overall: READY")
    }
    else {
        $lines.Add("Overall: NOT READY")
        $lines.Add("No packages or environments were modified.")
    }

    return [pscustomobject]@{
        Ready = $ready
        Text = ($lines -join [Environment]::NewLine)
    }
}

function Save-RuntimeConfig {
    param([Parameter(Mandatory = $true)][string] $PythonExecutable)

    if (-not (Test-Path -LiteralPath $ConfigDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $ConfigDirectory -Force | Out-Null
    }

    $config = [ordered]@{
        schema_version = "1.0"
        python_executable = $PythonExecutable
    }

    $json = $config | ConvertTo-Json -Depth 4
    $tempPath = Join-Path $ConfigDirectory ("runtime.json.tmp.{0}" -f $PID)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)

    try {
        [IO.File]::WriteAllText(
            $tempPath,
            $json + [Environment]::NewLine,
            $utf8NoBom
        )
        Move-Item -LiteralPath $tempPath -Destination $RuntimeConfigPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $tempPath -PathType Leaf) {
            Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
        }
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "MuseAI Settings"
$form.StartPosition = "CenterScreen"
$form.ClientSize = New-Object System.Drawing.Size(760, 520)
$form.MinimumSize = New-Object System.Drawing.Size(776, 559)
$form.Font = New-Object System.Drawing.Font("Segoe UI", 9)

$title = New-Object System.Windows.Forms.Label
$title.Text = "Runtime"
$title.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 16)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(24, 20)
$form.Controls.Add($title)

$description = New-Object System.Windows.Forms.Label
$description.Text = "Select the Python executable MuseAI should use. Settings does not install or modify Python packages."
$description.AutoSize = $true
$description.Location = New-Object System.Drawing.Point(27, 58)
$form.Controls.Add($description)

$pathLabel = New-Object System.Windows.Forms.Label
$pathLabel.Text = "Python executable"
$pathLabel.AutoSize = $true
$pathLabel.Location = New-Object System.Drawing.Point(27, 96)
$form.Controls.Add($pathLabel)

$pathBox = New-Object System.Windows.Forms.TextBox
$pathBox.Location = New-Object System.Drawing.Point(30, 118)
$pathBox.Size = New-Object System.Drawing.Size(600, 25)
$pathBox.Anchor = "Top,Left,Right"
$form.Controls.Add($pathBox)

$browseButton = New-Object System.Windows.Forms.Button
$browseButton.Text = "Browse..."
$browseButton.Location = New-Object System.Drawing.Point(642, 116)
$browseButton.Size = New-Object System.Drawing.Size(88, 28)
$browseButton.Anchor = "Top,Right"
$form.Controls.Add($browseButton)

$resultBox = New-Object System.Windows.Forms.TextBox
$resultBox.Location = New-Object System.Drawing.Point(30, 166)
$resultBox.Size = New-Object System.Drawing.Size(700, 270)
$resultBox.Anchor = "Top,Bottom,Left,Right"
$resultBox.Multiline = $true
$resultBox.ReadOnly = $true
$resultBox.ScrollBars = "Vertical"
$resultBox.Font = New-Object System.Drawing.Font("Consolas", 9)
$resultBox.Text = "Select a Python executable, then choose Check."
$form.Controls.Add($resultBox)

$checkButton = New-Object System.Windows.Forms.Button
$checkButton.Text = "Check"
$checkButton.Location = New-Object System.Drawing.Point(468, 458)
$checkButton.Size = New-Object System.Drawing.Size(80, 30)
$checkButton.Anchor = "Bottom,Right"
$form.Controls.Add($checkButton)

$saveButton = New-Object System.Windows.Forms.Button
$saveButton.Text = "Save"
$saveButton.Location = New-Object System.Drawing.Point(558, 458)
$saveButton.Size = New-Object System.Drawing.Size(80, 30)
$saveButton.Anchor = "Bottom,Right"
$form.Controls.Add($saveButton)

$closeButton = New-Object System.Windows.Forms.Button
$closeButton.Text = "Close"
$closeButton.Location = New-Object System.Drawing.Point(648, 458)
$closeButton.Size = New-Object System.Drawing.Size(80, 30)
$closeButton.Anchor = "Bottom,Right"
$form.Controls.Add($closeButton)

$browseButton.Add_Click({
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "Select Python executable"
    $dialog.Filter = "Python executable (python.exe)|python.exe|Executable files (*.exe)|*.exe|All files (*.*)|*.*"
    $dialog.CheckFileExists = $true
    $dialog.Multiselect = $false

    if (-not [string]::IsNullOrWhiteSpace($pathBox.Text)) {
        try {
            $existing = Resolve-SelectedPythonPath $pathBox.Text
            $directory = Split-Path -Parent $existing
            if (Test-Path -LiteralPath $directory -PathType Container) {
                $dialog.InitialDirectory = $directory
            }
        }
        catch {
        }
    }

    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        $pathBox.Text = $dialog.FileName
        $script:LastCheckedPath = $null
        $script:LastCheckReady = $false
        $resultBox.Text = "Path changed. Choose Check to validate the environment."
    }

    $dialog.Dispose()
})

$pathBox.Add_TextChanged({
    if ($script:LastCheckedPath -ne $pathBox.Text.Trim()) {
        $script:LastCheckReady = $false
    }
})

$checkButton.Add_Click({
    try {
        $selected = Resolve-SelectedPythonPath $pathBox.Text
        $pathBox.Text = $selected
        $form.UseWaitCursor = $true
        $checkButton.Enabled = $false
        $saveButton.Enabled = $false
        $resultBox.Text = "Checking..."
        [System.Windows.Forms.Application]::DoEvents()

        $result = Test-MuseRuntime -PythonExecutable $selected
        $script:LastCheckedPath = $selected
        $script:LastCheckReady = [bool]$result.Ready
        $resultBox.Text = $result.Text
    }
    catch {
        $script:LastCheckedPath = $null
        $script:LastCheckReady = $false
        $resultBox.Text = "Check failed:`r`n$($_.Exception.Message)"
    }
    finally {
        $form.UseWaitCursor = $false
        $checkButton.Enabled = $true
        $saveButton.Enabled = $true
    }
})

$saveButton.Add_Click({
    try {
        $selected = Resolve-SelectedPythonPath $pathBox.Text

        $checkedThisPath = (
            $null -ne $script:LastCheckedPath -and
            [string]::Equals(
                $script:LastCheckedPath,
                $selected,
                [StringComparison]::OrdinalIgnoreCase
            )
        )

        if (-not $checkedThisPath -or -not $script:LastCheckReady) {
            $answer = [System.Windows.Forms.MessageBox]::Show(
                "The selected runtime has not passed the current environment check.`r`n`r`nSave it anyway?",
                "MuseAI Settings",
                [System.Windows.Forms.MessageBoxButtons]::YesNo,
                [System.Windows.Forms.MessageBoxIcon]::Warning
            )

            if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
                return
            }
        }

        Save-RuntimeConfig -PythonExecutable $selected
        $pathBox.Text = $selected

        [System.Windows.Forms.MessageBox]::Show(
            "Runtime configuration saved to:`r`n$RuntimeConfigPath",
            "MuseAI Settings",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    }
    catch {
        [System.Windows.Forms.MessageBox]::Show(
            "Could not save runtime configuration:`r`n$($_.Exception.Message)",
            "MuseAI Settings",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
})

$closeButton.Add_Click({
    $form.Close()
})

if (Test-Path -LiteralPath $RuntimeConfigPath -PathType Leaf) {
    try {
        $existingConfig = (
            Get-Content -LiteralPath $RuntimeConfigPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
        )
        if (
            $null -ne $existingConfig -and
            ($existingConfig.PSObject.Properties.Name -contains "python_executable") -and
            ($existingConfig.python_executable -is [string])
        ) {
            $pathBox.Text = $existingConfig.python_executable
            $resultBox.Text = "Existing runtime configuration loaded. Choose Check to validate it."
        }
    }
    catch {
        $resultBox.Text = "Existing runtime.json could not be parsed. Select a Python executable and save a new configuration.`r`n`r`n$($_.Exception.Message)"
    }
}

$form.Add_Shown({
    $form.Activate()
})

[void]$form.ShowDialog()
$form.Dispose()
exit 0
