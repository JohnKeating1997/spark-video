param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $BlArgs
)

$ErrorActionPreference = "Stop"
if ($null -eq $BlArgs -or $BlArgs.Count -eq 0) {
    $BlArgs = @($args)
}

function Quote-WindowsArgument($arg) {
    $s = [string]$arg
    if ($s -notmatch '[\s"]') { return $s }
    return '"' + ($s -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

$realBl = Get-Command bl.cmd -ErrorAction SilentlyContinue
if (-not $realBl) { $realBl = Get-Command bl.exe -ErrorAction SilentlyContinue }
if (-not $realBl) { $realBl = Get-Command bl -ErrorAction SilentlyContinue }
if (-not $realBl) {
    Write-Error "scripts/bl.ps1: real 'bl' CLI not found in PATH. Install with: npm install -g bailian-cli"
    exit 127
}
$realBlPath = if ($realBl.Path) { $realBl.Path } else { $realBl.Source }
if (-not $realBlPath) {
    Write-Error "scripts/bl.ps1: could not resolve the real 'bl' executable path"
    exit 127
}

$projectsRoot = if ($env:VIDEOGEN_PROJECTS_DIR) { $env:VIDEOGEN_PROJECTS_DIR } else { ".\projects" }
if ($env:SPARK_VIDEO_PROJECT -and $env:SPARK_VIDEO_EPISODE) {
    $ep = $env:SPARK_VIDEO_EPISODE -replace "^episode-", ""
    $epDir = Join-Path (Join-Path $projectsRoot $env:SPARK_VIDEO_PROJECT) "episode-$ep"
    $logDir = if ($env:SPARK_VIDEO_LOG_DIR) { $env:SPARK_VIDEO_LOG_DIR } else { Join-Path $epDir "logs" }
} else {
    $logDir = if ($env:SPARK_VIDEO_LOG_DIR) { $env:SPARK_VIDEO_LOG_DIR } else { "logs" }
}
New-Item -ItemType Directory -Force -Path (Join-Path $logDir "raw") | Out-Null

$ts = [DateTimeOffset]::UtcNow
$tsIso = $ts.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
$tsStamp = $ts.ToString("yyyyMMddTHHmmss")
$shotLabel = if ($env:SPARK_VIDEO_SHOT) { $env:SPARK_VIDEO_SHOT } else { "noshot" }
$rawStdout = Join-Path $logDir "raw\$tsStamp-$shotLabel.stdout"
$rawStderr = Join-Path $logDir "raw\$tsStamp-$shotLabel.stderr"

$stdinPayload = $null
if (-not [Console]::IsInputRedirected) {
    $stdinPayload = $null
} else {
    $stdinPayload = [Console]::In.ReadToEnd()
}

$started = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$psi = [System.Diagnostics.ProcessStartInfo]::new()
$psi.FileName = $realBlPath
if ($null -ne $psi.ArgumentList) {
    foreach ($arg in $BlArgs) { [void]$psi.ArgumentList.Add($arg) }
} else {
    $psi.Arguments = ($BlArgs | ForEach-Object { Quote-WindowsArgument $_ }) -join " "
}
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.RedirectStandardInput = $stdinPayload -ne $null
$psi.UseShellExecute = $false

$proc = [System.Diagnostics.Process]::Start($psi)
if ($stdinPayload -ne $null) {
    $proc.StandardInput.Write([string]$stdinPayload)
    $proc.StandardInput.Close()
}
$stdout = $proc.StandardOutput.ReadToEnd()
$stderr = $proc.StandardError.ReadToEnd()
$stdout = if ($null -eq $stdout) { "" } else { $stdout }
$stderr = if ($null -eq $stderr) { "" } else { $stderr }
$proc.WaitForExit()
$ended = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

[IO.File]::WriteAllText($rawStdout, $stdout, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($rawStderr, $stderr, [Text.UTF8Encoding]::new($false))
Write-Output $stdout
if ($stderr) { [Console]::Error.Write($stderr) }

$logTarget = if ($env:SPARK_VIDEO_PROJECT -and $env:SPARK_VIDEO_EPISODE) {
    Join-Path $logDir "model_calls.jsonl"
} else {
    Join-Path $logDir "_unattributed.jsonl"
}

$model = $null
for ($i = 0; $i -lt $BlArgs.Count - 1; $i++) {
    if ($BlArgs[$i] -eq "--model") {
        $model = $BlArgs[$i + 1]
        break
    }
}

$attempt = $null
if ($env:SPARK_VIDEO_ATTEMPT -match "^\d+$") { $attempt = [int]$env:SPARK_VIDEO_ATTEMPT }

$record = [ordered]@{
    ts = $tsIso
    project = $env:SPARK_VIDEO_PROJECT
    episode = $env:SPARK_VIDEO_EPISODE
    shot = $env:SPARK_VIDEO_SHOT
    phase = $env:SPARK_VIDEO_PHASE
    attempt = $attempt
    cmd = @("bl") + $BlArgs
    stdin = $stdinPayload
    model = $model
    duration_ms = [int]($ended - $started)
    exit_code = $proc.ExitCode
    stdout_excerpt = if ($stdout.Length -gt 4096) { $stdout.Substring(0, 4096) } else { $stdout }
    stderr_excerpt = if ($stderr.Length -gt 2048) { $stderr.Substring(0, 2048) } else { $stderr }
    stdout_full_path = $rawStdout
    stderr_full_path = $rawStderr
}
($record | ConvertTo-Json -Compress -Depth 8) | Add-Content -Encoding UTF8 $logTarget

exit $proc.ExitCode
