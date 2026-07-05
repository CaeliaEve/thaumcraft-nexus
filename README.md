# Thaumcraft Nexus

Thaumcraft Nexus 是一个面向 Thaumcraft 4 / GT New Horizons 研究笔记的外部桌面求解工具。它通过本地 Java Agent 读取当前打开的研究笔记，计算要素连线路径，并可以把求解结果自动放置回游戏内研究台。

## 功能特性

- 结构化读取当前研究台中的 Thaumcraft 研究笔记。
- 自动求解要素连线，并生成清晰的答案预览图。
- 支持自动放置当前笔记所需要素。
- 支持批量处理背包与研究台中的未完成笔记。
- 要素数量不足时，可根据合成关系自动发送合成操作。
- 内置要素数据与图标，普通使用者不需要额外导出数据。
- GUI 提供自定义快捷键设置。

## 工作方式

```text
打开研究台 → 读取笔记 → 自动求解 → 可选自动放置 / 批量处理
```

Thaumcraft Nexus 是外部工具，不是服务端 Mod。服务器不需要安装本工具；自动放置仍然会经过游戏与服务器原有逻辑校验，并消耗游戏内实际拥有的要素资源。

## 环境要求

### 源码运行

- Windows
- Python 3.10+
- Java 8 JDK
  - 需要 JDK，不只是 JRE。
  - 需要 `java`、`javac`、`jar` 以及 Java Attach API。
- 正在运行的 GTNH / Minecraft 客户端

### 便携版运行

便携版不需要使用者安装 Python；仍需要本机安装 Java 8 JDK，并建议配置 `JAVA_HOME` 指向该 JDK。

## 快速开始（源码运行）

1. 下载或克隆本项目。
2. 安装 Python 依赖：
   ```powershell
   python -m pip install -r requirements.txt
   ```
3. 构建 Java Agent：
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\java-agent\build_agent.ps1
   ```
4. 启动 GTNH / Minecraft。
5. 打开 Thaumcraft 研究台，并放入研究笔记。
6. 双击启动：
   ```text
   start_gui.cmd
   ```

## GUI 使用

GUI 提供以下主要操作：

- **读取当前笔记**：读取并求解当前研究台中的笔记。
- **读取并自动放置**：读取、求解，并把结果应用到当前研究台。
- **轮椅模式：解完背包笔记**：批量处理研究台和背包中的未完成笔记。
- **保存答案图**：保存当前显示的答案图片。
- **设置**：自定义 GUI 快捷键。

自动放置与批量处理会消耗游戏内要素资源，请在确认要应用解法时使用。

## 命令行用法

只读取并求解当前研究笔记：

```powershell
python tools\read_current_note.py
```

读取、求解并自动放置：

```powershell
python tools\read_current_note.py --apply
```

模块入口：

```powershell
python -m thaum_nexus.cli read-current-note
python -m thaum_nexus.cli apply-current-note
python -m thaum_nexus.cli wheelchair --apply
```

如果无法自动检测 Minecraft JVM，可以手动指定进程 PID：

```powershell
python tools\read_current_note.py --pid <PID>
```

## 构建便携版 EXE

便携版采用 PyInstaller one-dir 方案。构建者需要安装 Python 和 Java 8 JDK；最终使用者不需要安装 Python。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_portable.ps1
```

构建完成后，将生成的 `ThaumcraftNexus` 文件夹整体复制给使用者即可。使用者启动游戏后运行 `ThaumcraftNexus.exe`。

## 数据

仓库已经包含普通使用所需的要素知识库和图标：

- `data/`：要素、合成关系和邻接规则。
- `image/`：要素图标和 GUI 图标。

普通使用者不需要重新生成这些数据。

开发者如需从本地 NESQL 导出重新生成数据，可以使用：

```powershell
python tools\extract_nesql_thaumcraft_data.py --nesql <NESQL_EXPORT_ROOT>
```

也可以通过环境变量指定：

```powershell
$env:THAUM_NEXUS_NESQL="<NESQL_EXPORT_ROOT>"
python tools\extract_nesql_thaumcraft_data.py
```

## 项目结构

```text
thaum_nexus/      Python 主程序、GUI、求解器和客户端桥接
java-agent/       Java Attach Agent 源码
tools/            命令行工具和数据提取脚本
scripts/          构建与发布辅助脚本
data/             已生成的要素知识库
image/            要素图标和 GUI 资源
tests/            回归测试
start_gui.cmd     GUI 启动脚本
```

## 开发检查

```powershell
python -m unittest discover -v
python -m py_compile thaum_nexus\gui_app.py thaum_nexus\client_bridge.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\java-agent\build_agent.ps1
```
