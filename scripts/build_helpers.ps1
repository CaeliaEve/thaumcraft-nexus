function Invoke-JavaAgentBuild {
    param([string]$Script, [string]$OutputDir)
    & powershell -NoProfile -ExecutionPolicy Bypass -File $Script -OutputDir $OutputDir
    if ($LASTEXITCODE -ne 0) {
        throw "Java Agent build failed with exit code $LASTEXITCODE. Existing jars will not be reused."
    }
}
