param()

$ErrorActionPreference = "Continue"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspace = (Get-Location).Path
$targetRoot = if ($env:SPARK_VIDEO_SHANYIN_DIR) {
    $env:SPARK_VIDEO_SHANYIN_DIR
} else {
    Join-Path $workspace ".spark-video\references\shanyin"
}
New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null

function Clone-Or-Pull($url, $target) {
    $path = Join-Path $targetRoot $target
    if (Test-Path (Join-Path $path ".git")) {
        Write-Host "[$target] already cloned - pulling latest"
        Push-Location $path
        git pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "pull failed for $target (continuing)"
        }
        Pop-Location
        return
    }

    Write-Host "[$target] cloning $url"
    git clone --depth 1 $url $path
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  OK cloned"
    } else {
        Write-Warning "clone failed - stage instructions will fall back to bundled guidance"
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $path
    }
}

Clone-Or-Pull "https://github.com/Shanyin-ai/shanyin-screenwriting-master.git" "screenwriting-master"
Clone-Or-Pull "https://github.com/Shanyin-ai/shanyin-director-master.git" "director-master"

Write-Host ""
Write-Host "Done. Verify with: Get-ChildItem $targetRoot"
