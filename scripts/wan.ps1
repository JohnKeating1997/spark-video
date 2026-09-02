param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $WanArgs
)

$ErrorActionPreference = "Stop"
if ($null -eq $WanArgs -or $WanArgs.Count -eq 0) {
    $WanArgs = @($args)
}

$realWan = Get-Command wan.cmd -ErrorAction SilentlyContinue
if (-not $realWan) { $realWan = Get-Command wan.exe -ErrorAction SilentlyContinue }
if (-not $realWan) { $realWan = Get-Command wan -ErrorAction SilentlyContinue }
if (-not $realWan) {
    Write-Error "scripts/wan.ps1: 'wan' CLI not found in PATH. Install @wan-ai/cli first."
    exit 127
}

$realWanPath = if ($realWan.Path) { $realWan.Path } else { $realWan.Source }
& $realWanPath @WanArgs
exit $LASTEXITCODE
