<#
.SYNOPSIS
    Build dist\qtRequestory.exe: test, package, smoke-test, report.

.DESCRIPTION
    Four steps, in this order, any of which stops the build:

      1. the interpreter really is the repository venv (not the Microsoft Store
         python, whose sandboxed %LOCALAPPDATA% redirection produces an exe that
         behaves differently from every colleague's machine);
      2. the whole pytest suite passes - shipping an exe built from a red tree
         is how a broken build reaches someone else's desktop;
      3. pyinstaller qtRequestory.spec;
      4. the produced exe is actually run: --version, --task status, and --find
         against a throwaway config in %TEMP% pointing at an EMPTY mirror, which
         must answer "nothing found" with exit code 1.

    Step 4 exists because the ways this exe breaks are silent. The build is
    always green; the exe starts, draws its window and shows an empty page.

.PARAMETER SkipTests
    Skip step 2. For iterating on the spec only - never for a build you hand out.

.PARAMETER KeepBuildDir
    Do not pass --clean to PyInstaller (a much faster rebuild, but it reuses the
    previous analysis; use it while editing the spec, not for a release).

.PARAMETER Python
    The interpreter to build with. Defaults to .venv\Scripts\python.exe next to
    this repository - which does not exist in a git worktree, where the venv
    lives in the main checkout; pass it explicitly there. It is still checked
    (real venv, not the Store python) whichever way it arrives.

.EXAMPLE
    .\scripts\build.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$KeepBuildDir,
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
if (-not $Python) { $Python = Join-Path $Repo '.venv\Scripts\python.exe' }
$Spec = Join-Path $Repo 'qtRequestory.spec'
$Exe = Join-Path $Repo 'dist\qtRequestory.exe'

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

# The exe is built with console=False. Two consequences shape this helper:
#   * giving it a PIPE for stdout hangs it forever, so the output goes to files;
#   * Start-Process -PassThru leaves ExitCode empty unless the process handle is
#     touched before waiting - hence the '$null = $p.Handle' line, which is not
#     dead code however much it looks like it.
# Every call has a timeout: a windowed exe that decides to wait for something
# would otherwise hang the build with nothing on screen.
function Invoke-Exe {
    param(
        [Parameter(Mandatory)][string]$Path,
        [string[]]$Arguments = @(),
        [int]$TimeoutMs = 120000
    )
    $out = [System.IO.Path]::GetTempFileName()
    $err = [System.IO.Path]::GetTempFileName()
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $start = @{
            FilePath               = $Path
            RedirectStandardOutput = $out
            RedirectStandardError  = $err
            PassThru               = $true
            WindowStyle            = 'Hidden'
        }
        # Start-Process joins ArgumentList with spaces and quotes nothing, so a
        # path with a space in it (%TEMP% under "C:\Users\Mario Rossi\...") would
        # arrive as two arguments.
        if ($Arguments.Count -gt 0) {
            $start['ArgumentList'] = @($Arguments | ForEach-Object {
                if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
            })
        }
        $p = Start-Process @start
        $null = $p.Handle
        if (-not $p.WaitForExit($TimeoutMs)) {
            $p.Kill(); $p.WaitForExit()
            throw "$Path $($Arguments -join ' ') did not exit within $([int]($TimeoutMs / 1000)) s"
        }
        $watch.Stop()
        [pscustomobject]@{
            ExitCode = $p.ExitCode
            Output   = (Get-Content $out -Raw -ErrorAction SilentlyContinue)
            Error    = (Get-Content $err -Raw -ErrorAction SilentlyContinue)
            Millis   = $watch.ElapsedMilliseconds
        }
    }
    finally {
        Remove-Item $out, $err -Force -ErrorAction SilentlyContinue
    }
}

