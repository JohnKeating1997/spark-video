param(
    [switch] $Quick,
    [switch] $Full,
    [switch] $Json,
    [switch] $Narration,
    [switch] $InstallPlan,
    [switch] $Help
)

$ErrorActionPreference = "Continue"
$mode = if ($InstallPlan) { "install-plan" } elseif ($Quick) { "quick" } else { "full" }
$checkMode = if ($InstallPlan) { "quick" } else { $mode }
$ok = $true
$checks = [System.Collections.Generic.List[object]]::new()
$actions = [System.Collections.Generic.List[object]]::new()

$missingWan = $false
$missingWanAuth = $false
$missingWanWrapper = $false
$missingBl = $false
$missingBlAuth = $false
$missingFfmpeg = $false
$missingUv = $false
$missingPython = $false
$missingScriptBl = $false
$missingStageRefs = $false
$missingShanyin = $false
$wanSite = "intl"
$wanSiteSource = "default"
$videogenRegion = ""
$wanVideoModel = ""
$selectedProvider = "wan-cli"
$wanRequired = $true

function Show-Usage {
    @"
spark-video doctor

Usage:
  doctor.ps1 [-Full] [-Json] [-Narration]
  doctor.ps1 -Quick [-Json] [-Narration]
  doctor.ps1 -InstallPlan [-Json] [-Narration]

Modes:
  -Quick        Fast readiness check for agents.
  -Full         Human-readable dependency report. This is the default.
  -InstallPlan  Print commands that would repair missing dependencies.
  -Json         Emit one JSON object and no human prose.
  -Narration    Require optional bl + authentication for narration TTS.
"@
}

if ($Help) {
    Show-Usage
    exit 0
}

function First-Line($text) {
    if ($null -eq $text) { return "" }
    return (($text -split "`r?`n") | Select-Object -First 1)
}

