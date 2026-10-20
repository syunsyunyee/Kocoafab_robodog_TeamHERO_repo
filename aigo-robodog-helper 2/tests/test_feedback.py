import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

from robot_controller import RobotController, RobotWorker, MockRobotController
from reactions import REACTIONS


class FeedbackTests(unittest.TestCase):
    def test_effect_tail_keeps_busy_and_rejects_all_other_effects(self):
        import time
        entered = threading.Event()
        starts = []
        class ShortReaction(MockRobotController):
            mode = "real"
            def initialize(self):
                return True
            def execute_action(self, action):
                starts.append(time.monotonic())
                self.sound_until = time.monotonic() + .25
                entered.set()
        worker = RobotWorker(ShortReaction())
        try:
            self.assertTrue(worker.submit("SOUND_TEST"))
            self.assertTrue(entered.wait(2))
            for action in ("PRAISE", "SUCCESS", "GESTURE_TEST", "SOUND_TEST"):
                self.assertFalse(worker.submit(action))
            self.assertIn("SOUND_TEST", worker.pending)
            worker.commands.join()
            self.assertEqual(len(starts), 1)
            self.assertEqual(worker.pending, set())
        finally:
            worker.stop()
            worker.thread.join(2)

    def controller(self, dog):
        c = RobotController(sleeper=Mock())
        c.dog = dog
        dog.headLEDExp = Mock()
        c.api = SimpleNamespace(멍멍=12, 안녕=16, 중간=2, 개소리=1, 초롱초롱=20, GREETING=7, STANDUP=8)
        return c

    def test_two_argument_sound_and_gesture_wait(self):
        calls = []
        class Dog:
            bodyLED = Mock()
            gesture = Mock()
            def sound(self, track, volume):
                calls.append((track, volume))
        dog = Dog()
        c = self.controller(dog)
        c.execute_action("PRAISE")
        self.assertEqual(calls, [(12, 2)])
        self.assertEqual(dog.gesture.call_args_list, [call(7), call(8)])
        self.assertEqual(c.sleep.call_args_list, [call(2.0), call(2.0)])
        self.assertEqual(c.take_warnings(), [])

    def test_three_argument_sound(self):
        calls = []
        class Dog:
            bodyLED = Mock()
            def sound(self, theme, track, volume):
                calls.append((theme, track, volume))
        c = self.controller(Dog())
        c.execute_action("SOUND_TEST")
        self.assertEqual(calls, [(1, 12, 2)])

    def test_sound_failure_is_reported_without_retry(self):
        class Dog:
            bodyLED = Mock()
            count = 0
            def sound(self, track, volume):
                self.count += 1
                raise TypeError("장치 내부 오류")
        dog = Dog()
        c = self.controller(dog)
        with self.assertLogs(level="WARNING"):
            c.execute_action("SOUND_TEST")
        self.assertEqual(dog.count, 1)
        self.assertIn("소리 재생 실패", c.take_warnings()[0])

    def test_gesture_failure_still_waits_and_reports(self):
        dog = SimpleNamespace(bodyLED=Mock(), sound=Mock(), gesture=Mock(side_effect=OSError("전송 오류")))
        c = self.controller(dog)
        with self.assertLogs(level="WARNING"):
            c.execute_action("GESTURE_TEST")
        self.assertEqual(c.sleep.call_args_list, [call(2.0), call(2.0)])
        self.assertIn("애교 동작 실행 실패", c.take_warnings()[0])

    def test_missing_constants_and_opt_out(self):
        c = self.controller(SimpleNamespace(bodyLED=Mock(), sound=Mock(), gesture=Mock()))
        c.api = SimpleNamespace()
        c.picker = SimpleNamespace(pick=lambda supported: REACTIONS[0])
        with self.assertLogs(level="WARNING"):
            c.execute_action("SUCCESS")
        self.assertEqual(len(c.take_warnings()), 3)
        c.sound_enabled = c.gestures_enabled = False
        with self.assertLogs(level="WARNING"):
            c.execute_action("SUCCESS")
        c.dog.sound.assert_not_called()
        c.dog.gesture.assert_not_called()

    def test_praise_throttles_until_motion_finishes(self):
        entered, release = threading.Event(), threading.Event()
        class Fake(MockRobotController):
            def execute_action(self, action):
                entered.set()
                release.wait(2)
        worker = RobotWorker(Fake())
        try:
            self.assertTrue(worker.submit("PRAISE"))
            self.assertTrue(entered.wait(2))
            self.assertFalse(worker.submit("PRAISE"))
            self.assertFalse(worker.submit("GESTURE_TEST"))
            self.assertFalse(worker.submit("SUCCESS"))
            self.assertFalse(worker.submit("SOUND_TEST"))
            release.set()
            worker.commands.join()
            self.assertFalse(worker.submit("PRAISE"))
        finally:
            release.set()
            worker.stop()
            worker.thread.join(2)

    def test_guided_completion_action_does_not_repeat_sound_or_body_motion(self):
        dog = SimpleNamespace(bodyLED=Mock(), sound=Mock(), gesture=Mock(), leg_bend=Mock())
        c = self.controller(dog)
        c.execute_action("COMPLETE")
        dog.sound.assert_not_called()
        dog.gesture.assert_not_called()
        dog.leg_bend.assert_not_called()

    def test_each_random_reward_pairs_one_eye_one_sound_and_one_sequence(self):
        for profile in REACTIONS:
            with self.subTest(profile=profile["id"]):
                dog = SimpleNamespace(bodyLED=Mock(), headLEDExp=Mock(), sound=Mock(), gesture=Mock(), leg_bend=Mock(), motor=Mock(), move=Mock(), headLEDClear=Mock())
                c = RobotController(sleeper=Mock())
                c.api = SimpleNamespace(STANDUP=1, GREETING=2, SITDOWN=3, STRETCH=4, 초롱초롱=10, ILOVEU=11, 감사=12, 멍멍=20, 안녕=21, 띠리리=22, 중간=30)
                c.dog = dog
                c.picker = SimpleNamespace(pick=lambda supported: profile)
                ordered = Mock()
                ordered.attach_mock(dog.headLEDExp, "eye")
                ordered.attach_mock(dog.sound, "sound")
                ordered.attach_mock(dog.gesture, "gesture")
                c.execute_action("PRAISE")
                dog.headLEDExp.assert_called_once_with(getattr(c.api, profile["expression"]))
                if profile["sound"] is None:
                    dog.sound.assert_not_called()
                else:
                    dog.sound.assert_called_once_with(getattr(c.api, profile["sound"]), 30)
                self.assertEqual(dog.gesture.call_args_list, [call(getattr(c.api, name)) for name in profile["sequence"]])
                self.assertEqual(c.sleep.call_args_list, [call(2.)] * len(profile["sequence"]))
                self.assertEqual([entry[0] for entry in ordered.mock_calls],
                                 ["eye"] + (["sound"] if profile["sound"] is not None else [])
                                 + ["gesture"] * len(profile["sequence"]))
                dog.leg_bend.assert_not_called()
                dog.motor.assert_not_called()
                dog.move.assert_not_called()
                dog.headLEDClear.assert_not_called()
                self.assertEqual(c.take_warnings(), [])

    def test_gratitude_profiles_have_no_added_sound_and_other_effects_remain(self):
        gratitude = [p for p in REACTIONS if p["expression"] == "감사"]
        self.assertEqual(len(gratitude), 5)
        self.assertTrue(all(p["sound"] is None for p in gratitude))
        self.assertEqual({p["sound"] for p in REACTIONS if p["expression"] != "감사"},
                         {"멍멍", "안녕"})

    def test_sound_reservation_rejects_effects_even_without_pending_motion(self):
        import time
        worker = RobotWorker(MockRobotController())
        try:
            worker.audio_until = time.monotonic() + 1.0
            for action in ("PRAISE", "SUCCESS", "GESTURE_TEST", "SOUND_TEST"):
                self.assertFalse(worker.submit(action))
            self.assertTrue(worker.commands.empty())
            worker.audio_until = 0.0
            self.assertTrue(worker.submit("SOUND_TEST"))
            worker.commands.join()
        finally:
            worker.stop()
            worker.thread.join(2)

    def test_eye_failure_does_not_suppress_sound_or_motion(self):
        dog = SimpleNamespace(bodyLED=Mock(), sound=Mock(), gesture=Mock())
        c = self.controller(dog)
        dog.headLEDExp.side_effect = OSError("눈 통신 오류")
        with self.assertLogs(level="WARNING"):
            c.execute_action("PRAISE")
        dog.sound.assert_called_once_with(12, 2)
        self.assertEqual(dog.gesture.call_args_list, [call(7), call(8)])
        self.assertIn("눈 표정 표시 실패", c.take_warnings()[0])

    def test_narration_actions_do_not_also_play_robot_effects(self):
        dog = SimpleNamespace(bodyLED=Mock(), sound=Mock(), gesture=Mock())
        c = self.controller(dog)
        for action in ("WELCOME", "HINT", "STEP_GUIDE", "COMPLETE"):
            c.execute_action(action)
        dog.sound.assert_not_called()
        dog.gesture.assert_not_called()

    def test_real_effect_reserves_audio_window_before_worker_starts(self):
        import time
        release = threading.Event()
        class RealFake(MockRobotController):
            def initialize(self):
                return True
            def execute_action(self, action):
                release.wait(2)
        worker = RobotWorker(RealFake())
        try:
            worker.events.get(timeout=2)
            self.assertTrue(worker.submit("PRAISE"))
            self.assertGreater(worker.audio_until - time.monotonic(), 4.0)
            self.assertFalse(worker.submit("SUCCESS"))
        finally:
            release.set()
            worker.stop()
            worker.thread.join(2)

    def test_effect_queued_during_real_connection_also_reserves_audio(self):
        import time
        entered, release = threading.Event(), threading.Event()
        class Connecting(MockRobotController):
            mode = "real"
            def initialize(self):
                entered.set()
                release.wait(2)
                return True
        worker = RobotWorker(Connecting())
        try:
            self.assertTrue(entered.wait(2))
            self.assertFalse(worker.available)
            self.assertTrue(worker.submit("PRAISE"))
            self.assertGreater(worker.audio_until - time.monotonic(), 4.0)
        finally:
            release.set()
            worker.stop()
            worker.thread.join(2)
