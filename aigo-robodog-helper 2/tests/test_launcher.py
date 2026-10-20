import unittest
from unittest.mock import patch

from main import make_controller
from robot_controller import MockRobotController, RobotController


class LauncherSettingsTests(unittest.TestCase):
    def test_mock_does_not_import_robot_library(self):
        with patch("robot_controller.importlib.import_module", side_effect=AssertionError("하드웨어 접근")):
            controller = make_controller("mock", "COM3")
            self.assertIsInstance(controller, MockRobotController)
            self.assertFalse(controller.initialize())

    def test_explicit_port_and_auto_detection(self):
        controller = make_controller("real", " COM3 ")
        self.assertIsInstance(controller, RobotController)
        self.assertEqual(controller.port, "COM3")
        self.assertIsNone(make_controller("real", " ").port)
        self.assertIsNone(controller.dog)  # 화면 설정만으로 장치를 열지 않는다.

    def test_invalid_mode_and_port(self):
        for mode, port in (("other", ""), ("real", "COM3\nCOM4"), ("real", "x" * 129)):
            with self.subTest(mode=mode, port=port):
                with self.assertRaises(ValueError):
                    make_controller(mode, port)
