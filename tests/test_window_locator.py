import unittest

from thaum_nexus.vision import WindowInfo, score_minecraft_window


class WindowLocatorTests(unittest.TestCase):
    def test_minecraft_java_window_scores_above_normal_window(self):
        minecraft = WindowInfo(
            hwnd=1,
            title="GT: New Horizons 2.8.4",
            rect=(0, 0, 1280, 720),
            pid=10,
            process_path="javaw.exe",
        )
        normal = WindowInfo(
            hwnd=2,
            title="Notepad",
            rect=(0, 0, 1280, 720),
            pid=11,
            process_path="notepad.exe",
        )

        self.assertGreater(score_minecraft_window(minecraft), score_minecraft_window(normal))
        self.assertGreater(score_minecraft_window(minecraft), 200)

    def test_browser_guide_title_does_not_beat_java_game_window(self):
        browser_guide = WindowInfo(
            hwnd=4,
            title="GTNH 神秘时代 游戏攻略 - Google Chrome",
            rect=(0, 0, 1280, 720),
            pid=13,
            process_path="chrome.exe",
        )
        game = WindowInfo(
            hwnd=5,
            title="GT: New Horizons 2.8.4",
            rect=(0, 0, 1280, 720),
            pid=14,
            process_path="java.exe",
        )

        self.assertGreater(score_minecraft_window(game), score_minecraft_window(browser_guide))

    def test_tiny_java_popup_is_downranked(self):
        popup = WindowInfo(
            hwnd=3,
            title="Minecraft",
            rect=(0, 0, 120, 80),
            pid=12,
            process_path="javaw.exe",
        )

        self.assertLess(score_minecraft_window(popup), 100)


if __name__ == "__main__":
    unittest.main()
