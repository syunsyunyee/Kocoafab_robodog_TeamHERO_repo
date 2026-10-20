from pathlib import Path
import json
import random
import shutil
import tempfile
import unittest
from unittest.mock import Mock, call
from types import SimpleNamespace

from web_kiosk import BASE, KioskModel
from reactions import REACTIONS, ReactionPicker, guidance_voice_capability, supported_reactions
from robot_controller import RobotController
from test_web import FakeWorker
from curriculum import STAGES, CURRICULUM_VERSION, random_recipe, describe_order
from core import MENUS, OPTION_SPECS, FIELD_LABELS, order_total


class CurriculumTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / "data").mkdir()
        shutil.copy(BASE / "data/guidance.json", self.base / "data/guidance.json")
        self.worker = FakeWorker()
        self.model = KioskModel(self.worker, self.base, rng=random.Random(23))
        self.counter = 0

    def tearDown(self):
        self.temp.cleanup()

    def act(self, action, value=""):
        self.counter += 1
        return self.model.apply({"action": action, "value": value, "revision": self.model.revision,
                                 "requestId": str(self.counter)})

    def full_order(self):
        for key in ("service", "menu"):
            self.act(key, self.model.target[key])
            self.act("next")
        for key, value in self.model.target.items():
            if key not in ("service", "menu"):
                self.act(key, value)
        self.act("next")
        self.act("complete")

    def test_sixteen_whole_order_missions_and_progress(self):
        for stage_id in range(1, len(STAGES) + 1):
            self.act("start_stage", str(stage_id)) if stage_id == 1 else self.act("next_stage")
            self.assertEqual(self.model.session.screen, "service_mode")
            self.assertEqual(self.model.session.order, {})
            self.assertEqual(set(self.model.target), set(FIELD_LABELS))
            self.full_order()
            self.assertEqual(self.model.session.screen, "complete")
        loaded = KioskModel(FakeWorker(), self.base)
        self.assertEqual(loaded.completed_stages, set(range(1, 17)))
        rows = [json.loads(line) for line in (self.base / "data/results.jsonl").read_text().splitlines()]
        self.assertEqual([row["stage"] for row in rows], list(range(1, 17)))
        self.assertEqual(rows[-2]["order"]["side"], "초코 머핀")
        self.assertEqual(rows[-2]["order"], STAGES[14].target)
        self.assertEqual(self.model.snapshot()["total"], order_total(self.model.target))

    def test_shot_stage_and_full_option_stage_block_missing_extras(self):
        from core import OPTION_SPECS
        for stage_id in (7, 15):
            self.act("home")
            self.act("start_stage", str(stage_id))
            self.act("service", "가져가기")
            self.act("next")
            self.act("menu", self.model.target["menu"])
            self.act("next")
            self.act("temperature", "차갑게")
            with self.assertRaises(ValueError):
                self.act("next")
            for key in OPTION_SPECS:
                self.act(key, self.model.target[key])
            self.act("next")
            self.act("complete")
            self.assertEqual(self.model.session.screen, "complete")

    def test_category_mapping_and_retry(self):
        self.act("start_stage", "2")
        menus = {item["id"]: item for item in self.model.snapshot()["menus"]}
        self.assertEqual(menus["strawberry_latte"]["category"], "음료")
        self.assertEqual(menus["peach_tea"]["category"], "티")
        target = dict(self.model.target)
        self.full_order()
        self.act("retry")
        self.assertEqual(self.model.target, target)
        self.assertEqual(self.model.session.order, {})
        self.act("back")
        self.assertEqual(self.model.session.screen, "start")

    def test_invalid_stage_and_damaged_progress(self):
        for value in ("0", "17", "__import__", "1.0"):
            with self.assertRaises(ValueError):
                self.act("start_stage", value)
        (self.base / "data/progress.json").write_text(json.dumps({"curriculumVersion": CURRICULUM_VERSION, "completedByMode": {"guided": [True, 19], "practice": []}}))
        with self.assertLogs(level="WARNING"):
            model = KioskModel(FakeWorker(), self.base)
        self.assertFalse(model.completed_stages)

    def test_random_replay_is_stable_new_draw_changes_target_and_screen_starts_empty(self):
        self.act("start_stage", "16")
        first = dict(self.model.target)
        description = self.model.snapshot()["taskDescription"]
        self.assertEqual(description, describe_order(first))
        self.assertTrue(self.model.snapshot()["lesson"]["randomized"])
        self.act("help")
        self.assertEqual(self.model.target, first)
        self.full_order()
        self.act("retry")
        self.assertEqual(self.model.target, first)
        self.assertEqual(self.model.session.order, {})
        self.full_order()
        self.act("new_random")
        self.assertNotEqual(self.model.target, first)
        self.assertEqual(self.model.session.screen, "service_mode")
        self.assertEqual(self.model.session.order, {})

    def test_random_generator_reaches_all_choices_and_only_valid_temperatures(self):
        rng = random.Random(112)
        orders = [random_recipe(rng) for _ in range(2000)]
        self.assertEqual({o["menu"] for o in orders}, set(MENUS))
        self.assertEqual({o["service"] for o in orders}, {"가져가기", "매장에서 먹기"})
        for key, spec in OPTION_SPECS.items():
            self.assertEqual({o[key] for o in orders}, set(spec[1]))
        for order in orders:
            self.assertIn(order["temperature"], MENUS[order["menu"]][2])
            self.assertEqual(set(order), set(FIELD_LABELS))
        self.assertGreater(len({json.dumps(o, sort_keys=True) for o in orders}), 1000)
        first = random_recipe(random.Random(1))
        self.assertNotEqual(first, random_recipe(random.Random(1), first))

    def test_fixed_curriculum_covers_every_choice_and_has_distinct_whole_orders(self):
        fixed = STAGES[:-1]
        self.assertEqual({s.target["menu"] for s in fixed}, set(MENUS))
        for key, spec in OPTION_SPECS.items():
            self.assertEqual({s.target[key] for s in fixed}, set(spec[1]))
        self.assertEqual(len({json.dumps(s.target, sort_keys=True) for s in fixed}), len(fixed))
        self.assertTrue(all(s.screens == STAGES[0].screens for s in STAGES))

    def test_guidance_falls_back_to_pc_in_mock_and_real_modes(self):
        snapshot = self.model.snapshot()
        self.assertEqual(snapshot["voice"]["route"], "pc")
        self.worker.controller.mode = "real"
        self.worker.available = True
        self.assertFalse(self.model.snapshot()["voice"]["robotTextSpeech"])
        self.assertIn("공개", guidance_voice_capability()["reason"])


