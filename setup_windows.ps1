[CmdletBinding()]
param(
    [string]$RepoName = "roblox-hat-alerts",
    [switch]$Private,
    [switch]$NoEveryone,
    [switch]$UpdateWebhook,
    [switch]$NoWait
)

$ErrorActionPreference = "Stop"

function Update-AlertPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = $env:Path + ";" + $machinePath + ";" + $userPath
}

function Install-AlertDependency([string]$PackageId) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Windows Package Manager (winget) is missing. Install Microsoft's App Installer from the Microsoft Store, then rerun this command."
    }
    Write-Host "Installing $PackageId..."
    & winget install --exact --id $PackageId --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        throw "Installation of $PackageId failed (exit $LASTEXITCODE). Resolve the installation error and rerun this command."
    }
    Update-AlertPath
}

function Find-AlertPython {
    $candidates = @()
    foreach ($name in @("python", "python3", "py")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command -and $command.Source -and $command.Source -notmatch "\\WindowsApps\\") {
            $candidates += $command.Source
        }
    }
    $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")
    $candidates += (Join-Path $env:ProgramFiles "Python313\python.exe")
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath $candidate) {
            $probe = & $candidate -c "import sys; print('PRICE_ALERT_PYTHON_OK' if sys.version_info >= (3, 8) else 'OLD')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $probe -contains "PRICE_ALERT_PYTHON_OK") {
                return $candidate
            }
        }
    }
    return $null
}

try {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot "setup_github.py"))) {
        throw "Extract the full hosting ZIP before running this script."
    }
    Update-AlertPath
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Install-AlertDependency "GitHub.cli"
    }
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        $cliDirectory = Join-Path $env:ProgramFiles "GitHub CLI"
        if (Test-Path -LiteralPath (Join-Path $cliDirectory "gh.exe")) {
            $env:Path += ";" + $cliDirectory
        }
    }
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw "GitHub CLI was installed but was not found. Open a new PowerShell window and rerun this command."
    }
    $pythonExecutable = Find-AlertPython
    if (-not $pythonExecutable) {
        Install-AlertDependency "Python.Python.3.13"
        $pythonExecutable = Find-AlertPython
    }
    if (-not $pythonExecutable) {
        throw "Python was installed but was not found. Open a new PowerShell window and rerun this command."
    }
    $setupArguments = @((Join-Path $PSScriptRoot "setup_github.py"), "--repo-name", $RepoName)
    if ($Private) { $setupArguments += "--private" }
    if ($NoEveryone) { $setupArguments += "--no-everyone" }
    if ($UpdateWebhook) { $setupArguments += "--update-webhook" }
    if ($NoWait) { $setupArguments += "--no-wait" }
    & $pythonExecutable @setupArguments
    exit $LASTEXITCODE
} catch {
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
