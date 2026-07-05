param(
    [switch]$SkipPyInstallerInstall,
    [switch]$SkipJavaAgentBuild
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistRoot = Join-Path $ProjectRoot "dist"
$AppDist = Join-Path $DistRoot "ThaumcraftNexus"
$PyInstallerBuild = Join-Path $ProjectRoot "build\pyinstaller"
$SpecPath = Join-Path $PyInstallerBuild "spec"
$WorkPath = Join-Path $PyInstallerBuild "work"

function Resolve-PythonCommand {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @{ Exe = $python.Source; Args = @() }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @{ Exe = $py.Source; Args = @("-3") }
    }

    throw "Python was not found. Install Python 3 first."
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$Arguments
    )

    & $Python.Exe @($Python.Args + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

Push-Location $ProjectRoot
try {
    $Python = Resolve-PythonCommand

    Invoke-Python $Python @("-m", "pip", "install", "-r", "requirements.txt")

    if (-not $SkipPyInstallerInstall) {
        & $Python.Exe @($Python.Args + @("-m", "PyInstaller", "--version")) | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Invoke-Python $Python @("-m", "pip", "install", "pyinstaller")
        }
    }

    $AgentJar = Join-Path $ProjectRoot "java-agent\build\thaum-nexus-agent.jar"
    if (-not $SkipJavaAgentBuild) {
        try {
            powershell -NoProfile -ExecutionPolicy Bypass -File ".\java-agent\build_agent.ps1"
        } catch {
            if (-not (Test-Path $AgentJar)) {
                throw
            }
            Write-Warning "Java Agent build failed, using existing jar: $AgentJar"
        }
    }
    if (-not (Test-Path $AgentJar)) {
        throw "Java Agent jar was not found: $AgentJar"
    }

    New-Item -ItemType Directory -Force -Path $SpecPath, $WorkPath | Out-Null

    $DataDir = Join-Path $ProjectRoot "data"
    $ImageDir = Join-Path $ProjectRoot "image"
    $EntryScript = Join-Path $ProjectRoot "tools\thaum_nexus_gui.py"

    $AddData = @(
        "$DataDir;data",
        "$ImageDir;image",
        "$AgentJar;java-agent"
    )

    $PyInstallerArgs = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name", "ThaumcraftNexus",
        "--specpath", $SpecPath,
        "--distpath", $DistRoot,
        "--workpath", $WorkPath
    )
    foreach ($Item in $AddData) {
        $PyInstallerArgs += @("--add-data", $Item)
    }
    $PyInstallerArgs += @($EntryScript)

    Invoke-Python $Python $PyInstallerArgs

    if (-not (Test-Path (Join-Path $AppDist "ThaumcraftNexus.exe"))) {
        throw "Build finished but ThaumcraftNexus.exe was not found under $AppDist"
    }

    $PortableReadme = @"
Thaumcraft Nexus 便携版

使用方式：
1. 确认本机已安装可用于 GTNH 的 Java 8 JDK，并且 JAVA_HOME 指向该 JDK。
2. 启动 GT New Horizons，进入游戏并打开神秘时代研究台。
3. 双击 ThaumcraftNexus.exe。
4. 在界面中读取当前笔记、自动放置，或使用轮椅模式批量处理。

注意：
- 本工具是外部辅助程序，不需要把文件放进整合包 mods 目录。
- 运行时生成的 JSON、图片和设置会写入本目录下的 runtime 文件夹。
"@
    $PortableReadme | Set-Content -Encoding UTF8 -Path (Join-Path $AppDist "README_CN.txt")

    Write-Output ""
    Write-Output "Portable build complete:"
    Write-Output "  $AppDist"
    Write-Output "Start with:"
    Write-Output "  $AppDist\ThaumcraftNexus.exe"
}
finally {
    Pop-Location
}
