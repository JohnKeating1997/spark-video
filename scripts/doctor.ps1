param()

$ErrorActionPreference = "Continue"
$ok = $true

function Good($message) { Write-Host "  OK $message" }
function WarnCheck($message) {
    Write-Host "  WARN $message"
    $script:ok = $false
}
function Note($message) { Write-Host "  NOTE $message" }
function ErrCheck($message) {
    Write-Host "  FAIL $message"
    $script:ok = $false
}

function First-Line($text) {
    if ($null -eq $text) { return "" }
    return (($text -split "`r?`n") | Select-Object -First 1)
}

function Find-Exe($name, $fallbackPattern) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $wingetRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if ($fallbackPattern -and (Test-Path $wingetRoot)) {
        $found = Get-ChildItem -Path $wingetRoot -Recurse -Filter $fallbackPattern -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

function Invoke-Version($exe, $versionArgs) {
    $out = & $exe @versionArgs 2>&1 | Out-String
    return First-Line $out
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

Write-Host "spark-video doctor"
Write-Host "=================="

Write-Host "[bl CLI]"
$blCmd = Get-Command bl -ErrorAction SilentlyContinue
if ($blCmd) {
    $ver = First-Line (& bl --version 2>&1 | Out-String)
    if (-not $ver) { $ver = $blCmd.Source }
    Good "bl found ($ver)"
    & bl auth status *> $null
    if ($LASTEXITCODE -eq 0) {
        Good "bl auth OK"
    } else {
        WarnCheck "bl auth NOT logged in - run: bl auth login"
    }
} else {
    ErrCheck "bl not found. Install: npm install -g bailian-cli"
    ErrCheck "then run: npx skills add modelstudioai/skills --all -g"
}

Write-Host "[ffmpeg]"
foreach ($bin in @("ffmpeg", "ffprobe")) {
    $exe = Find-Exe $bin "$bin.exe"
    if ($exe) {
        $ver = Invoke-Version $exe @("-version")
        Good "$bin found ($ver)"
    } else {
        ErrCheck "$bin not found. Install: winget install --exact --id Gyan.FFmpeg"
    }
}

Write-Host "[uv]"
$uvExe = Find-Exe "uv" "uv.exe"
if ($uvExe) {
    $ver = Invoke-Version $uvExe @("--version")
    Good "uv found ($ver)"
} else {
    ErrCheck "uv not found. Install: winget install --exact --id astral-sh.uv"
}

Write-Host "[scripts/bl wrapper]"
if (Test-Path (Join-Path $scriptDir "bl.ps1")) {
    Good "scripts/bl.ps1 present"
} else {
    ErrCheck "scripts/bl.ps1 missing"
}
if (Test-Path (Join-Path $scriptDir "bl")) {
    Good "scripts/bl present for Unix-like systems"
} else {
    ErrCheck "scripts/bl missing"
}

Write-Host "[python]"
$pythonOk = $false
foreach ($candidate in @("python3", "python", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    $prefixArgs = if ($candidate -eq "py") { @("-3") } else { @() }
    $py = & $cmd.Source @prefixArgs -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
    $parts = $py -split "\."
    if ($parts.Length -ge 2 -and [int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) {
        Good "python found ($py)"
        $pythonOk = $true
        break
    }
}
if (-not $pythonOk) {
    if ($uvExe) {
        Note "python 3.10+ not found on PATH; use 'uv run ...' so uv can supply the script runtime"
    } else {
        ErrCheck "python 3.10+ not found"
    }
}

Write-Host "[shanyin craft references - optional]"
$shSwCandidates = @(
    (Join-Path $repoRoot "references\shanyin\screenwriting-master\SKILL.md"),
    (Join-Path $repoRoot "references\shanyin\screenwriting-master\screenwriting-master\SKILL.md")
)
$shDirCandidates = @(
    (Join-Path $repoRoot "references\shanyin\director-master\SKILL.md"),
    (Join-Path $repoRoot "references\shanyin\director-master\director-master\SKILL.md")
)
if (@($shSwCandidates | Where-Object { Test-Path $_ }).Count -gt 0) {
    Good "shanyin-screenwriting-master present"
} else {
    Write-Host "  optional not installed. Run: .\scripts\install-deps.ps1"
}
if (@($shDirCandidates | Where-Object { Test-Path $_ }).Count -gt 0) {
    Good "shanyin-director-master present"
} else {
    Write-Host "  optional not installed. Run: .\scripts\install-deps.ps1"
}

Write-Host "[sub-skills]"
foreach ($s in @("screenwriter", "director", "cast", "vfx-review", "clip-review", "episode")) {
    $f = Join-Path $repoRoot "references\spark-video-$s\SKILL.md"
    if (Test-Path $f) {
        Good "spark-video-$s SKILL.md present"
    } else {
        ErrCheck "spark-video-$s SKILL.md MISSING"
    }
}

Write-Host ""
if ($ok) {
    Write-Host "All checks passed. spark-video is ready."
    exit 0
}

Write-Host "Some checks failed. Fix the FAIL items above before running the pipeline."
exit 1
