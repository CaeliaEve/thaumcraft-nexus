# 魔导手册主页实现计划

> 使用 subagent-driven-development 拆分独立的棋盘渲染工作，主页集成在当前会话完成。用户已批准设计及实施。

**目标：** 以用户的 1024 × 681 原图为美术基础，实现可缩放、可键盘操作的研究笔记主页。

**架构：** 独立的 LogbookView 管理 Canvas、坐标变换和按钮状态，GUI 保留任务及设置逻辑。BoardImageRenderer 提供透明的纸面模式，保存答案图继续使用完整背景的导出模式。

**技术栈：** Python / Tkinter / Pillow；背景离线修补使用 OpenCV，不增加运行时依赖。

**工作区：** 沿用当前 release/windows 工作区，因为设计基于已有未提交 GUI 改动。保留其他文件的用户改动，不提交或覆盖已有发行产物；便携验证输出到 build/logbook-portable。

## 文件与职责

- `image/thaumonomicon_bg_clean.png`：原图衍生底图，清除动态文字，原 JPG 保留。
- `tools/prepare_logbook_background.py`：可重现的局部纸张修补脚本。
- `thaum_nexus/logbook_view.py`：等比缩放、菜单点击与键盘焦点、状态与详情显示。
- `thaum_nexus/gui_app.py`：连接界面和现有业务操作，控制任务生命周期。
- `thaum_nexus/overlay/board_image_renderer.py`：透明预览与独立导出。
- `tests/test_logbook_ui.py`：真实 Tk 窗口中验证菜单空白区点击、禁用、缩放、键盘、生命周期。
- `tests/test_board_image_renderer.py`：透明预览、导出和绘制范围验证。

## 任务 1：透明棋盘

- [x] 为透明预览的背景 alpha、要素仍可见、默认导出不透明写测试，运行确认当前实现失败。
- [x] 增加 `render(board, solution, *, paper=False)` 参数。纸面模式无黑色底板及标题，采用深褐网格和暗红路径；默认导出保持完整图像。
- [x] 运行 `build/ui-venv/Scripts/python.exe -B -m unittest tests.test_board_image_renderer -v`。
- [x] 独立审查规格和实现。

## 任务 2：背景与主页交互

- [x] 修补菜单、现况与等待文字区域，检查原尺寸图片无矩形色块、原图不变。
- [x] 使用真实 Tk 复现禁用快捷键、键盘导航和缩放后的命中错误，并保留整行点击回归测试。
- [x] 实现统一设计坐标；窗口比例改变时居中留边；所有文字、命中区域及图版同步缩放。
- [x] 菜单位于左页 y=210/250/290/330/370/410，状态位于左下；Tab / Shift+Tab 导航，Enter / Space 激活，禁用按钮不触发动作。
- [x] 右页显示空闲、处理中、成功、失败、取消；长笔记名省略并悬停显示全文；状态详情可查看。
- [x] 将 GUI 设置与任务完成/异常/取消事件连接至视图；快捷键遵守按钮禁用状态。
- [x] 运行 `build/ui-venv/Scripts/python.exe -B -m unittest tests.test_logbook_ui -v`。

## 任务 3：集成与交付

- [x] 执行全部 unittest，并运行 Python 编译检查。
- [x] 导出并检查 1024×681 与 1440×900 的离线画面；真实 Tk 测试验证等比缩放及留边命中。
- [x] 构建独立便携包，核对背景哈希一致，运行启动进程检查。
- [x] 审查最终修改，报告验证结果和交付路径。

## 进度

- 环境：创建 `build/ui-venv`，安装 Pillow、PyInstaller 及仅制作资源所用的 OpenCV。
- 原有测试基线：66 项，65 通过，1 项因缺 Pillow 跳过。

## 验证结果

- 全量 unittest：83 项全部通过，无跳过（build/logbook-tests.log）。
- Python 编译检查通过，git diff --check 无差异格式错误。
- 便携版：build/logbook-portable/ThaumcraftNexus/ThaumcraftNexus.exe；PyInstaller 构建完成。
- 启动进程保持运行 3 秒后由验证程序停止；包内背景与源 PNG 哈希一致。
- 离线预览：build/logbook-previews 与 build/logbook-previews-large，五种状态均已生成；检查了原尺寸及放大画面。
- 独立审查发现的路径被覆盖、六边形不共边、详情不更新、自定义快捷键优先级、最终扫描多计一张等问题均已修复并增加回归测试。
- 桌面截图工具因自动审批审查模型配置错误 model_not_found（gpt-5.6-luna）未执行；未进行真实游戏连接验证。
- 原始 JPG、既有 dist 包及其他求解器改动保留；未提交 Git。

## GitHub 发布（用户随后授权）

- 用户确认界面并授权推送 GitHub，发布目标为现有 release/windows 分支。
- 旧 dist/ThaumcraftNexus 已完整备份至 build 下的 portable-backup-before-logbook 时间戳目录。
- dist 同步为已验证的完整便携包；所有文件逐一核对 SHA-256。
- 源码包含当前库存排序优化及配套测试，与便携包构建输入保持一致。
- .omx、runtime、构建日志与本地备份不上传。
