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
        for job in self.root.tk.call("after", "info"):
            self.root.after_cancel(job)
        self.root.destroy()
        self.assertEqual(self.callback_errors, [], "Tk callbacks must not fail during use or shutdown")

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
