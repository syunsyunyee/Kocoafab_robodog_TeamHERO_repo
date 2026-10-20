from datetime import datetime
from pathlib import Path
import json
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call

from medication import MedicationReminder
from robot_controller import MockRobotController, RobotController, RobotWorker
import test_web
from test_web import FakeWorker


class MedicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "medication.json"
        self.now = datetime(2026, 10, 17, 8, 30, 20)
        self.clock = 100.0
        self.med = MedicationReminder(self.path, lambda: self.now, lambda: self.clock)
        self.worker = FakeWorker()

    def tearDown(self):
        self.temp.cleanup()

    def start_alert(self):
        self.med.configure("08:30")
        self.med.tick(self.worker)
        self.assertEqual(self.med.status, "preparing")
        self.clock += 2
        self.med.tick(self.worker)
        self.assertEqual(self.med.status, "alerting")
        self.med.action_finished("MED_ALERT")
        self.assertEqual(self.med.status, "waiting")

    def test_time_validation_and_next_occurrence_persist(self):
        for value in ("8:30", "24:00", "12:60", "", None, "08:30:00"):
            with self.assertRaises(ValueError):
                self.med.configure(value)
        self.med.configure("08:29")
        self.assertEqual(self.med.due, datetime(2026, 10, 18, 8, 29))
        restored = MedicationReminder(self.path)
        self.assertEqual(restored.status, "armed")
        self.assertEqual(restored.due, self.med.due)

    def test_due_once_repeats_every_five_seconds_and_cancel(self):
        self.start_alert()
        self.med.tick(self.worker)
        self.clock += 4.9
        self.med.tick(self.worker)
        self.assertEqual(self.worker.actions, ["MED_ALERT"])
        self.clock += .1
        self.med.tick(self.worker)
        self.assertEqual(self.worker.actions, ["MED_ALERT", "MED_REPEAT"])
        self.med.cancel()
        self.med.action_finished("MED_REPEAT")
        self.clock += 120
        self.med.tick(self.worker)
        self.assertEqual(self.med.status, "idle")
        self.assertFalse(self.med.action_allowed("MED_REPEAT"))
        self.assertEqual(len(self.worker.actions), 2)

    def test_restart_resumes_unconfirmed_alarm_not_confirmed(self):
        self.start_alert()
        restored = MedicationReminder(self.path, lambda: self.now, lambda: self.clock)
        self.assertEqual(restored.status, "armed")
        restored.tick(self.worker)
        self.assertEqual(restored.status, "preparing")

    def test_mock_qr_and_real_manual_confirmation_restriction(self):
        self.start_alert()
        self.med.confirm(self.worker, simulated=True)
        self.assertEqual(self.worker.actions[-1], "MED_CONFIRM")
        self.med.action_finished("MED_CONFIRM")
        self.assertEqual(self.med.status, "done")
        self.assertEqual(MedicationReminder(self.path).status, "done")
        self.med.status = "waiting"
        self.worker.controller.mode = "real"
        with self.assertRaises(ValueError):
            self.med.confirm(self.worker, simulated=True)

    def test_exact_stop_qr_retry_reconnect_and_decode_error(self):
        self.start_alert()
        dog = SimpleNamespace(is_ai_alive=Mock(return_value=True), ai_mode=Mock(return_value=None), get_qrcode=Mock())
        self.worker.controller = SimpleNamespace(mode="real", dog=dog, api=SimpleNamespace(QRCODE_READ=4))
        self.worker.available = True
        self.med._read_qr(self.worker, self.clock)
        self.assertFalse(self.med.qr_ready)
        self.med._read_qr(self.worker, self.clock + 1)
        dog.ai_mode.assert_called_once()
        self.clock += 15
        dog.ai_mode.return_value = 4
        self.med._read_qr(self.worker, self.clock)
        self.assertTrue(self.med.qr_ready)
        dog.get_qrcode.side_effect = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")
        self.med._read_qr(self.worker, self.clock)
        self.assertEqual(self.med.status, "waiting")
        dog.get_qrcode.side_effect = None
        for value in ("스탑", "stop", "STOP ", "STOP"):
            dog.get_qrcode.return_value = value
            self.med._read_qr(self.worker, self.clock)
            self.assertEqual(self.med.status, "confirming" if value == "STOP" else "waiting")
        self.assertEqual(self.worker.actions.count("MED_CONFIRM"), 1)
        self.med.status = "waiting"
        dog.is_ai_alive.return_value = False
        self.med._read_qr(self.worker, self.clock)
        self.assertFalse(self.med.qr_ready)

    def test_damaged_settings_do_not_arm_alarm(self):
        self.path.write_text(json.dumps({"status": "armed", "time": "25:00"}))
        self.assertEqual(MedicationReminder(self.path).status, "idle")

    def test_multiple_times_and_medicine_names_persist_and_remove(self):
        self.med.add("09:00", "아침 약")
        self.med.add("12:30", "점심 약, 비타민")
        restored = MedicationReminder(self.path)
        self.assertEqual([(e["time"], e["medicine"]) for e in restored.schedules],
                         [("09:00", "아침 약"), ("12:30", "점심 약, 비타민")])
        restored.remove(restored.schedules[0]["id"])
        self.assertEqual(MedicationReminder(self.path).snapshot()["pendingCount"], 1)
        self.assertEqual(restored.time_text, "12:30")

    def test_medicine_validation_and_duplicate_are_rejected(self):
        for name in ("", "  ", None, "약\n이름", "약" * 81):
            with self.assertRaises(ValueError):
                self.med.add("09:00", name)
        self.med.add("09:00", "아침 약")
        with self.assertRaises(ValueError):
            self.med.add("09:00", "아침 약")
        self.assertEqual(len(self.med.schedules), 1)

    def test_same_time_group_confirm_does_not_confirm_other_times(self):
        self.med.add("08:30", "아침 약")
        self.med.add("08:30", "비타민")
        self.med.add("09:00", "다른 시간 약")
        self.med.tick(self.worker); self.clock += 2; self.med.tick(self.worker)
        self.med.action_finished("MED_ALERT")
        self.assertEqual(self.med.snapshot()["activeMedicines"], ["아침 약", "비타민"])
        self.med.confirm(self.worker, simulated=True); self.med.action_finished("MED_CONFIRM")
        self.assertEqual([e["status"] for e in self.med.schedules], ["done", "done", "armed"])
        self.assertEqual(self.med.time_text, "09:00")

    def test_cancel_all_includes_active_group_and_later_schedule(self):
        self.med.add("08:30", "아침 약"); self.med.add("09:00", "다음 약")
        self.med.tick(self.worker)
        self.med.cancel()
        self.assertEqual(self.med.schedules, [])
        self.assertEqual(json.loads(self.path.read_text())["schedules"], [])
        self.assertEqual(self.med.status, "idle")

    def test_cancel_all_never_rearms_after_late_callbacks_or_restart(self):
        for phase in ("preparing", "alerting", "waiting", "stopping", "confirming"):
            with self.subTest(phase=phase):
                self.med = MedicationReminder(self.path, lambda: self.now, lambda: self.clock)
                self.med.configure("08:30")
                self.med.add("09:00", "다음 약")
                self.med.tick(self.worker)
                self.med.status = phase
                self.med.cancel()
                for action in ("MED_ALERT", "MED_REPEAT", "MED_CONFIRM"):
                    self.assertFalse(self.med.action_allowed(action))
                    self.med.action_finished(action)
                restored = MedicationReminder(self.path, lambda: datetime(2026, 10, 18, 9, 30), lambda: self.clock)
                previous = len(self.worker.actions)
                restored.tick(self.worker)
                self.assertEqual(len(self.worker.actions), previous)
                self.assertEqual(restored.snapshot()["pendingCount"], 0)
                self.assertEqual(restored.snapshot()["schedules"], [])
                self.assertFalse(restored.snapshot()["active"])
                self.assertEqual(restored.status, "idle")

    def test_cancel_all_also_removes_completed_history(self):
        self.start_alert()
        self.med.confirm(self.worker, simulated=True)
        self.med.action_finished("MED_CONFIRM")
        self.med.add("09:00", "다음 약")
        self.assertEqual(len(self.med.schedules), 2)
        self.med.cancel()
        self.assertEqual(self.med.snapshot()["schedules"], [])
        self.assertEqual(MedicationReminder(self.path).schedules, [])

    def test_old_single_schedule_migrates_without_losing_due_time(self):
        self.path.write_text(json.dumps({"status": "waiting", "time": "08:30", "due": "2026-10-17T08:30:00"}))
        restored = MedicationReminder(self.path)
        self.assertEqual(restored.status, "armed")
        self.assertEqual(restored.schedules[0]["medicine"], "약 이름 미설정")
        self.assertEqual(restored.schedules[0]["due"], datetime(2026, 10, 17, 8, 30))

    def test_stop_during_bark_is_latched_before_return_to_ready(self):
        import time
        actions = []
        med = self.med
        class Controller(MockRobotController):
            mode = "real"
            def __init__(self):
                super().__init__()
                self.api = SimpleNamespace(QRCODE_READ=4)
                self.dog = SimpleNamespace(is_ai_alive=Mock(return_value=True), get_qrcode=Mock(return_value="STOP"))
                self.sound_until = 0.0
            def initialize(self):
                return True
            def execute_action(self, action):
                actions.append(action)
                if action == "MED_ALERT":
                    med.qr_ready = True
                    self.sound_until = time.monotonic() + .25
                    worker.audio_until = self.sound_until
        controller = Controller()
        worker = RobotWorker(controller)
        worker.medication = med
        try:
            med.configure("08:30"); med.tick(worker); self.clock += 2; med.tick(worker)
            deadline = time.monotonic() + 2
            while med.status != "done" and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(med.status, "done")
            self.assertEqual(actions, ["MED_ALERT", "MED_CONFIRM"])
            controller.dog.get_qrcode.assert_called_once()
        finally:
            worker.stop(); worker.thread.join(2)

    def test_held_stop_qr_cannot_confirm_next_time_without_being_removed(self):
        self.start_alert()
        self.med.add("09:00", "다음 약")
        self.med.confirm(self.worker, simulated=True); self.med.action_finished("MED_CONFIRM")
        self.now = datetime(2026, 10, 17, 9, 0)
        self.med.tick(self.worker); self.clock += 2; self.med.tick(self.worker)
        self.med.action_finished("MED_ALERT")
        dog = SimpleNamespace(is_ai_alive=Mock(return_value=True), get_qrcode=Mock(return_value="STOP"))
        self.worker.controller = SimpleNamespace(mode="real", dog=dog, api=SimpleNamespace(QRCODE_READ=4))
        self.med.qr_ready = True
        self.med._read_qr(self.worker, self.clock)
        self.assertEqual(self.med.status, "waiting")
        dog.get_qrcode.return_value = None
        self.med._read_qr(self.worker, self.clock)
        dog.get_qrcode.return_value = "STOP"
        self.med._read_qr(self.worker, self.clock)
        self.assertEqual(self.med.status, "confirming")

    def test_alarm_adapter_uses_one_sound_and_waits_for_each_motion(self):
        dog = SimpleNamespace(bodyLED=Mock(), headLEDDraw=Mock(), headLEDExp=Mock(), sound=Mock(), gesture=Mock(), Open=Mock())
        c = RobotController(sleeper=Mock())
        c.dog = dog
        c.api = SimpleNamespace(멍멍=1, 중간=2, STRETCH=4, STANDUP=2, 준비=0, 초롱초롱=0)
        c.execute_action("MED_ALERT")
        dog.sound.assert_called_once_with(1, 2)
        dog.headLEDExp.assert_called_once_with(0)
        dog.headLEDDraw.assert_not_called()
        self.assertEqual(dog.gesture.call_args_list, [call(4), call(2)])
        self.assertEqual(c.sleep.call_args_list, [call(2.), call(2.)])
        dog.Open.assert_not_called()
        dog.sound.reset_mock(); dog.gesture.reset_mock()
        c.execute_action("MED_REPEAT")
        dog.sound.assert_called_once_with(1, 2)
        dog.gesture.assert_not_called()
        dog.sound.reset_mock()
        c.execute_action("MED_CONFIRM")
        dog.sound.assert_not_called()
        dog.gesture.assert_called_once_with(0)
        dog.headLEDDraw.assert_called_once_with(bytearray(8), bytearray(8))

    def test_worker_alarm_rejects_other_reactions_and_cancel_does_not_resurrect(self):
        entered, release = threading.Event(), threading.Event()
        class Controller(MockRobotController):
            def execute_action(self, action):
                entered.set()
                release.wait(2)
        worker = RobotWorker(Controller())
        worker.medication = self.med
        try:
            self.med.configure("08:30")
            self.med.tick(worker)
            self.clock += 2
            self.med.tick(worker)
            self.assertTrue(entered.wait(2))
            for action in ("PRAISE", "SUCCESS", "GESTURE_TEST", "SOUND_TEST", "MED_REPEAT"):
                self.assertFalse(worker.submit(action))
            self.med.cancel()
            release.set()
            worker.commands.join()
            self.assertEqual(self.med.status, "idle")
        finally:
            release.set(); worker.stop(); worker.thread.join(2)


class MedicationModelTests(unittest.TestCase):
    setUp = test_web.ModelTests.setUp
    tearDown = test_web.ModelTests.tearDown
    act = test_web.ModelTests.act

    def test_html_settings_switching_and_active_alarm_blocks_kiosk(self):
        self.assertEqual(self.model.snapshot()["app"], "hub")
        self.act("open_app", "medication")
        data = self.act("med_set", "23:59")
        self.assertEqual(data["medication"]["time"], "23:59")
        self.act("open_app", "kiosk")
        self.assertEqual(self.model.snapshot()["medication"]["status"], "armed")
        self.model.medication.status = "waiting"
        with self.assertRaises(ValueError):
            self.act("gesture_test")
        self.act("med_cancel")
        self.assertEqual(self.model.snapshot()["medication"]["status"], "idle")
