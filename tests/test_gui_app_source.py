import unittest
from pathlib import Path


GUI_SOURCE = Path(__file__).resolve().parents[1] / "thaum_nexus" / "gui_app.py"
GITIGNORE = Path(__file__).resolve().parents[1] / ".gitignore"

OBSOLETE_SCREENSHOT_UI_TEXT = [
    "打开截图",
    "截取当前屏幕",
    "截取 Minecraft 窗口",
    "重新校准",
    "加载校准",
    "保存校准",
    "自动检测 ROOT/格子",
    "备用流程：截图识别",
]


class GuiAppSourceTests(unittest.TestCase):
    def test_gui_focuses_on_structured_note_workflow(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn("读取当前笔记", source)
        self.assertIn("读取并自动放置", source)
        for obsolete_label in OBSOLETE_SCREENSHOT_UI_TEXT:
            self.assertNotIn(obsolete_label, source)

    def test_gui_has_github_link_without_usage_steps_noise(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn("https://github.com/CaeliaEve/thaumcraft-nexus", source)
        self.assertIn("icons8-github-50.png", source)
        self.assertIn("_open_github", source)
        self.assertIn("设置", source)
        self.assertIn("_open_settings", source)
        self.assertIn("_bind_shortcuts", source)
        self.assertNotIn('text="GH"', source)
        self.assertNotIn("使用步骤", source)
        self.assertNotIn("游戏里打开研究台", source)
        self.assertNotIn("打开游戏研究台后，点击", source)
        self.assertNotIn("轮椅模式运行时界面不会再卡住", source)
        self.assertNotIn("结构读取 · 自动求解 · 批量处理", source)

    def test_gui_exposes_manual_jvm_pid_setting(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn("targetPid", source)
        self.assertIn("_bridge_pid", source)
        self.assertIn("list_java_processes", source)
        self.assertIn("pid=pid", source)
        self.assertIn("stale PID", source)
        self.assertIn("targetPid\": """, source)

    def test_gui_stop_button_cancels_all_worker_actions(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn("OperationCancelled", source)
        self.assertIn("read_and_solve_current_note(", source)
        self.assertIn("read_solve_and_apply_current_note(", source)
        self.assertIn("solve_all_inventory_notes(", source)
        self.assertIn("delay_ms=delay_ms", source)
        self.assertIn("verify_delay_ms=verify_delay_ms", source)
        self.assertIn('self._start_worker("\\u8bfb\\u53d6\\u5f53\\u524d\\u7b14\\u8bb0", task, cancellable=True)', source)
        self.assertIn('self._start_worker("\\u81ea\\u52a8\\u653e\\u7f6e\\u5f53\\u524d\\u7b14\\u8bb0", task, cancellable=True)', source)

    def test_gui_exposes_placement_speed_presets_and_custom_values(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn("PLACEMENT_SPEED_PRESETS", source)
        self.assertIn("DEFAULT_PLACEMENT_SPEED_PRESET", source)
        self.assertIn('"placementSpeed"', source)
        self.assertIn("摆放速度", source)
        self.assertIn("自定义", source)
        self.assertIn("_placement_speed_values", source)
        self.assertIn("_placement_speed_summary", source)
        self.assertIn("0 到 5000 毫秒", source)

    def test_gui_exposes_optimal_solver_mode(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")

        self.assertIn('"solverMode"', source)
        self.assertIn("最少要素优先", source)
        self.assertIn("_solver_mode_summary", source)
        self.assertIn("solve_mode=solve_mode", source)

    def test_documented_read_tool_exposes_solver_mode(self):
        project_root = Path(__file__).resolve().parents[1]
        source = (project_root / "tools" / "read_current_note.py").read_text(encoding="utf-8")

        self.assertIn('"--solver-mode"', source)
        self.assertGreaterEqual(source.count("solve_mode=args.solver_mode"), 2)

    def test_gui_no_longer_imports_screenshot_vision_stack(self):
        source = GUI_SOURCE.read_text(encoding="utf-8")

        for obsolete_import in [
            "PillowScreenshotSource",
            "CalibrationProfile",
            "BoardReader",
            "AspectMatcher",
            "HexPresenceDetector",
            "locate_minecraft_window",
        ]:
            self.assertNotIn(obsolete_import, source)

    def test_local_archive_is_not_published(self):
        gitignore = GITIGNORE.read_text(encoding="utf-8")

        self.assertIn("archive/", gitignore)


if __name__ == "__main__":
    unittest.main()