class ReactionTests(unittest.TestCase):
    def test_shuffle_bag_has_all_body_motions_and_no_adjacent_repeats(self):
        picker = ReactionPicker(random.Random(12))
        ids = [item["id"] for item in REACTIONS]
        chosen = [picker.pick(ids)["id"] for _ in range(60)]
        for i in range(0, 60, len(ids)):
            self.assertEqual(set(chosen[i:i + len(ids)]), set(ids))
        self.assertTrue(all(a != b for a, b in zip(chosen, chosen[1:])))

    def test_only_supported_reactions_are_selected(self):
        picker = ReactionPicker(random.Random(4))
        self.assertEqual(picker.pick(["greeting"])["id"], "greeting")
        self.assertEqual(picker.pick(["stretch"])["id"], "stretch")
        with self.assertRaises(ValueError):
            picker.pick([])

    def test_sequences_are_distinct_and_have_four_ending_poses(self):
        sequences = [p["sequence"] for p in REACTIONS]
        self.assertEqual(len(sequences), 15)
        self.assertEqual(len(set(sequences)), 15)
        self.assertEqual({s[-1] for s in sequences}, {"GREETING", "SITDOWN", "STRETCH", "STANDUP"})

    def test_all_reactions_follow_sequence_and_wait_at_each_pose(self):
        for profile in REACTIONS:
            with self.subTest(profile=profile["id"]):
                dog = SimpleNamespace(gesture=Mock(), leg_bend=Mock(), headLEDExp=Mock(), headLEDDraw=Mock(), headLEDClear=Mock())
                controller = RobotController(sleeper=Mock())
                controller.dog = dog
                controller.api = SimpleNamespace(GREETING=1, STRETCH=2, STANDUP=3, SITDOWN=4,
                                                 ALL_LEG=10, LEFT_LEG=11, RIGHT_LEG=12, FRONT_LEG=13, BACK_LEG=14)
                controller.picker = SimpleNamespace(pick=lambda supported: profile)
                controller._optional_gesture()
                self.assertEqual(dog.gesture.call_args_list, [call(getattr(controller.api, name)) for name in profile["sequence"]])
                dog.leg_bend.assert_not_called()
                self.assertEqual(controller.sleep.call_args_list, [call(2.)] * len(profile["sequence"]))
                self.assertEqual(controller.last_reaction, profile["name"])
                self.assertEqual(controller.take_warnings(), [])
                dog.headLEDExp.assert_not_called()
                dog.headLEDDraw.assert_not_called()
                dog.headLEDClear.assert_not_called()

    def test_supported_motions_use_documented_aliases_and_filter_missing_leg_api(self):
        api = SimpleNamespace(인사하기=1, 기지개켜기=2, 앉기자세=3, 준비=4)
        dog = SimpleNamespace(bodyLED=Mock(), gesture=Mock())
        self.assertEqual({p["id"] for p in supported_reactions(api, dog)}, {p["id"] for p in REACTIONS})
        dog.headLEDExp = Mock()
        api.초롱초롱, api.ILOVEU, api.감사 = 10, 11, 12
        controller = RobotController(sound_enabled=False, sleeper=Mock())
        controller.api, controller.dog = api, dog
        for _ in REACTIONS:
            controller.execute_action("PRAISE")
        self.assertEqual({args.args[0] for args in dog.gesture.call_args_list}, {1, 2, 3, 4})
        self.assertEqual(controller.take_warnings(), [])

    def test_missing_constants_filter_entire_sequence(self):
        api = SimpleNamespace(GREETING=1, STANDUP=2)
        dog = SimpleNamespace(gesture=Mock())
        self.assertEqual([p["id"] for p in supported_reactions(api, dog)], ["greeting"])
