"""실제 Tk 위젯으로 주문과 도움말을 검증한다. 화면이 없으면 건너뛴다."""
import json
from pathlib import Path
import shutil
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import kiosk as main
from robot_controller import MockRobotController, RobotWorker


class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.folder = tempfile.TemporaryDirectory()
        self.base = Path(self.folder.name)
        (self.base / "data").mkdir()
        shutil.copy(main.BASE / "data" / "guidance.json", self.base / "data" / "guidance.json")
        self.patch = patch.object(main, "BASE", self.base)
        self.patch.start()
        self.worker = RobotWorker(MockRobotController())
        self.app = main.App(self.root, self.worker)
        self.root.update()

    def tearDown(self):
        self.worker.stop()
        self.worker.thread.join(2)
        self.root.destroy()
        self.patch.stop()
        self.folder.cleanup()

    def click(self, label):
        def descendants(parent):
            for child in parent.winfo_children():
                yield child
                yield from descendants(child)
        for widget in descendants(self.app.content):
            if isinstance(widget, tk.Button) and widget.cget("text").startswith(label):
                widget.invoke()
                self.root.update()
                return
        self.fail(f"버튼 없음: {label}")

    def test_order_help_repeat_back_and_variant(self):
        self.click("혼자 해보기")
        self.assertEqual(self.app.next_widget.cget("state"), "disabled")
        self.app.help_request()
        self.assertEqual(self.app.state.support_level, 2)
        self.app.repeat()
        self.assertEqual(self.app.state.help_count, 1)
        self.click("가져가기")
        self.click("다음")
        self.app.back()
        self.root.update()
        self.assertEqual(self.app.state.order["service"], "가져가기")
        self.click("다음")
        self.app.help_request()
        self.assertEqual(self.app.state.support_level, 3)
        self.click("딸기주스")
        self.click("다음")
        self.assertFalse(any(isinstance(w, tk.Button) and "따뜻하게" in w.cget("text")
                             for w in self.app.content.winfo_children()))
        self.click("기본값으로 계속")
        self.click("주문 연습 완료")
        self.app.finish()  # 연속 완료 입력도 기록은 한 번만 저장
        records = (self.base / "data" / "results.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0])["help_count"], 2)
        self.click("다른 화면으로 도전")
        self.assertTrue(self.app.state.variant)
        self.assertEqual(self.app.state.help_count, 0)
