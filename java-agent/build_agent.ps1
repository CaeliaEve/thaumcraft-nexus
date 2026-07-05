param(
    [string]$OutputDir = "$PSScriptRoot\build"
)

$ErrorActionPreference = "Stop"

$srcDir = Join-Path $PSScriptRoot "src\main\java"
$classesDir = Join-Path $OutputDir "classes"
$manifestPath = Join-Path $OutputDir "MANIFEST.MF"
$jarPath = Join-Path $OutputDir "thaum-nexus-agent.jar"
$latestPathFile = Join-Path $OutputDir "latest-agent.path"

New-Item -ItemType Directory -Force -Path $classesDir | Out-Null

function Resolve-Tool([string]$toolName) {
    if ($env:JAVA_HOME) {
        $candidate = Join-Path $env:JAVA_HOME "bin\$toolName.exe"
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    $cmd = Get-Command $toolName -ErrorAction Stop
    return $cmd.Source
}

$javac = Resolve-Tool "javac"
$jar = Resolve-Tool "jar"

$javaHomeFromJavac = Split-Path (Split-Path $javac -Parent) -Parent
$toolsJarCandidates = @()
if ($env:JAVA_HOME) {
    $toolsJarCandidates += Join-Path $env:JAVA_HOME "lib\tools.jar"
}
$toolsJarCandidates += Join-Path $javaHomeFromJavac "lib\tools.jar"
$toolsJar = $toolsJarCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

$sources = Get-ChildItem -Path $srcDir -Recurse -Filter "*.java" | ForEach-Object { $_.FullName }
if (-not $sources) {
    throw "No Java sources found under $srcDir"
}

$compileArgs = @("-encoding", "UTF-8", "-source", "1.8", "-target", "1.8")
if ($toolsJar) {
    $compileArgs += @("-cp", $toolsJar)
}
$compileArgs += @("-d", $classesDir)
$compileArgs += $sources

& $javac @compileArgs
if ($LASTEXITCODE -ne 0) {
    throw "javac failed with exit code $LASTEXITCODE"
}

@"
Manifest-Version: 1.0
Agent-Class: thaumnexus.agent.ThaumNexusAgentV3
Premain-Class: thaumnexus.agent.ThaumNexusAgentV3
Can-Redefine-Classes: false
Can-Retransform-Classes: false
Main-Class: thaumnexus.agent.ThaumNexusAttacher

"@ | Set-Content -Encoding ASCII -Path $manifestPath

if (Test-Path $jarPath) {
    try {
        Remove-Item -Force $jarPath -ErrorAction Stop
    } catch {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $jarPath = Join-Path $OutputDir "thaum-nexus-agent-$stamp.jar"
    }
}
& $jar cfm $jarPath $manifestPath -C $classesDir .
if ($LASTEXITCODE -ne 0) {
    throw "jar failed with exit code $LASTEXITCODE"
}

$jarPath | Set-Content -Encoding UTF8 -Path $latestPathFile
Write-Output $jarPath

