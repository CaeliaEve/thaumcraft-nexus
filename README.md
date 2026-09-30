<h1 align="center">Thaumcraft Nexus</h1>

<p align="center">
  <strong>Thaumcraft 4 / GT New Horizons 研究笔记外部求解器</strong>
</p>

<p align="center">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows-2563eb">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-3776ab">
  <img alt="Java" src="https://img.shields.io/badge/java-8%20%7C%2017--25-f97316">
  <img alt="Type" src="https://img.shields.io/badge/type-external%20tool-16a34a">
  <img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-blue">
</p>

Thaumcraft Nexus 是面向 **Thaumcraft 4 / GT New Horizons** 的外部桌面工具。项目通过本地 Java Agent 读取当前研究台中的研究笔记，将笔记结构转换为可计算的棋盘模型，计算合法要素连线路径，并可将求解结果应用回游戏内研究台。

本项目不是 Minecraft / Forge Mod，不需要放入 `mods` 目录，也不要求服务器安装。自动放置与要素合成仍遵循游戏与服务器原有逻辑，并消耗玩家实际持有的要素资源。

---

## 目录

- [核心能力](#核心能力)
- [运行方式](#运行方式)
- [GUI 功能](#gui-功能)
- [Java / JVM 要求](#java--jvm-要求)
- [命令行接口](#命令行接口)
- [构建便携版](#构建便携版)
- [数据文件](#数据文件)
- [开发与验证](#开发与验证)
- [项目结构](#项目结构)
- [License](#license)
- [使用边界与风险声明](#使用边界与风险声明)

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 结构化读取 | 直接从客户端读取研究笔记数据，不依赖截图识别。 |
| 自动求解 | 基于 Thaumcraft 要素邻接规则计算合法连线路径。 |
| 资源感知 | 读取玩家当前可用要素数量，并在求解时优先使用更充足的要素。 |
| 最优路径模式 | 在搜索预算内比较多种连接顺序与候选路径，以总放置数量为首要目标；格数相同时按库存余量、基础要素均衡和合成开销择优。 |
| 要素合成 | 在要素不足时，递归生成并执行多阶合成链。 |
| 自动放置 | 将求解结果发送至当前研究台，完成要素放置。 |
| 批量处理 | 连续处理研究台和背包中的未完成研究笔记。 |
| 答案预览 | 生成结构化答案预览图，便于检查求解路径。 |
| 快捷键配置 | 支持在 GUI 内配置常用操作快捷键。 |

## 运行方式

源码和 Windows 便携版统一在 `main` 分支维护。直接使用可打开仓库中的 [`dist/ThaumcraftNexus/`](dist/ThaumcraftNexus/)；开发和调试可从同一份仓库运行源码。

### Windows 便携版

便携版面向直接使用场景。运行时需要保留完整的 `ThaumcraftNexus` 目录结构，不能仅复制单个 `.exe` 文件。

```text
ThaumcraftNexus/
  ThaumcraftNexus.exe
  README_CN.txt
  _internal/
    image/
    data/
    java-agent/
  runtime/        # 运行时生成
```

基本流程：

1. 启动 GT New Horizons / Minecraft。
2. 打开 Thaumcraft 研究台，并放入研究笔记。
3. 运行 `ThaumcraftNexus.exe`。
4. 在 GUI 中执行读取、求解、自动放置或批量处理。

### 源码运行

源码运行面向开发、调试或自行构建场景。

环境要求：

- Windows
- Python 3.10+
- 可用 JDK
- 正在运行的 GTNH / Minecraft 客户端

安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

构建 Java Agent：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\java-agent\build_agent.ps1
```

启动 GUI：

```powershell
.\start_gui.cmd
```

## GUI 功能

| 操作 | 说明 |
| --- | --- |
| 解析研究笔记 | 读取当前研究台笔记并生成求解预览。 |
| 推演并注入要素 | 读取、求解，并将结果应用到当前研究台。 |
| 批量研习 | 批量处理研究台和背包中的未完成笔记。 |
| 誊录研究图谱 | 保存当前答案预览图片。 |
| 研究配置 | 选择 JVM 进程、填写 PID、配置快捷键、摆放速度和求解策略。 |

自动放置和批量处理会消耗游戏内要素资源。执行前应确认当前研究台状态和求解结果符合预期。

主页采用魔导手册双页布局：左页提供操作目录与实时状态，右页显示透明棋盘预览。窗口缩放时书页、文字和点击区域等比例调整；支持 Tab / Shift+Tab、方向键导航及 Enter / Space 激活。左下角“研究记录”可查看持续更新的任务记录，长笔记名可悬停查看全文。

右页提供资源预估与“资源明细与合成顺序”入口，可查看放置需求、读取时库存、预计合成次数和阻塞缺口；悬停棋盘要素可查看名称与放置编号。库存是读取时的快照，自动放置后会将执行前计划与实际回执区分显示。缺口为当前合成路径识别到的阻塞资源，补充后应重新读取。

停止请求会传递到求解过程。关闭主窗口时，程序先请求停止并等待后台任务结束；若游戏内操作未确认停止，会保留错误提示，要求检查或重启目标客户端后再继续。

错误页面提供原因分类和处理建议，完整技术详情保存在任务记录及 `runtime/gui_last_error.*` 中。设置使用原子替换保存；保存失败保留原设置，格式损坏时回退默认值并提示，读取过程不会覆盖损坏文件。原生窗口标题栏采用深色主题，版本信息保留在研究记录与诊断记录中，便携包还记录构建所用的源码提交号。

研究配置按研究策略、注入节律、快捷符令和世界连接分类。所有修改（包括快捷键）仅在点击“保存配置”后生效；取消放弃草稿，“恢复本页默认”仅重置当前分类。进程查询在后台进行，手动 PID 仅本次运行有效。主页 GitHub 图标可直接打开项目仓库。

## Java / JVM 要求

Thaumcraft Nexus 会自动识别 GTNH / Minecraft JVM，并兼容常见启动器入口，包括 Prism Launcher / MultiMC 系列入口。

| 游戏 Java 版本 | 要求 |
| --- | --- |
| Java 8 | 需要 JDK，并包含 `lib/tools.jar`。 |
| Java 9+ | 需要包含 `jdk.attach` 模块的 JDK / 运行时。 |
| Java 17–25 | 使用现代 JVM attach 参数进行连接。 |

连接优先级：

1. 优先使用目标游戏进程自身的 Java 运行时。
2. 自动识别失败时，可在 GUI 设置中刷新并选择 JVM 进程。
3. 支持手动填写 PID；游戏进程重启后 PID 会变化。
4. 便携包可内置 JDK，例如 `jdk/`、`jdk8/`、`jdk21/` 等目录。

内置 JDK 目录示例：

```text
ThaumcraftNexus/
  ThaumcraftNexus.exe
  _internal/
  jdk/      # 通用 JDK 目录
  jdk21/    # Java 21 JDK
```

## 命令行接口

读取并求解当前研究笔记：

```powershell
python tools\read_current_note.py
```

读取、求解并自动放置：

```powershell
python tools\read_current_note.py --apply
```

指定 Minecraft JVM PID：

```powershell
python tools\read_current_note.py --pid <PID>
```

模块入口：

```powershell
python -m thaum_nexus.cli read-current-note
python -m thaum_nexus.cli apply-current-note
python -m thaum_nexus.cli apply-current-note --solver-mode optimal
python -m thaum_nexus.cli inventory-notes
python -m thaum_nexus.cli wheelchair --apply
python -m thaum_nexus.cli wheelchair --apply --solver-mode optimal
```

## 构建便携版

构建者需要安装 `.python-version` 指定的 64 位 Python 和可用 JDK。构建脚本在 `build/release-venv/` 创建独立环境，并使用 `requirements-build.txt` 固定工具链版本；资源制作所用的 OpenCV、NumPy 不进入便携包。源码运行仍支持 Python 3.10+。构建产物采用 PyInstaller one-dir 结构。

构建程序本体：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1
```

构建时复制指定 JDK 到便携包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -BundledJdkPath "C:\Program Files\Java\jdk-21"
```

构建输出目录：

```text
dist/ThaumcraftNexus/
```

发布时应分发完整的 `ThaumcraftNexus` 文件夹。

如需保留现有便携包，可通过 `-OutputDir` 指定另一个输出目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1 -OutputDir .\build\logbook-portable
```

可用 `-PythonExe` 指定构建用的 Python 路径。`-SkipPyInstallerInstall` 仅复用已创建且依赖校验通过的发布环境；`-SkipJavaAgentBuild` 显式复用已有 Agent。常规构建遇到 Java 编译失败会立即停止，避免把旧 Agent 混入新版本。

构建后可验证冻结程序是否能加载界面与资源：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_portable.ps1 -AppDir .\dist\ThaumcraftNexus
```

GitHub Actions 会在 `main` 更新及 Pull Request 时运行 Windows 测试、Java 编译和便携包检查。发布 `v主版本.次版本.修订号` 标签（例如 `v1.0.0`）后，会重新测试、构建，并自动在 GitHub Releases 上传完整 ZIP 与 SHA-256 校验文件。带后缀的标签（例如 `v1.0.0-rc.1`）发布为预览版；无需维护独立 Windows 分支。

工具链固定用于控制构建输入，不承诺不同机器上的二进制逐字节相同。

## 数据文件

仓库包含运行所需的要素数据与图标资源。

| 目录 | 内容 |
| --- | --- |
| `data/` | 要素定义、合成关系、邻接规则和数据清单。 |
| `image/` | Thaumcraft 要素图标和 GUI 资源。 |

无需为常规运行重新生成数据。如需从本地 NESQL 导出并重建数据，可执行：

```powershell
python tools\extract_nesql_thaumcraft_data.py --nesql <NESQL_EXPORT_ROOT>
```

或通过环境变量指定 NESQL 路径：

```powershell
$env:THAUM_NEXUS_NESQL="<NESQL_EXPORT_ROOT>"
python tools\extract_nesql_thaumcraft_data.py
```

## 开发与验证

常用验证命令：

```powershell
python -m unittest discover -v
python -m py_compile thaum_nexus\gui_app.py thaum_nexus\client_bridge.py thaum_nexus\solver\search.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\java-agent\build_agent.ps1
```

统一使用 `main` 分支维护源码、测试、资源与 `dist/ThaumcraftNexus/` 便携包，不再单独维护 `release/windows` 分支。发布更新时，先验证源码并重新构建便携包，再将两者一起提交；运行时设置、日志及本地 JDK 不纳入版本控制。

可离线生成主页各状态的 PNG 预览，无需连接游戏：

```powershell
python tools\render_logbook_preview.py
```

预览输出到 `build/logbook-previews/`。底图使用 `image/thaumonomicon_bg_clean.png`，原始参考 JPG 保留；如需重新修补底图，开发环境额外安装 `opencv-python-headless` 后运行 `python tools\prepare_logbook_background.py`。OpenCV 不属于程序运行依赖。

可用现有知识库、仓库棋盘样本和固定随机种子生成离线求解基准，无需额外数据库：

```powershell
python tools\benchmark_solver.py > build\solver-benchmark.json
```

默认运行两个仓库样本和 20 个生成棋盘，输出合法性、放置数量、阻塞缺口、合成次数和耗时。`--seed`、`--generated`、`--mode` 可调整样本与策略；`--solver-source` 可载入可信的旧版 `search.py` 对比。生成棋盘不代表真实玩家分布，搜索未成功也不证明无解。最少要素模式会继续尝试其他候选策略，避免首个贪心策略失败就提前放弃。

## 项目结构

```text
thaum_nexus/      Python 主程序、GUI、求解器和客户端桥接
java-agent/       Java Attach Agent 源码
scripts/          构建与发布辅助脚本
tools/            命令行工具和数据提取脚本
data/             已生成的要素知识库
image/            要素图标和 GUI 资源
tests/            回归测试
dist/ThaumcraftNexus/  Windows 便携版（与源码同步维护）
start_gui.cmd     GUI 启动脚本
```

## License

Original source code in this project is licensed under the [Apache License 2.0](LICENSE).

> Third-party names, icons, textures, aspect data, compatibility data, bundled runtimes, and dependency components remain the property of their respective owners. These third-party materials are not covered by the Apache License 2.0 grant for the project's original source code.
>
> See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details.

## 使用边界与风险声明

- 本项目是外部辅助工具，不是 Minecraft / Forge Mod。
- 本项目不绕过 Thaumcraft 的要素消耗、研究台规则或服务器校验。
- 自动操作依赖当前客户端状态，应在研究台已打开且笔记已放入时执行。
- 在重要存档或生产环境中使用前，应先在可接受的测试环境中验证行为。

### 风险声明

1. **工具属性**：本项目通过本地 Java Agent 与运行中的 Minecraft 客户端进程交互，属于外部辅助工具范畴。部分服务器、整合包环境或反作弊策略可能将客户端进程交互、自动化操作或数据读取视为受限制行为。
2. **规则确认**：在多人服务器环境中使用前，应自行确认所在服务器的用户协议、管理条例、自动化规则、客户端修改规则以及相关社区约定。若服务器规则禁止或限制类似工具，应停止使用。
3. **能力边界**：本项目不提供规避服务器检测、权限限制、要素消耗、研究台规则或其他游戏校验机制的能力，也不鼓励在违反服务器规则的场景中使用。
4. **风险承担**：因使用本项目导致的账号处罚、服务器封禁、进度异常、数据损坏、兼容性问题或其他直接、间接后果，由使用者自行承担。
5. **推荐场景**：应优先在单人存档、测试环境或明确允许使用此类工具的服务器中验证行为，再决定是否在其他环境中继续使用。
