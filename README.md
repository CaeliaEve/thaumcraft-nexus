# Thaumcraft Nexus

Thaumcraft Nexus 是一个面向 Thaumcraft 4 研究笔记的外部桌面求解工具，主要适配 GT New Horizons。

它可以从正在运行的 Minecraft 客户端中读取当前打开的研究笔记，自动计算要素连线路径，在 GUI 中展示答案，并可选择自动放置要素。

## 功能特性

- 通过本地 Java Agent 结构化读取当前研究笔记。
- 自动求解 Thaumcraft 研究笔记中的要素连线。
- 提供干净的 GUI 答案预览。
- 支持一键自动放置当前笔记。
- 支持批量处理多个未完成研究笔记。
- 内置要素数据和图标，普通用户不需要额外导出 NESQL 数据。

## 工作方式

```text
打开研究台 → 读取笔记 → 自动求解 → 预览答案 → 可选自动放置
```

Thaumcraft Nexus **不是服务端 Mod**。服务器不需要安装任何东西。自动放置使用的是 Thaumcraft 客户端原本的放置请求，仍然由服务端正常校验，并会消耗游戏内资源。

## 环境要求

- Windows
- Python 3.10+
- Java 8 JDK
  - 需要 JDK，不只是 JRE。
  - 构建 Java Agent 需要 `javac`、`jar` 和 Java Attach API。
- 本地正在运行的 GTNH / Minecraft 客户端

安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

## 快速开始

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

## GUI

GUI 提供以下主要操作：

- **读取当前笔记**：读取并求解当前研究台中的笔记。
- **读取并自动放置**：读取、求解，并把结果应用到当前研究台。
- **轮椅模式**：批量处理背包/研究台中的未完成笔记。
- **保存答案图**：保存当前显示的答案图片。
- **设置**：自定义 GUI 快捷键。

自动放置和批量模式会消耗游戏内墨水/要素，请在确认要应用解法时再使用。

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

## 数据

仓库已经包含普通使用所需的要素数据和图标：

- `data/`：要素、合成关系和邻接规则。
- `image/`：要素图标和 GUI 图标。

普通用户不需要重新生成这些数据。

如果开发者需要从本地 NESQL 导出重新生成数据，可以使用：

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