function Get-WorkspaceEnvValue($name) {
    $processValue = [Environment]::GetEnvironmentVariable($name, "Process")
    if ($processValue) { return $processValue.Trim() }

    $envFile = Join-Path (Get-Location).Path ".env"
    if (-not (Test-Path $envFile)) { return "" }
    $escapedName = [regex]::Escape($name)
    foreach ($line in Get-Content $envFile -ErrorAction SilentlyContinue) {
        if ($line -match "^\s*(?:export\s+)?$escapedName\s*=\s*(.*?)\s*(?:#.*)?$") {
            return $matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ""
}

$selectedProvider = Get-WorkspaceEnvValue "SPARK_VIDEO_PROVIDER"
if (-not $selectedProvider) { $selectedProvider = Get-WorkspaceEnvValue "VIDEOGEN_VIDEO_PROVIDER" }
if (-not $selectedProvider) { $selectedProvider = "wan-cli" }
$selectedProvider = switch ($selectedProvider.ToLowerInvariant()) {
    { $_ -in @("wan", "wan_cli") } { "wan-cli"; break }
    "happyhorse" { "bl"; break }
    "seedance" { "seedance2"; break }
    default { $selectedProvider.ToLowerInvariant() }
}
$wanRequired = $selectedProvider -eq "wan-cli"

function Find-CommandPath($name, $fallbackPattern) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $(if ($cmd.Path) { $cmd.Path } else { $cmd.Source }) }

    $wingetRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if ($fallbackPattern -and (Test-Path $wingetRoot)) {
        $found = Get-ChildItem -Path $wingetRoot -Recurse -Filter $fallbackPattern -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

function Add-Check($id, $status, [bool] $required, $message, $fix = "") {
    if ($status -eq "fail" -and $required) { $script:ok = $false }
    [void]$script:checks.Add([ordered]@{
        id = $id
        status = $status
        required = $required
        message = $message
        fix = $fix
    })

    if ($script:Json -or $script:InstallPlan) { return }
    $mark = switch ($status) {
        "pass" { "OK" }
        "fail" { "FAIL" }
        "warn" { "WARN" }
        default { "NOTE" }
    }
    Write-Host "  $mark $message"
}

function Add-Action($id, [bool] $required, $reason, [string[]] $commands) {
    [void]$script:actions.Add([ordered]@{
        id = $id
        required = $required
        reason = $reason
        commands = $commands
    })
}

function Section($title) {
    if (-not $script:Json -and -not $script:InstallPlan) { Write-Host $title }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$workspace = (Get-Location).Path
$shanyinRoot = if ($env:SPARK_VIDEO_SHANYIN_DIR) {
    $env:SPARK_VIDEO_SHANYIN_DIR
} else {
    Join-Path $workspace ".spark-video\references\shanyin"
}

if (-not $Json -and -not $InstallPlan) {
    Write-Host $(if ($checkMode -eq "quick") { "spark-video doctor (quick)" } else { "spark-video doctor" })
    Write-Host "=================="
}

Section "[wan CLI]"
$wanExe = Find-CommandPath "wan" "wan.exe"
if ($wanExe) {
    if ($checkMode -eq "full") {
        $version = First-Line (& $wanExe --version 2>&1 | Out-String)
        Add-Check "wan" "pass" $wanRequired "wan found ($version)"
    } else {
        Add-Check "wan" "pass" $wanRequired "wan found"
    }

    $configText = (& $wanExe config show --output json 2>$null | Out-String)
    if ($LASTEXITCODE -eq 0) {
        try {
            $parsedConfig = $configText | ConvertFrom-Json
            $parsedSite = [string]$parsedConfig.site
            if ($parsedSite -in @("cn", "intl")) {
                $wanSite = $parsedSite
                $wanSiteSource = "config"
            }
        } catch {
            # Keep the international default when config output is not recognized.
        }
    }

    & $wanExe auth status --output json *> $null
    if ($LASTEXITCODE -eq 0) {
        Add-Check "wan-auth" "pass" $wanRequired "wan auth OK"
    } else {
        $missingWanAuth = $true
        Add-Check "wan-auth" $(if ($wanRequired) { "fail" } else { "warn" }) $wanRequired "wan auth NOT logged in" "Run: wan auth login --site $wanSite --output json"
    }
} else {
    $missingWan = $true
    Add-Check "wan" $(if ($wanRequired) { "fail" } else { "warn" }) $wanRequired "wan not found" "Install @wan-ai/cli, then run wan auth login --site intl --output json"
}

Section "[runtime profile]"
Add-Check "video-provider" "pass" $true "selected video provider: $selectedProvider"
if ($wanSiteSource -eq "config") {
    Add-Check "wan-site" "pass" $true "wan account site: $wanSite"
} else {
    Add-Check "wan-site" "warn" $false "wan account site: intl (default; current site was not recognized)"
}

$videogenRegion = Get-WorkspaceEnvValue "VIDEOGEN_REGION"
if (-not $videogenRegion) { $videogenRegion = "beijing" }
Add-Check "videogen-region" "info" $false "DashScope region: $videogenRegion"

$wanVideoModel = Get-WorkspaceEnvValue "SPARK_VIDEO_WAN_VIDEO_MODEL"
if (-not $wanVideoModel) { $wanVideoModel = Get-WorkspaceEnvValue "VIDEOGEN_WAN_VIDEO_MODEL" }
if (-not $wanVideoModel) { $wanVideoModel = "wan3.0" }
$wanVideoModel = switch ($wanVideoModel.ToLowerInvariant()) {
    { $_ -in @("3.0", "3_0", "wan3_0") } { "wan3.0"; break }
    { $_ -in @("2.7", "2_7", "wan2_7") } { "wan2.7"; break }
    default { $wanVideoModel }
}
if ($wanVideoModel -in @("wan3.0", "wan2.7")) {
    Add-Check "wan-video-models" "pass" $wanRequired "spark-video wan-cli models: wan3.0, wan2.7 (selected: $wanVideoModel)"
} else {
    Add-Check "wan-video-models" $(if ($wanRequired) { "fail" } else { "warn" }) $wanRequired "unsupported selected wan-cli model: $wanVideoModel; available: wan3.0, wan2.7" "Set VIDEOGEN_WAN_VIDEO_MODEL to wan3.0 or wan2.7"
}
$wanWrapper = Join-Path $scriptDir "wan.ps1"
if (Test-Path $wanWrapper) {
    Add-Check "scripts-wan" "pass" $true "scripts/wan.ps1 present"
} else {
    $missingWanWrapper = $true
    Add-Check "scripts-wan" "fail" $true "scripts/wan.ps1 missing" "Reinstall spark-video from a complete skill package"
}

if ($selectedProvider -eq "seedance2") {
    $arkKey = Get-WorkspaceEnvValue "ARK_API_KEY"
    if (-not $arkKey) { $arkKey = Get-WorkspaceEnvValue "VOLCENGINE_API_KEY" }
    if ($arkKey) { Add-Check "ark-key" "pass" $true "Ark key configured for seedance2" }
    else { Add-Check "ark-key" "fail" $true "ARK_API_KEY missing for seedance2" "Set ARK_API_KEY in the workspace .env" }
}

Section "[bl CLI - required for bl rendering or narration]"
$blRequired = [bool]$Narration -or $selectedProvider -eq "bl"
$blExe = Find-CommandPath "bl" "bl.exe"
if ($blExe) {
    if ($checkMode -eq "full") {
        $version = First-Line (& $blExe --version 2>&1 | Out-String)
        Add-Check "bl" "pass" $blRequired "bl found ($version)"
    } else {
        Add-Check "bl" "pass" $blRequired "bl found"
    }
    & $blExe auth status *> $null
    if ($LASTEXITCODE -eq 0) {
        Add-Check "bl-auth" "pass" $blRequired "bl auth OK"
    } else {
        $missingBlAuth = $true
        if ($blRequired) {
            Add-Check "bl-auth" "fail" $true "bl auth NOT logged in; selected workflow needs bl" "Run: bl auth login"
        } else {
            Add-Check "bl-auth" "warn" $false "bl auth NOT logged in (optional: bl rendering, narration TTS, and clip review)" "Run: bl auth login"
        }
    }
} else {
    $missingBl = $true
    if ($blRequired) {
        Add-Check "bl" "fail" $true "bl not found; selected workflow needs bl" "Install bailian-cli, then authenticate with bl auth login"
    } else {
        Add-Check "bl" "warn" $false "bl not found (optional: bl rendering, narration TTS, and clip review)" "Install bailian-cli only if those features are needed"
    }
}

Section "[ffmpeg]"
foreach ($bin in @("ffmpeg", "ffprobe")) {
    $exe = Find-CommandPath $bin "$bin.exe"
    if ($exe) {
        if ($checkMode -eq "full") {
            $version = First-Line (& $exe -version 2>&1 | Out-String)
            Add-Check $bin "pass" $true "$bin found ($version)"
        } else {
            Add-Check $bin "pass" $true "$bin found"
        }
    } else {
        $missingFfmpeg = $true
        Add-Check $bin "fail" $true "$bin not found" "Install: winget install --exact --id Gyan.FFmpeg"
    }
}

Section "[uv]"
$uvExe = Find-CommandPath "uv" "uv.exe"
if ($uvExe) {
    if ($checkMode -eq "full") {
        $version = First-Line (& $uvExe --version 2>&1 | Out-String)
        Add-Check "uv" "pass" $true "uv found ($version)"
    } else {
        Add-Check "uv" "pass" $true "uv found"
    }
} else {
    $missingUv = $true
    Add-Check "uv" "fail" $true "uv not found" "Install: winget install --exact --id astral-sh.uv"
}

Section "[scripts/bl wrapper - optional]"
$blWrapper = Join-Path $scriptDir "bl.ps1"
if (Test-Path $blWrapper) {
    Add-Check "scripts-bl" "pass" $blRequired "scripts/bl.ps1 present"
} else {
    $missingScriptBl = $true
    if ($Narration) {
        Add-Check "scripts-bl" "fail" $true "scripts/bl.ps1 missing" "Reinstall spark-video from a complete skill package"
    } else {
        Add-Check "scripts-bl" "warn" $false "scripts/bl.ps1 missing (optional)" "Reinstall spark-video from a complete skill package"
    }
}

Section "[python]"
$pythonOk = $false
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $uvPython = (& uv python find ">=3.10" 2>$null | Select-Object -First 1)
    if ($uvPython -and (Test-Path $uvPython)) {
        $version = & $uvPython -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')" 2>$null
        Add-Check "python3" "pass" $true "uv Python runtime found ($version)"
        $pythonOk = $true
    }
}
if (-not $pythonOk) {
    $missingPython = $true
    Add-Check "python3" "fail" $true "uv could not resolve Python 3.10+" "Run: uv python install 3.12"
}

Section "[shanyin craft references - optional]"
foreach ($item in @(
    @{ id = "shanyin-screenwriting-master"; dir = "screenwriting-master" },
    @{ id = "shanyin-director-master"; dir = "director-master" }
)) {
    $repoDir = Join-Path $shanyinRoot $item.dir
    $skillBundle = Get-ChildItem -Path $repoDir -Filter "*.skill" -File -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($skillBundle) {
        Add-Check $item.id "pass" $false "$($item.id) present ($shanyinRoot)"
    } else {
        $missingShanyin = $true
        Add-Check $item.id "warn" $false "not installed at $shanyinRoot (optional)" "Run: & `"$scriptDir\install-deps.ps1`""
    }
}

Section "[stage references]"
foreach ($stage in @("screenwriter", "director", "cast", "vfx-review", "clip-review")) {
    $relativePath = if ($stage -eq "clip-review") {
        "references\spark-video-clip-review\instructions.md"
    } else {
        "references\spark-video-$stage.md"
    }
    $manifest = Join-Path $repoRoot $relativePath
    if (Test-Path $manifest) {
        Add-Check "spark-video-$stage" "pass" $true "spark-video-$stage instructions present"
    } else {
        $missingStageRefs = $true
        Add-Check "spark-video-$stage" "fail" $true "spark-video-$stage instructions MISSING" "Reinstall spark-video from a complete skill package"
    }
}

if ($InstallPlan) {
    $wanPackageManager = "npm"

    if ($missingWan -and $wanRequired) {
        Add-Action "wan" $true "wan-cli is the default image and video provider" @(
            "$wanPackageManager install --global @wan-ai/cli@latest",
            "wan auth login --site intl --output json"
        )
    }
    if ($missingWanAuth -and $wanRequired) {
        Add-Action "wan-auth" $true "wan-cli is installed but not authenticated" @("wan auth login --site $wanSite --output json")
    }
    if ($missingWanWrapper) {
        Add-Action "scripts-wan" $true "spark-video's Windows wan wrapper is missing" @("Reinstall spark-video from a complete skill package")
    }
    if ($missingBl) {
        Add-Action "bl" $blRequired "Bailian CLI: required for bl rendering or narration, and available for clip review" @(
            "npm install -g bailian-cli",
            "bl auth login"
        )
    }
    if ($missingBlAuth) {
        Add-Action "bl-auth" $blRequired "bl is installed but not authenticated" @("bl auth login")
    }
    if ($missingFfmpeg) {
        Add-Action "ffmpeg" $true "ffmpeg and ffprobe are required for video stitching" @("winget install --exact --id Gyan.FFmpeg")
    }
    if ($missingUv) {
        Add-Action "uv" $true "uv is required to run Python scripts with inline dependencies" @("winget install --exact --id astral-sh.uv")
    }
    if ($missingPython) {
        Add-Action "python3" $true "uv needs a Python 3.10+ runtime for the script toolchain" @("uv python install 3.12")
    }
    if ($missingScriptBl) {
        Add-Action "scripts-bl" $blRequired "spark-video's optional bl wrapper is missing" @("Reinstall spark-video from a complete skill package")
    }
    if ($missingStageRefs) {
        Add-Action "stage-references" $true "The installed spark-video package is incomplete" @("Reinstall spark-video from a complete skill package")
    }
    if ($missingShanyin) {
        Add-Action "shanyin-references" $false "Optional Shanyin craft references are not installed" @("& `"$scriptDir\install-deps.ps1`"")
    }

    $result = [ordered]@{
        ok = $ok
        mode = "install-plan"
        os = "windows"
        package_manager = "winget"
        actions = $actions
    }
} else {
    $result = [ordered]@{
        ok = $ok
        mode = $mode
        skill_dir = $repoRoot
        workspace = $workspace
        shanyin_dir = $shanyinRoot
        checks = $checks
    }
}

if ($Json) {
    $result | ConvertTo-Json -Depth 8 -Compress
} elseif ($InstallPlan) {
    Write-Host "Install plan"
    Write-Host "============"
    Write-Host "Ask the user before running each command."
    foreach ($action in $actions) {
        $label = if ($action.required) { "required" } else { "optional" }
        Write-Host "[$label] $($action.id): $($action.reason)"
        foreach ($command in $action.commands) { Write-Host "  $command" }
    }
} elseif ($ok) {
    Write-Host ""
    Write-Host "All required checks passed. spark-video is ready."
} else {
    Write-Host ""
    Write-Host "Some required checks failed. Fix the FAIL items above before running the pipeline."
}

if ($ok) { exit 0 }
exit 1
