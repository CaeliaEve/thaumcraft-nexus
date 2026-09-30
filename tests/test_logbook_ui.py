"""Interaction regressions exercised against a real Tk canvas, without a JVM."""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from thaum_nexus.gui_app import ThaumNexusGui


class LogbookUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gui = ThaumNexusGui()
        self.gui.runtime_root = Path(self.tmp.name)
        self.root = tk.Tk()
        # Hosted Windows desktops can be smaller than the resize cases below.
        self.root.maxsize(4096, 4096)
        self.callback_errors = []
        self.root.report_callback_exception = lambda *error: self.callback_errors.append(error)
        self.addCleanup(self.close_window)
        self.root.geometry("1024x681+0+0")
        self.gui.tk = self.root
        self.calls = []
        self.gui._read_current_note = lambda: self.calls.append("read")
        from tkinter import ttk
        self.gui._configure_style(ttk)
        self.gui._build_layout(tk, ttk)
        self.root.update()

    def close_window(self):
        try:
            for job in self.root.tk.call("after", "info"):
                self.root.after_cancel(job)
            self.root.destroy()
        except tk.TclError:
            pass  # A shutdown test may already have destroyed the interpreter's window.
        self.assertEqual(self.callback_errors, [], "Tk callbacks must not fail during use or shutdown")

    def test_github_icon_has_tooltip_and_click_target(self):
        from types import SimpleNamespace
        view = self.gui.logbook
        x, y = view.point(350, 624)
        view._motion(SimpleNamespace(x=x, y=y))
        self.assertEqual(view._tooltip_text, "项目仓库 · GitHub")
        clicked = []
        view.on_github = lambda: clicked.append(True)
        view._click(SimpleNamespace(x=x, y=y))
        self.assertEqual(clicked, [True])
        self.assertIsNotNone(view._github_photo)

    def test_settings_rebinding_conflict_and_escape_leave_live_shortcuts_unchanged(self):
        from types import SimpleNamespace
        self.gui._open_settings()
        editor = self.gui.settings_editor
        original = dict(self.gui.shortcuts)
        editor.capture("read")
        editor.capture_key(SimpleNamespace(keysym="F6", state=0))
        self.assertEqual(editor.shortcuts, original)
        editor.capture_key(SimpleNamespace(keysym="F9", state=0))
        self.assertEqual(editor.shortcuts["read"], "<F9>")
        self.assertEqual(self.gui.shortcuts, original)
        editor.capture("apply")
        editor.escape()
        self.assertTrue(editor.window.winfo_exists())
        editor.cancel()

    def test_settings_invalid_custom_timing_does_not_save(self):
        self.gui._open_settings()
        editor = self.gui.settings_editor
        editor.preset.set("custom")
        editor.speed_changed()
        editor.delay.set("5001")
        before = dict(self.gui.placement_speed)
        editor.save()
        self.assertEqual(self.gui.placement_speed, before)
        self.assertFalse(self.gui._settings_path().exists())
        self.assertTrue(editor.window.winfo_exists())
        editor.cancel()

    def test_settings_process_refresh_can_finish_after_cancel(self):
        import threading
        from unittest.mock import patch
        entered, release = threading.Event(), threading.Event()
        def processes():
            entered.set()
            release.wait(2)
            return []
        self.addCleanup(release.set)
        self.gui._open_settings()
        editor = self.gui.settings_editor
        with patch("thaum_nexus.client_bridge.list_java_processes", side_effect=processes):
            editor.refresh_processes()
            self.assertTrue(entered.wait(1))
            self.root.update()
            editor.cancel()
            release.set()
            self.root.update()
        self.assertTrue(editor.closed)
        self.assertIsNone(editor.pending)
        self.assertEqual(self.gui.target_pid, "")

    def test_settings_edits_are_drafts_until_save(self):
        import json
        self.gui._open_settings()
        editor = self.gui.settings_editor
        previous = dict(self.gui.shortcuts)
        editor.shortcuts["read"] = "<F9>"
        editor.mode.set("optimal")
        editor.cancel()
        self.assertEqual(self.gui.shortcuts, previous)
        self.assertFalse((self.gui.runtime_root / "gui_settings.json").exists())
        self.gui._open_settings()
        editor = self.gui.settings_editor
        editor.shortcuts["read"] = "<F9>"
        editor.save()
        self.assertEqual(self.gui.shortcuts["read"], "<F9>")
        data = json.loads((self.gui.runtime_root / "gui_settings.json").read_text())
        self.assertEqual(data["shortcuts"]["read"], "<F9>")
        self.assertEqual(data["targetPid"], "")

    def test_settings_defaults_only_affect_current_page(self):
        self.gui._open_settings()
        editor = self.gui.settings_editor
        editor.shortcuts["read"] = "<F9>"
        editor.pid.set("123")
        editor.show_page("世界连接")
        editor.reset_page()
        self.assertEqual(editor.pid.get(), "")
        self.assertEqual(editor.shortcuts["read"], "<F9>")
        editor.cancel()

    def test_close_waits_for_worker_acknowledgement_and_blocks_new_tasks(self):
        import threading
        import time
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()

        def task(stop, emit):
            entered.set()
            stop.wait(2)
            if stop.is_set():
                cancelled.set()
            release.wait(2)
            return {"kind": "test"}

        self.gui._start_worker("测试", task, cancellable=True)
        self.assertTrue(entered.wait(1))
        original_thread = self.gui.worker_thread
        self.addCleanup(release.set)
        self.gui._request_close()
        self.assertTrue(cancelled.wait(1), "Closing must signal cooperative cancellation")
        self.assertTrue(self.root.winfo_exists(), "Window must wait for acknowledgement")
        self.gui._start_worker("不可启动", lambda *_: self.calls.append("unexpected"), cancellable=True)
        self.assertIs(self.gui.worker_thread, original_thread)
        release.set()
        original_thread.join(1)
        deadline = time.monotonic() + 2
        while self.gui.tk is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIsNone(self.gui.tk)
        self.assertEqual(self.calls, [])

    def test_busy_worker_cannot_be_replaced_by_another_start(self):
        import threading
        release = threading.Event()
        self.addCleanup(release.set)
        self.gui._start_worker("测试", lambda *_: release.wait(2), cancellable=True)
        original = self.gui.worker_thread
        self.gui._start_worker("重复", lambda *_: self.calls.append("unexpected"), cancellable=True)
        self.assertIs(self.gui.worker_thread, original)
        release.set()
        original.join(1)
        self.assertEqual(self.calls, [])

    def test_error_report_write_failure_still_restores_controls_and_shows_advice(self):
        self.gui.runtime_root = self.gui.runtime_root / "not-a-directory"
        self.gui.runtime_root.write_text("occupied", encoding="utf-8")
        self.gui.busy = True
        self.gui._handle_worker_error(TimeoutError("attach timed out"))
        self.assertFalse(self.gui.busy)
        self.assertEqual(self.gui.buttons["read"].state, "normal")
        self.assertIn("超时", self.gui.logbook.message)
        self.assertTrue(any("诊断" in line for line in self.gui.log_lines))

    def test_solution_resources_and_cell_tooltips_follow_scaled_preview(self):
        from thaum_nexus.note_io import ResearchNote
        from thaum_nexus.solver import solve
        from types import SimpleNamespace
        note = ResearchNote.load(Path(__file__).parent / "fixtures" / "notes" / "two_roots_line_note.json")
        solution = solve(note.board, self.gui.kb)
        self.gui._show_solution(board=note.board, solution=solution, note_label="测试",
                                payload={"resources": {"required": {"lux": 1}, "available": {"lux": 3},
                                                       "synthesis": [], "shortages": {}}})
        self.root.geometry("1440x900")
        self.root.update()
        view = self.gui.logbook
        texts = [view.canvas.itemcget(i, "text") for i in view.canvas.find_all() if view.canvas.type(i) == "text"]
        self.assertTrue(any("资源" in text for text in texts))
        region = next(region for region in view.preview_regions if "放置" in region[3])
        left, top, factor = view.preview_transform
        event = SimpleNamespace(x=left + region[0] * factor, y=top + region[1] * factor)
        view._motion(event)
        view._show_tooltip()
        tooltip = " ".join(view.canvas.itemcget(i, "text") for i in view.canvas.find_withtag("tooltip") if view.canvas.type(i) == "text")
        self.assertIn("放置", tooltip)
        self.assertIn("1", tooltip)
        self.gui._show_resources()
        self.assertTrue(self.gui.resources_window.winfo_exists())

    def test_failed_settings_save_keeps_dialog_open_and_previous_values(self):
        from tkinter import ttk
        self.gui.runtime_root = self.gui.runtime_root / "blocked"
        self.gui.runtime_root.write_text("occupied", encoding="utf-8")
        self.gui._open_settings()
        dialog = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
        widgets = list(dialog.winfo_children())
        all_widgets = []
        while widgets:
            widget = widgets.pop()
            all_widgets.append(widget)
            widgets.extend(widget.winfo_children())
        editor = self.gui.settings_editor
        before = self.gui.solver_mode
        editor.mode.set("optimal")
        editor.shortcuts["read"] = "<F9>"
        previous_shortcuts = dict(self.gui.shortcuts)
        editor.save()
        self.root.update()
        self.assertTrue(dialog.winfo_exists())
        self.assertEqual(self.gui.solver_mode, before)
        self.assertEqual(self.gui.shortcuts, previous_shortcuts)
        self.assertIn("保存失败", editor.hint.get())
        self.assertEqual(self.callback_errors, [])

    def test_unconfirmed_agent_cancellation_keeps_window_open_for_diagnosis(self):
        import queue
        from thaum_nexus.client_bridge import UnsafeAgentStateError
        self.gui.worker_queue = queue.Queue()
        self.gui.worker_queue.put(("error", UnsafeAgentStateError("Java Agent did not confirm cancellation")))
        self.gui._request_close()
        self.assertIsNotNone(self.gui.tk)
        self.assertTrue(self.root.winfo_exists())
        self.assertFalse(self.gui.closing)
        self.assertEqual(self.gui.logbook.state, "error")

    def test_completed_read_with_unwritable_output_becomes_visible_error(self):
        import queue
        from thaum_nexus.client_bridge import CurrentNoteResult
        from thaum_nexus.note_io import ResearchNote
        from thaum_nexus.solver import solve
        note = ResearchNote.load(Path(__file__).parent / "fixtures" / "notes" / "two_roots_line_note.json")
        result = CurrentNoteResult(note, solve(note.board, self.gui.kb), Path("note.json"))
        self.gui.runtime_root = self.gui.runtime_root / "blocked"
        self.gui.runtime_root.write_text("occupied", encoding="utf-8")
        self.gui.worker_queue = queue.Queue()
        self.gui.worker_queue.put(("done", {"kind": "read", "result": result}))
        self.gui.busy = True
        self.gui._poll_worker_queue()
        self.assertEqual(self.gui.logbook.state, "error")
        self.assertFalse(self.gui.busy)
        self.assertEqual(self.callback_errors, [])

    def click(self, x, y):
        self.gui.canvas.event_generate("<Motion>", x=x, y=y)
        self.gui.canvas.event_generate("<Button-1>", x=x, y=y)
        self.root.update()

    def details_text(self):
        widgets = list(self.gui.details_window.winfo_children())
        while widgets:
            widget = widgets.pop()
            if isinstance(widget, tk.Text):
                return widget
            widgets.extend(widget.winfo_children())
        self.fail("Details window must contain a real Tk Text widget")

    def test_open_details_tracks_note_status_and_log_updates(self):
        self.gui._show_details()
        text = self.details_text()
        self.gui.note_name.set("笔记：更新后的笔记")
        self.assertIn("更新后的笔记", text.get("1.0", "end"))
        self.gui._set_status("任务已完成")
        self.assertIn("任务已完成", text.get("1.0", "end"))
        self.gui._append_log("最终诊断记录")
        self.assertIn("最终诊断记录", text.get("1.0", "end"))
        self.assertEqual(text.cget("state"), "disabled")

    def test_details_refreshes_when_shown_again_and_reopens_after_close(self):
        self.gui._show_details()
        original_window = self.gui.details_window
        self.gui.log_lines.append("再次查看时的记录")
        self.gui._show_details()
        self.assertIs(self.gui.details_window, original_window)
        self.assertIn("再次查看时的记录", self.details_text().get("1.0", "end"))
        original_window.destroy()
        self.gui._set_status("窗口关闭后的状态")
        self.gui._append_log("窗口关闭后的记录")
        self.gui._show_details()
        self.assertIsNot(self.gui.details_window, original_window)
        contents = self.details_text().get("1.0", "end")
        self.assertIn("窗口关闭后的状态", contents)
        self.assertIn("窗口关闭后的记录", contents)

    def test_whole_menu_row_is_clickable_including_blank_paper(self):
        # Empty space between label and shortcut must still invoke the action.
        self.click(305, 210)
        self.assertEqual(self.calls, ["read"])

    def test_disabled_action_rejects_mouse_and_shortcut(self):
        self.gui._set_busy_ui("读取中", cancellable=True)
        self.click(305, 210)
        self.gui.canvas.focus_force()
        self.root.event_generate("<F5>")
        self.root.update()
        self.assertEqual(self.calls, [])

    def test_scaled_letterboxed_menu_hit_target_moves_with_artwork(self):
        self.root.geometry("1280x681+0+0")
        self.root.update()
        # 128 px horizontal letterbox; original (305, 210) moves to (433, 210).
        self.click(433, 210)
        self.assertEqual(self.calls, ["read"])
        self.click(120, 210)
        self.assertEqual(self.calls, ["read"])

    def test_keyboard_focus_can_activate_menu(self):
        self.gui.canvas.focus_force()
        self.gui.canvas.event_generate("<Tab>")
        self.gui.canvas.event_generate("<Return>")
        self.root.update()
        self.assertEqual(self.calls, ["read"])

    def test_reverse_tab_works_when_tk_lacks_x11_keysym(self):
        from unittest.mock import patch
        from tkinter import ttk
        original_bind = tk.Canvas.bind

        def older_tk_bind(canvas, sequence=None, func=None, add=None):
            if sequence == "<ISO_Left_Tab>":
                raise tk.TclError('bad event type or keysym "ISO_Left_Tab"')
            return original_bind(canvas, sequence, func, add)

        self.gui.canvas.destroy()
        with patch.object(tk.Canvas, "bind", older_tk_bind):
            self.gui._build_layout(tk, ttk)
        self.root.update()
        self.gui.logbook.focus = "apply"
        self.gui.canvas.focus_force()
        self.gui.canvas.event_generate("<Shift-Tab>")
        self.root.update()
        self.assertEqual(self.gui.logbook.focus, "read")

    def test_configured_enter_shortcuts_override_focused_menu_action(self):
        self.gui.buttons["apply"].command = lambda: self.calls.append("apply")
        self.gui.canvas.focus_force()
        for sequence in ("<Return>", "<Control-Return>"):
            with self.subTest(sequence=sequence):
                self.gui.shortcuts["read"] = sequence
                self.gui._bind_shortcuts()
                self.gui.logbook.focus = "apply"
                self.calls.clear()
                self.gui.canvas.event_generate(sequence)
                self.root.update()
                self.assertEqual(self.calls, ["read"])
                self.gui.buttons["read"].configure(state="disabled")
                self.calls.clear()
                self.gui.canvas.event_generate(sequence)
                self.root.update()
                self.assertEqual(self.calls, [], "Disabled shortcuts must not activate the focused menu action")
                self.gui.buttons["read"].configure(state="normal")

    def test_rebinding_enter_shortcut_restores_menu_activation(self):
        self.gui.buttons["apply"].command = lambda: self.calls.append("apply")
        self.gui.shortcuts["read"] = "<Return>"
        self.gui._bind_shortcuts()
        self.gui.shortcuts["read"] = "<F5>"
        self.gui._bind_shortcuts()
        self.gui.logbook.focus = "apply"
        self.gui.canvas.focus_force()
        self.gui.canvas.event_generate("<Return>")
        self.root.update()
        self.assertEqual(self.calls, ["apply"])
        self.gui.canvas.event_generate("<F5>")
        self.root.update()
        self.assertEqual(self.calls, ["apply", "read"])

    def test_enlarged_menu_target_and_old_position_do_not_overlap(self):
        self.root.geometry("1536x1022+0+0")
        self.root.update()
        self.assertEqual(self.gui.canvas.winfo_width(), 1536)
        self.click(458, 315)
        self.assertEqual(self.calls, ["read"])
        self.click(120, 210)
        self.assertEqual(self.calls, ["read"])

    def test_batch_progress_shows_index_total_and_note(self):
        import queue
        self.gui.worker_queue = queue.Queue()
        self.gui.worker_queue.put(("progress", {"event": "inventory-scan-done", "unsolvedCount": 12}))
        self.gui.worker_queue.put(("progress", {"event": "read-current-note", "iteration": 2, "researchKey": "TEST_NOTE", "message": "正在读取"}))
        self.gui._poll_worker_queue()
        self.assertIn("3 / 12", self.gui.worker_label.get())
        self.assertIn("TEST_NOTE", self.gui.note_name.get())

    def test_final_inventory_scan_shows_confirmation_instead_of_extra_note(self):
        import queue
        self.gui.worker_queue = queue.Queue()
        self.gui.worker_queue.put(("progress", {"event": "inventory-scan-done", "unsolvedCount": 12}))
        self.gui.worker_queue.put(("progress", {"event": "apply-current-note-done", "iteration": 11}))
        self.gui._poll_worker_queue()
        self.assertIn("12 / 12", self.gui.worker_label.get())
        self.gui.worker_queue.put(("progress", {"event": "inventory-final-scan", "iteration": 12,
                                                "message": "最后确认背包未解笔记"}))
        self.gui._poll_worker_queue()
        self.assertIn("确认", self.gui.worker_label.get())
        self.assertNotIn("13", self.gui.worker_label.get())
        self.assertEqual(self.gui.status.get(), "最后确认背包未解笔记")

    def test_error_and_cancel_leave_distinct_visible_states(self):
        from thaum_nexus.client_bridge import OperationCancelled
        self.gui._handle_worker_error(RuntimeError("连接失败"))
        texts = [self.gui.canvas.itemcget(i, "text") for i in self.gui.canvas.find_all()
                 if self.gui.canvas.type(i) == "text"]
        self.assertTrue(any("失败" in text for text in texts))
        self.gui._handle_worker_error(OperationCancelled("cancelled"))
        texts = [self.gui.canvas.itemcget(i, "text") for i in self.gui.canvas.find_all()
                 if self.gui.canvas.type(i) == "text"]
        self.assertTrue(any("停止" in text for text in texts))

    def test_show_solution_uses_paper_preview_and_opaque_saved_image(self):
        from PIL import Image
        from thaum_nexus.note_io import ResearchNote
        from thaum_nexus.solver import solve

        note = ResearchNote.load(Path(__file__).parent / "fixtures" / "notes" / "two_roots_line_note.json")
        solution = solve(note.board, self.gui.kb)
        self.gui._show_solution(board=note.board, solution=solution,
                                note_label="TEST_NOTE", payload=solution.to_dict())
        self.assertEqual(self.gui.logbook.state, "success")
        self.assertEqual(self.gui.logbook.preview.getpixel((0, 0))[3], 0)
        with Image.open(self.gui.solution_image_path) as exported:
            self.assertEqual(exported.getpixel((0, 0))[3], 255)
        self.assertEqual(self.gui.buttons["save"].state, "normal")


if __name__ == "__main__":
    unittest.main()
