import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from core import Session
from guidance import load_guidance
from robot_controller import RobotController, MockRobotController, RobotWorker


def ready(session):
    session.new_task()
    session.choose_service("가져가기")
    session.choose_menu("latte")
    session.choose_temperature()
    session.navigate("confirm")


class LearningTests(unittest.TestCase):
    def test_full_order_and_completion_is_idempotent(self):
        s = Session()
        ready(s)
        self.assertTrue(s.complete()["completed"])
        self.assertEqual(s.screen, "complete")
        self.assertIsNone(s.complete())
        self.assertEqual(s.unaided_streak, 1)

    def test_required_choices_and_options(self):
        s = Session()
        s.new_task()
        with self.assertRaises(ValueError):
            s.navigate("options")
        s.choose_service("가져가기")
        s.choose_menu("latte")
        s.choose_temperature("따뜻하게")
        s.choose_menu("juice")
        self.assertNotIn("temperature", s.order)
        with self.assertRaises(ValueError):
            s.choose_temperature("따뜻하게")
        s.choose_temperature()
        self.assertEqual(s.order["temperature"], "차갑게")

    def test_help_and_back_preserve_history(self):
        s = Session()
        s.new_task("practice")
        s.choose_service("가져가기")
        s.navigate("menu")
        s.request_help()
        self.assertEqual(s.support_level, 2)
        s.back()
        s.request_help()
        self.assertEqual(s.support_level, 3)
        self.assertEqual(s.help_count, 2)
        self.assertEqual(s.order["service"], "가져가기")

    def test_two_unaided_tasks_reduce_support(self):
        s = Session()
        for _ in range(2):
            ready(s)
            s.complete()
        self.assertEqual(s.support_level, 2)
        self.assertEqual(s.unaided_streak, 0)
        ready(s)
        s.request_help()
        s.complete()
        self.assertEqual(s.unaided_streak, 0)
        s.new_task()
        self.assertEqual(s.help_count, 0)

    def test_minimum_support(self):
        s = Session(support_level=1)
        for _ in range(4):
            ready(s)
            s.complete()
        self.assertEqual(s.support_level, 1)


class GuidanceTests(unittest.TestCase):
    def test_all_screens_have_guidance(self):
        path = Path(__file__).resolve().parents[1] / "data" / "guidance.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(load_guidance(path), raw)

    def test_bad_json_uses_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            path.write_text("{", encoding="utf-8")
            with self.assertLogs(level="WARNING"):
                data = load_guidance(path)
            self.assertTrue(data["menu"]["intro"])


class WorkerTests(unittest.TestCase):
    def test_serial_execution_dedup_and_rejection(self):
        entered, release = threading.Event(), threading.Event()

        class Fake(MockRobotController):
            def __init__(self):
                self.actions = []

            def execute_action(self, action):
                self.actions.append(action)
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("테스트 시간 초과")

        controller = Fake()
        worker = RobotWorker(controller)
        try:
            self.assertFalse(worker.submit("FORWARD"))
            self.assertTrue(worker.submit("HINT"))
            self.assertTrue(entered.wait(2))
            self.assertFalse(worker.submit("HINT"))
            self.assertTrue(worker.submit("SUCCESS"))
            self.assertEqual(controller.actions, ["HINT"])
            release.set()
            worker.commands.join()
            self.assertEqual(controller.actions, ["HINT", "SUCCESS"])
            self.assertFalse(worker.available)
        finally:
            release.set()
            worker.stop()
            worker.thread.join(2)
        self.assertFalse(worker.thread.is_alive())

    def test_connection_failure_falls_back(self):
        class Broken(MockRobotController):
            def initialize(self):
                raise ConnectionError("분리됨")

        with self.assertLogs(level="ERROR"):
            worker = RobotWorker(Broken())
            worker.events.get(timeout=2)
        try:
            self.assertIsInstance(worker.controller, MockRobotController)
            self.assertFalse(worker.available)
            worker.submit("HINT")
            worker.commands.join()
        finally:
            worker.stop()
            worker.thread.join(2)

    def test_command_failure_falls_back_and_closes(self):
        class Broken(MockRobotController):
            def initialize(self):
                return True

            def execute_action(self, action):
                raise OSError("통신 실패")

        worker = RobotWorker(Broken())
        worker.events.get(timeout=2)
        with self.assertLogs(level="ERROR"):
            worker.submit("INTRO")
            worker.commands.join()
        self.assertFalse(worker.available)
        worker.stop()
        worker.thread.join(2)

    def test_real_adapter_uses_documented_led_api(self):
        from unittest.mock import MagicMock
        api = MagicMock()
        api.RoboDog.return_value.Open.return_value = True
        with patch("robot_controller.importlib.import_module", return_value=api):
            controller = RobotController("COM3")
            self.assertTrue(controller.initialize())
            controller.execute_action("HINT")
            controller.close()
        api.RoboDog.return_value.Open.assert_called_once_with("COM3")
        api.RoboDog.return_value.bodyLED.assert_called_once_with(160, 100, 0)
        api.RoboDog.return_value.Close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
