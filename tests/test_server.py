import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from xiangqi_duel.models import ModelRegistry
from xiangqi_duel.server import create_server


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.registry = ModelRegistry(os.path.join(cls.tmp.name, "models.json"))
        cls.server = create_server(
            "127.0.0.1",
            0,
            registry=cls.registry,
            games_dir=os.path.join(cls.tmp.name, "games"),
        )
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def base(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def call(self, path, method="GET", body=None, timeout=20):
        data = None
        headers = {"Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
        request = urllib.request.Request(self.base(path), data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}")

    def test_01_health_and_page(self):
        status, data = self.call("/api/health")
        self.assertEqual(status, 200)
        with urllib.request.urlopen(self.base("/"), timeout=10) as response:
            page = response.read().decode()
        self.assertIn("象棋对弈", page)
        self.assertIn("model-list", page)

    def test_02_models_crud(self):
        status, data = self.call("/api/models")
        self.assertEqual(status, 200)
        self.assertEqual(data["models"], [])
        self.assertTrue(data["providers"])

        status, data = self.call(
            "/api/models",
            "POST",
            {"provider": "engine", "model": "alpha-beta", "label": "离线引擎"},
        )
        self.assertEqual(status, 200)
        model_id = data["model"]["id"]
        self.assertNotIn("api_key", data["model"])

        status, data = self.call("/api/models")
        self.assertEqual(len(data["models"]), 1)
        self.assertEqual(data["models"][0]["label"], "离线引擎")

        status, data = self.call("/api/models/" + model_id, "DELETE")
        self.assertEqual(status, 200)
        status, data = self.call("/api/models")
        self.assertEqual(data["models"], [])

    def test_03_engine_match_and_events(self):
        status, data = self.call(
            "/api/new",
            "POST",
            {
                "red": {"kind": "engine", "depth": 1},
                "black": {"kind": "engine", "depth": 1},
                "max_plies": 20,
            },
        )
        self.assertEqual(status, 200)
        match_id = data["match_id"]

        with urllib.request.urlopen(self.base("/api/events"), timeout=20) as stream:
            line = stream.readline().decode()
            self.assertIn("data:", line)

        deadline = time.time() + 40
        snapshot = None
        while time.time() < deadline:
            status, data = self.call("/api/state")
            snapshot = data["snapshot"]
            if snapshot and snapshot["status"] == "finished":
                break
            time.sleep(0.2)
        self.assertEqual(snapshot["match_id"], match_id)
        self.assertGreaterEqual(len(snapshot["moves"]), 2)
        self.assertTrue(snapshot["trace"])
        self.assertFalse(snapshot["trace_hidden"])

        status, data = self.call("/api/stop", "POST", {})
        self.assertEqual(status, 200)

    def test_04_human_mode(self):
        status, data = self.call(
            "/api/new",
            "POST",
            {
                "red": {"kind": "human"},
                "black": {"kind": "engine", "depth": 1},
                "human_side": "red",
                "max_plies": 30,
            },
        )
        self.assertEqual(status, 200)
        snapshot = data["snapshot"]
        self.assertEqual(snapshot["mode"], "human")
        self.assertEqual(snapshot["trace"], [])
        self.assertTrue(snapshot["trace_hidden"])
        self.assertIn("red_horse_1", snapshot["legal"])

        status, data = self.call("/api/move", "POST", {"piece_id": "red_horse_1", "to": "c2"})
        self.assertEqual(status, 200)

        deadline = time.time() + 20
        while time.time() < deadline:
            status, data = self.call("/api/state")
            snapshot = data["snapshot"]
            if snapshot and len(snapshot["moves"]) >= 2:
                break
            time.sleep(0.1)
        self.assertGreaterEqual(len(snapshot["moves"]), 2)
        self.assertEqual(snapshot["moves"][0]["notation"], "马八进七")

        status, data = self.call("/api/say", "POST", {"text": "请多指教"})
        self.assertEqual(status, 200)
        status, data = self.call("/api/state")
        self.assertTrue(any(m["text"] == "请多指教" for m in data["snapshot"]["chat"]))

        status, data = self.call("/api/move", "POST", {"piece_id": "red_horse_1", "to": "e2"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

        status, data = self.call("/api/stop", "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(data["ok"], True)

    def test_05_bad_match_request(self):
        status, data = self.call(
            "/api/new",
            "POST",
            {"red": {"kind": "model", "model_id": "missing"}, "black": {"kind": "engine"}},
        )
        self.assertEqual(status, 400)
        self.assertIn("模型库", data["error"])


class ResignTest(unittest.TestCase):
    def test_human_can_resign(self):
        import json as _json
        import threading as _threading
        import time as _time
        import urllib.request as _urllib
        from xiangqi_duel.models import ModelRegistry as _Registry
        from xiangqi_duel.server import create_server as _create

        with tempfile.TemporaryDirectory() as tmp:
            registry = _Registry(os.path.join(tmp, "models.json"))
            server = _create("127.0.0.1", 0, registry=registry, games_dir=os.path.join(tmp, "games"))
            port = server.server_address[1]
            thread = _threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = "http://127.0.0.1:%d" % port

            def call(path, method="GET", body=None):
                data = None
                headers = {"Content-Type": "application/json"}
                if body is not None:
                    data = _json.dumps(body).encode()
                request = _urllib.Request(base + path, data=data, headers=headers, method=method)
                try:
                    with _urllib.urlopen(request, timeout=15) as response:
                        return response.status, _json.loads(response.read().decode())
                except _urllib.error.HTTPError as exc:
                    return exc.code, _json.loads(exc.read().decode() or "{}")

            try:
                status, data = call("/api/new", "POST", {
                    "red": {"kind": "human"},
                    "black": {"kind": "engine", "depth": 1},
                    "human_side": "red",
                    "max_plies": 20,
                })
                self.assertEqual(status, 200)
                status, data = call("/api/resign", "POST", {"side": "red"})
                self.assertEqual(status, 200)
                self.assertTrue(data["ok"])
                deadline = _time.time() + 10
                snapshot = None
                while _time.time() < deadline:
                    status, data = call("/api/state")
                    snapshot = data["snapshot"]
                    if snapshot and snapshot["status"] == "finished":
                        break
                    _time.sleep(0.1)
                self.assertEqual(snapshot["status"], "finished")
                self.assertEqual(snapshot["result"]["winner"], "black")
                self.assertIn("认输", snapshot["result"]["reason"])
            finally:
                server.shutdown()
                server.server_close()


class AuthTest(unittest.TestCase):
    def test_basic_auth(self):
        import base64
        import json as _json
        import threading as _threading
        import urllib.error as _errors
        import urllib.request as _urllib
        from xiangqi_duel.models import ModelRegistry as _Registry
        from xiangqi_duel.server import create_server as _create

        with tempfile.TemporaryDirectory() as tmp:
            registry = _Registry(os.path.join(tmp, "models.json"))
            server = _create(
                "127.0.0.1", 0, registry=registry, games_dir=os.path.join(tmp, "games"),
                password="s3cret",
            )
            port = server.server_address[1]
            thread = _threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = "http://127.0.0.1:%d" % port

            def get(path, token=None):
                request = _urllib.Request(base + path)
                if token:
                    request.add_header("Authorization", "Basic " + base64.b64encode(b"duel:" + token.encode()).decode())
                try:
                    with _urllib.urlopen(request, timeout=10) as response:
                        return response.status, response.read()
                except _errors.HTTPError as exc:
                    return exc.code, exc.read()

            try:
                status, _ = get("/api/models")
                self.assertEqual(status, 401)
                status, body = get("/api/models", "s3cret")
                self.assertEqual(status, 200)
                self.assertIn(b"models", body)
                status, _ = get("/api/health")
                self.assertEqual(status, 200)
            finally:
                server.shutdown()
                server.server_close()
