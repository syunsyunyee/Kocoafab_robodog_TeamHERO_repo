from pathlib import Path
import json
import queue
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from web_kiosk import BASE, KioskModel, LocalKioskServer


class FakeWorker:
    def __init__(self):
        self.controller = SimpleNamespace(mode="mock")
        self.available = False
        self.events = queue.Queue()
        self.pending = set()
        self.actions = []

    def submit(self, action):
        self.actions.append(action)
        return True


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / "data").mkdir()
        shutil.copy(BASE / "data/guidance.json", self.base / "data/guidance.json")
        self.worker = FakeWorker()
        self.model = KioskModel(self.worker, self.base)
        self.counter = 0

    def tearDown(self):
        self.temp.cleanup()

    def act(self, action, value=""):
        self.counter += 1
        return self.model.apply({"action": action, "value": value,
                                 "revision": self.model.revision, "requestId": str(self.counter)})

    def test_correct_choices_reward_once_and_save_once(self):
        self.act("start", "guided")
        self.act("service", "매장에서 먹기")
        self.assertNotIn("PRAISE", self.worker.actions)
        with self.assertRaises(ValueError):
            self.act("next")
        self.act("service", "가져가기")
        self.act("service", "가져가기")
        self.assertEqual(self.worker.actions.count("PRAISE"), 1)
        self.act("next")
        self.act("menu", "americano")
        self.act("next")
        self.act("temperature", "차갑게")
        self.act("next")
        payload = {"action": "complete", "value": "", "revision": self.model.revision, "requestId": "complete"}
        self.model.apply(payload)
        self.model.apply(payload)
        self.act("complete")
        self.assertEqual(self.worker.actions.count("PRAISE"), 3)
        self.assertEqual(self.worker.actions.count("SUCCESS"), 0)
        self.assertEqual(self.worker.actions.count("COMPLETE"), 1)
        records = (self.base / "data/results.jsonl").read_text().splitlines()
        self.assertEqual(len(records), 1)
        self.act("variant")
        self.assertEqual(self.model.target["menu"], "latte")
        self.assertEqual(self.model.session.help_count, 0)

    def test_free_order_allows_other_choices(self):
        self.act("start", "free")
        self.act("service", "매장에서 먹기")
        self.act("next")
        self.act("menu", "vanilla")
        self.act("next")
        self.act("default")
        self.act("next")
        self.act("complete")
        self.assertEqual(self.model.session.screen, "complete")

    def test_help_repeat_back_and_invalid_requests(self):
        self.act("start", "practice")
        self.act("hint")
        self.act("repeat")
        self.assertEqual(self.model.session.help_count, 1)
        self.act("help")
        self.assertEqual(self.model.session.support_level, 3)
        self.act("back")
        self.assertEqual(self.model.session.help_count, 2)
        for payload in ([], {}, {"requestId": "bad", "revision": -1},
                        {"requestId": "x", "revision": self.model.revision, "action": "exec"}):
            with self.assertRaises(ValueError):
                self.model.apply(payload)

    def test_wrong_screen_rejects_choice(self):
        with self.assertRaises(ValueError):
            self.act("menu", "latte")
        self.assertEqual(self.model.session.order, {})

    def test_warning_and_mock_test_are_visible(self):
        self.worker.events.put(("warning", "소리 재생 실패"))
        data = self.act("sound_test")
        self.assertIn("모의 모드", data["message"])
        self.assertEqual(data["robot"]["warnings"], ["소리 재생 실패"])


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.server = LocalKioskServer(FakeWorker())
        self.server.start()
        self.base = "http://" + self.server.host

    def tearDown(self):
        self.server.close()

    def request(self, path, payload=None, authorized=True, **headers):
        if authorized:
            headers["X-Kiosk-Token"] = self.server.token
        body = json.dumps(payload).encode() if payload is not None else None
        return urlopen(Request(self.base + path, data=body, headers=headers), timeout=3)

    def test_token_static_files_and_traversal(self):
        with self.assertRaises(HTTPError) as error:
            self.request("/api/state", authorized=False)
        self.assertEqual(error.exception.code, 403)
        with self.request("/api/state") as response:
            self.assertEqual(json.load(response)["screen"], "start")
        with self.request("/assets/americano.jpg") as response:
            self.assertEqual(response.headers["Content-Type"], "image/jpeg")
        with self.assertRaises(HTTPError) as error:
            self.request("/%2e%2e/core.py")
        self.assertEqual(error.exception.code, 404)

    def test_cross_origin_and_unknown_actions_are_rejected(self):
        payload = {"requestId": "x", "revision": 0, "action": "exec", "value": ""}
        with self.assertRaises(HTTPError) as error:
            self.request("/api/event", payload, Origin="https://example.com")
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            self.request("/api/event", payload)
        self.assertEqual(error.exception.code, 400)
