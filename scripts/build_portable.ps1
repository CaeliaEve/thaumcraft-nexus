param(
    [switch]$SkipPyInstallerInstall,
    [switch]$SkipJavaAgentBuild,
    [string]$BundledJdkPath
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

function Get-PythonRuntimeDir {
    param(
        [hashtable]$Python
    )

    $runtimeDir = & $Python.Exe @($Python.Args + @("-c", "import pathlib, sys; print(pathlib.Path(sys.executable).resolve().parent)"))
    if ($LASTEXITCODE -ne 0 -or -not $runtimeDir) {
        throw "Failed to resolve Python runtime directory."
    }
    return [string]$runtimeDir
}

function Resolve-BundledJdk {
    param(
        [string]$Path
    )

    if (-not $Path) {
        return $null
    }

    $resolved = (Resolve-Path -LiteralPath $Path).Path
    $javaExe = Join-Path $resolved "bin\java.exe"
    $javaUnix = Join-Path $resolved "bin\java"
    $toolsJar = Join-Path $resolved "lib\tools.jar"

    if (-not (Test-Path $javaExe) -and -not (Test-Path $javaUnix)) {
        throw "Bundled JDK is missing bin\java.exe: $resolved"
    }
    $java = if (Test-Path $javaExe) { $javaExe } else { $javaUnix }
    $oldErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $versionText = (& $java -version 2>&1 | ForEach-Object { $_.ToString() }) -join "`n"
    } finally {
        $ErrorActionPreference = $oldErrorActionPreference
    }
    $major = $null
    if ($versionText -match '"1\.(\d+)') {
        $major = [int]$Matches[1]
    } elseif ($versionText -match '"(\d+)') {
        $major = [int]$Matches[1]
    }
    if (-not $major) {
        throw "Failed to determine bundled JDK major version: $resolved"
    }
    if ($major -le 8 -and -not (Test-Path $toolsJar)) {
        throw "Bundled Java 8 JDK must include lib\tools.jar: $resolved"
    }
    if ($major -ge 9) {
        $modules = & $java --list-modules 2>$null
        if ($LASTEXITCODE -ne 0 -or -not ($modules | Select-String -Pattern '^jdk\.attach')) {
            throw "Bundled Java $major must include the jdk.attach module: $resolved"
        }
    }

    return $resolved
}

function Copy-BundledJdk {
    param(
        [string]$Source,
        [string]$AppDist
    )

    if (-not $Source) {
        return
    }

    $target = Join-Path $AppDist "jdk"
    $targetFull = [System.IO.Path]::GetFullPath($target)
    $appFull = [System.IO.Path]::GetFullPath($AppDist)
    if (-not $appFull.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
        $appFull = $appFull + [System.IO.Path]::DirectorySeparatorChar
    }
    if (-not $targetFull.StartsWith($appFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to copy bundled JDK outside app dist: $targetFull"
    }

    if (Test-Path $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    Copy-Item -LiteralPath $Source -Destination $target -Recurse -Force
}

Push-Location $ProjectRoot
try {
    $Python = Resolve-PythonCommand
    $PythonRuntimeDir = Get-PythonRuntimeDir $Python
    $ResolvedBundledJdk = Resolve-BundledJdk $BundledJdkPath

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
    $AddBinary = @()

    $VCRuntime1401 = Join-Path $PythonRuntimeDir "vcruntime140_1.dll"
    if (Test-Path $VCRuntime1401) {
        $AddBinary += "$VCRuntime1401;."
    }

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
    foreach ($Item in $AddBinary) {
        $PyInstallerArgs += @("--add-binary", $Item)
    }
    $PyInstallerArgs += @($EntryScript)

    Invoke-Python $Python $PyInstallerArgs

    if (-not (Test-Path (Join-Path $AppDist "ThaumcraftNexus.exe"))) {
        throw "Build finished but ThaumcraftNexus.exe was not found under $AppDist"
    }

    if ($ResolvedBundledJdk) {
        Copy-BundledJdk $ResolvedBundledJdk $AppDist
    }

    $PortableReadme = @"
Thaumcraft Nexus 便携版

使用方式：
1. 程序会优先使用目标游戏进程自己的 Java，可兼容 Java 8 / 17 / 21 / 25。
2. 启动 GT New Horizons，进入游戏并打开神秘时代研究台。
3. 双击 ThaumcraftNexus.exe。
4. 在界面中读取当前笔记、自动放置，或使用轮椅模式批量处理。

注意：
- 本工具是外部辅助程序，不需要把文件放进整合包 mods 目录。
- Java 8 需要 lib\tools.jar；Java 9+ 需要 jdk.attach 模块。
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
