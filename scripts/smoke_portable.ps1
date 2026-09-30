param([Parameter(Mandatory=$true)][string]$AppDir)
$ErrorActionPreference = "Stop"
$app = (Resolve-Path -LiteralPath $AppDir).Path
$exe = Join-Path $app "ThaumcraftNexus.exe"
$process = Start-Process -FilePath $exe -ArgumentList "--self-test" -WorkingDirectory $app -PassThru -WindowStyle Hidden
try {
    if (-not $process.WaitForExit(60000)) {
        throw "Portable self-test timed out after 60 seconds"
    }
    if ($process.ExitCode -ne 0) {
        throw "Portable self-test failed with exit code $($process.ExitCode)"
    }
    Write-Output "Portable resource self-test passed: $exe"
} finally {
    if (-not $process.HasExited) { $process.Kill() }
    $process.Dispose()
}
