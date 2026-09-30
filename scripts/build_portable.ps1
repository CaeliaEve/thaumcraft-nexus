param(
    [switch]$SkipPyInstallerInstall,
    [switch]$SkipJavaAgentBuild,
    [string]$BundledJdkPath,
    [string]$OutputDir,
    [string]$PythonExe,
    [string]$Version
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistRoot = if ($OutputDir) { [System.IO.Path]::GetFullPath($OutputDir) } else { Join-Path $ProjectRoot "dist" }
$AppDist = Join-Path $DistRoot "ThaumcraftNexus"
$PyInstallerBuild = Join-Path $ProjectRoot "build\pyinstaller"
$SpecPath = Join-Path $PyInstallerBuild "spec"
$WorkPath = Join-Path $PyInstallerBuild "work"
. (Join-Path $PSScriptRoot "build_helpers.ps1")

function Resolve-PythonCommand {
    if ($PythonExe) {
        return @{ Exe = (Resolve-Path -LiteralPath $PythonExe).Path; Args = @() }
    }
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

    $runtimeDir = & $Python.Exe @($Python.Args + @("-c", "import pathlib, sys; print(pathlib.Path(sys.base_prefix).resolve())"))
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

function Copy-NormalizedUtf8Text {
    param(
        [string]$Source,
        [string]$Destination
    )

    $content = [System.IO.File]::ReadAllText($Source)
    $content = $content -replace "`r`n", "`n" -replace "`r", "`n"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Destination, $content, $utf8NoBom)
}

Push-Location $ProjectRoot
try {
    $BasePython = Resolve-PythonCommand
    $RequiredPython = (Get-Content -LiteralPath (Join-Path $ProjectRoot ".python-version") -Raw).Trim()
    Invoke-Python $BasePython @("-c", "import sys; assert '.'.join(map(str, sys.version_info[:3])) == '$RequiredPython', 'Release builds require Python $RequiredPython'; assert sys.maxsize > 2**32, 'Release builds require 64-bit Python'")
    # Resolve before creating the venv: vcruntime140_1.dll lives with base Python.
    $PythonRuntimeDir = Get-PythonRuntimeDir $BasePython
    $ResolvedBundledJdk = Resolve-BundledJdk $BundledJdkPath
    $BuildRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot "build"))
    $ReleaseVenv = [System.IO.Path]::GetFullPath((Join-Path $BuildRoot "release-venv"))
    $Python = @{ Exe = (Join-Path $ReleaseVenv "Scripts\python.exe"); Args = @() }
    if (-not $SkipPyInstallerInstall) {
        if ((Test-Path -LiteralPath $BuildRoot) -and ((Get-Item -LiteralPath $BuildRoot).Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            throw "Refusing to recreate environment inside linked build directory: $BuildRoot"
        }
        if (-not $ReleaseVenv.StartsWith($BuildRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to recreate environment outside build directory: $ReleaseVenv"
        }
        if (Test-Path -LiteralPath $ReleaseVenv) {
            if ((Get-Item -LiteralPath $ReleaseVenv).Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw "Refusing to remove linked build environment: $ReleaseVenv"
            }
            Remove-Item -LiteralPath $ReleaseVenv -Recurse -Force
        }
        Invoke-Python $BasePython @("-m", "venv", $ReleaseVenv)
        Invoke-Python $Python @("-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:", "-r", "requirements-build.txt")
    } elseif (-not (Test-Path -LiteralPath $Python.Exe)) {
        throw "-SkipPyInstallerInstall requires an existing build/release-venv. Run once without this flag."
    }
    Invoke-Python $Python @("-c", "import sys; assert '.'.join(map(str, sys.version_info[:3])) == '$RequiredPython'")
    Invoke-Python $Python @("tools/release_tools.py", "check-environment", "requirements-build.txt")

    $AgentJar = Join-Path $ProjectRoot "java-agent\build\thaum-nexus-agent.jar"
    if (-not $SkipJavaAgentBuild) {
        # Every build gets a fresh Java output directory, so a locked old jar cannot be selected.
        $JavaOutput = Join-Path $PyInstallerBuild ("java-agent-" + [guid]::NewGuid().ToString("N"))
        Invoke-JavaAgentBuild (Join-Path $ProjectRoot "java-agent\build_agent.ps1") $JavaOutput
        $AgentJar = Join-Path $JavaOutput "thaum-nexus-agent.jar"
    }
    if (-not (Test-Path $AgentJar)) {
        throw "Java Agent jar was not found: $AgentJar"
    }

    New-Item -ItemType Directory -Force -Path $SpecPath, $WorkPath | Out-Null
    $MetadataPath = Join-Path $PyInstallerBuild "build-info.json"
    $MetadataArgs = @("tools/release_tools.py", "metadata", "--output", $MetadataPath)
    if ($Version) { $MetadataArgs += @("--version", $Version) }
    Invoke-Python $Python $MetadataArgs

    $DataDir = Join-Path $ProjectRoot "data"
    $ImageDir = Join-Path $ProjectRoot "image"
    $EntryScript = Join-Path $ProjectRoot "tools\thaum_nexus_gui.py"

    $AddData = @(
        "$DataDir;data",
        "$ImageDir;image",
        "$AgentJar;java-agent",
        "$MetadataPath;."
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
        "--exclude-module", "numpy",
        "--exclude-module", "cv2",
        "--exclude-module", "matplotlib",
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

    foreach ($NoticeFile in @("LICENSE", "THIRD_PARTY_NOTICES.md")) {
        $NoticePath = Join-Path $ProjectRoot $NoticeFile
        if (Test-Path $NoticePath) {
            Copy-NormalizedUtf8Text $NoticePath (Join-Path $AppDist $NoticeFile)
        }
    }

    $PortableReadme = @"
Thaumcraft Nexus 便携版

使用方式：
1. 程序会优先使用目标游戏进程自己的 Java，可兼容 Java 8 / 17 / 21 / 25。
2. 启动 GT New Horizons，进入游戏并打开神秘时代研究台。
3. 双击 ThaumcraftNexus.exe。
4. 在界面中读取当前笔记、自动放置，或使用轮椅模式批量处理。
5. 设置中可开启“最少要素优先”；关闭时保持库存优先策略。

License:
- Original source code is licensed under the Apache License 2.0. See LICENSE.
- Third-party resources and dependency notices are documented in THIRD_PARTY_NOTICES.md.

注意：
- 本工具是外部辅助程序，不需要把文件放进整合包 mods 目录。
- Java 8 需要 lib\tools.jar；Java 9+ 需要 jdk.attach 模块。
- 运行时生成的 JSON、图片和设置会写入本目录下的 runtime 文件夹。
"@
    $PortableReadmePath = Join-Path $AppDist "README_CN.txt"
    $PortableReadmeLf = ($PortableReadme -replace "`r`n", "`n") + "`n"
    $Utf8Bom = New-Object System.Text.UTF8Encoding($true)
    [System.IO.File]::WriteAllText($PortableReadmePath, $PortableReadmeLf, $Utf8Bom)

    Invoke-Python $Python @("tools/release_tools.py", "verify", $AppDist)

    Write-Output ""
    Write-Output "Portable build complete:"
    Write-Output "  $AppDist"
    Write-Output "Start with:"
    Write-Output "  $AppDist\ThaumcraftNexus.exe"
}
finally {
    Pop-Location
}