# PowerShell 5.1 turns every stderr line of a native command into an ErrorRecord
# as soon as the caller redirects the streams (`.\build.ps1 *>&1 | Tee-Object`),
# and with $ErrorActionPreference = 'Stop' that aborts the build on PyInstaller's
# perfectly ordinary INFO logging - which it writes to stderr. The exit code is
# the only thing worth believing here, so that is what this checks.
function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$File,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory)][string]$What
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $File @Arguments } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}

function Assert-ExitCode {
    param($Result, [int]$Expected, [string]$What)
    if ($Result.ExitCode -ne $Expected) {
        Write-Host $Result.Output
        Write-Host $Result.Error -ForegroundColor Red
        throw "$What exited with $($Result.ExitCode), expected $Expected"
    }
}

# Everything below assumes the repository root is the working directory: pytest
# resolves testpaths/pythonpath from it, and PyInstaller writes build\ and dist\
# relative to it. Running the script from anywhere else must not scatter them.
Push-Location $Repo
try {

# ---------------------------------------------------------------- 1. venv ---

Write-Step 'Checking the build interpreter'
if (-not (Test-Path $Python)) {
    throw "Repository venv not found at $Python. Create it with: python -m venv .venv; .venv\Scripts\python -m pip install -e `".[ui,dev]`""
}
$probe = & $Python -c "import sys, PyInstaller, PySide6; print(sys.prefix); print(sys.base_prefix); print(sys.version.split()[0]); print(PyInstaller.__version__); print(PySide6.__version__)"
if ($LASTEXITCODE -ne 0) { throw "The venv is missing PyInstaller or PySide6: $Python -m pip install -e `".[ui,dev]`"" }
$prefix, $basePrefix, $pyVersion, $pyiVersion, $qtVersion = $probe

if ($prefix -eq $basePrefix) { throw "$Python is not a virtual environment (sys.prefix == sys.base_prefix)." }
# The Store interpreter installs under ...\WindowsApps and redirects writes to a
# per-app %LOCALAPPDATA%; an exe built from it resolves the app directory
# differently from the one the colleagues will run.
if ($basePrefix -like '*WindowsApps*') { throw "The venv was created from the Microsoft Store python ($basePrefix). Rebuild it from the python.org interpreter." }
Write-Host "    python      $pyVersion  ($prefix)"
Write-Host "    PyInstaller $pyiVersion"
Write-Host "    PySide6     $qtVersion"

# --------------------------------------------------------------- 2. tests ---

if ($SkipTests) {
    Write-Step 'Tests SKIPPED (-SkipTests) - do not hand this exe to anyone'
}
else {
    Write-Step 'Running the test suite'
    Invoke-Native -File $Python -Arguments @('-m', 'pytest') -What 'pytest'
}

# ------------------------------------------------------------- 3. package ---

# The Windows version resource is stamped from qtrequestory.__version__ rather
# than written down a second time. qtRequestory.spec does this too, so a bare
# `pyinstaller qtRequestory.spec` still works; doing it here as well costs
# nothing and puts the version being built on screen before the build starts.
Write-Step 'Generating the version resource'
Invoke-Native -File $Python -Arguments @((Join-Path $PSScriptRoot 'make_version_info.py')) -What 'make_version_info.py'

Write-Step 'Building with PyInstaller'
# `python -m PyInstaller`, not `pyinstaller`: the console script on PATH may well
# belong to a different environment.
$pyiArgs = @('-m', 'PyInstaller', '--noconfirm', $Spec)
if (-not $KeepBuildDir) { $pyiArgs += '--clean' }
Invoke-Native -File $Python -Arguments $pyiArgs -What 'PyInstaller'
if (-not (Test-Path $Exe)) { throw "PyInstaller reported success but $Exe does not exist." }

# ---------------------------------------------------------- 4. smoke test ---

Write-Step 'Smoke-testing the built exe'

# A throwaway app directory and configuration, so the smoke test never reads or
# writes the real config, the real mirror or the real logs of whoever is building.
$sandbox = Join-Path $env:TEMP "qtrequestory-build-$PID"
$mirror = Join-Path $sandbox 'mirror-vuoto'
$home_ = Join-Path $sandbox 'app-home'
New-Item -ItemType Directory -Force -Path $mirror, $home_ | Out-Null
$configPath = Join-Path $sandbox 'config.json'
$configJson = '{"schema_version": 1, "mirror_root": "' + $mirror.Replace('\', '\\') + '", "environments": [{"name": "smoke", "url": "https://esempio.invalido/", "enabled": true}], "default_window_days": 1}'
Set-Content -Path $configPath -Value $configJson -Encoding utf8

$previousHome = $env:QTREQUESTORY_HOME
$env:QTREQUESTORY_HOME = $home_
try {
    $expected = & $Python -c "import sys; sys.path.insert(0, r'$Repo\src'); import qtrequestory; print(qtrequestory.__version__)"

    $version = Invoke-Exe -Path $Exe -Arguments @('--version')
    Assert-ExitCode $version 0 '--version'
    $printed = ($version.Output -replace '\s+', ' ').Trim()
    if ($printed -ne "qtRequestory $expected") {
        throw "--version printed '$printed', expected 'qtRequestory $expected'"
    }
    Write-Host "    --version      $printed   ($($version.Millis) ms, cold start included)"

    # Exit 1 = "no task registered", which is the answer on a machine that has
    # not installed it yet; 0 = registered. Anything else is a real failure.
    $task = Invoke-Exe -Path $Exe -Arguments @('--task', 'status')
    if ($task.ExitCode -notin 0, 1) {
        Write-Host $task.Output
        throw "--task status exited with $($task.ExitCode)"
    }
    Write-Host "    --task status  exit $($task.ExitCode) ($($task.Millis) ms)"

    # The real point of the smoke test: the headless search path end to end
    # (config -> index -> search) against an EMPTY mirror, which must report
    # "nothing found" and exit 1 rather than crash or find something.
    $find = Invoke-Exe -Path $Exe -Arguments @(
        '--config', $configPath, '--find', '-e', 'smoke',
        '-k', 'SMOKE_TEST_KEY', '--days', '1', '--no-open')
    Assert-ExitCode $find 1 '--find on an empty mirror'
    if ($find.Output -notmatch 'nessuna chiamata trovata') {
        Write-Host $find.Output
        throw "--find did not print the 'nothing found' message"
    }
    Write-Host "    --find         exit 1, 'nessuna chiamata trovata' ($($find.Millis) ms)"

    Write-Step 'Cold start'
    $runs = 1..3 | ForEach-Object { (Invoke-Exe -Path $Exe -Arguments @('--version')).Millis }
    $average = [int](($runs | Measure-Object -Average).Average)
    Write-Host "    --version x3   $($runs -join ' ms, ') ms  (average $average ms)"
    Write-Host "    onefile unpacks the whole payload into %TEMP% on every run, including every scheduled --sync."
}
finally {
    # Assigning $null would leave the variable set to the empty string.
    if ($null -eq $previousHome) { Remove-Item Env:\QTREQUESTORY_HOME -ErrorAction SilentlyContinue }
    else { $env:QTREQUESTORY_HOME = $previousHome }
    Remove-Item -Recurse -Force $sandbox -ErrorAction SilentlyContinue
}

# ------------------------------------------------------------------ done ---

$size = (Get-Item $Exe).Length
Write-Step 'Done'
Write-Host ("    {0}" -f $Exe)
Write-Host ("    {0:N0} bytes ({1:N2} MB), built {2}" -f $size, ($size / 1MB), (Get-Item $Exe).LastWriteTime)
Write-Host ''
Write-Host '    Next: copy it to %LOCALAPPDATA%\qtRequestory\bin\ and run "qtRequestory.exe --task install".'
Write-Host '    Never schedule the copy in dist\ - the next build replaces it.'

}
finally {
    Pop-Location
}
