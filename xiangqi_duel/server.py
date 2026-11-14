"""本地 Web 服务：观战、人机对弈与模型库管理。"""
from __future__ import annotations

import base64
import json
import os
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import __version__
from .arena import Match, PlayerSpec
from .game import IllegalMove
from .llm import LLMError, PRESETS, list_models
from .models import DEFAULT_HOME, ModelRegistry, RegistryError

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
MAX_BODY = 256 * 1024


def provider_catalog():
    catalog = []
    for name, preset in PRESETS.items():
        catalog.append(
            {
                "name": name,
                "kind": preset.get("kind"),
                "base_url": preset.get("base_url", ""),
                "model": preset.get("model", ""),
                "env": list(preset.get("env", ())),
            }
        )
    return catalog


class AppState:
    def __init__(self, registry=None, games_dir=None, password=None, username="duel"):
        self.registry = registry or ModelRegistry()
        self.password = password or None
        self.username = username or "duel"
        self.games_dir = games_dir or os.path.join(DEFAULT_HOME, "games")
        self.lock = threading.RLock()
        self.match = None
        self.saved = {}

    # --------------------------------------------------------------- matches
    def current(self):
        with self.lock:
            return self.match

    def set_match(self, match):
        with self.lock:
            self.match = match

    def stop_match(self):
        match = self.current()
        if match is not None:
            match.stop("已开始新对局")
        return match

    def spec_for(self, data):
        data = dict(data or {})
        kind = data.get("kind") or "engine"
        if kind == "human":
            return PlayerSpec(kind="human")
        if kind in ("engine", "local"):
            try:
                depth = int(data.get("depth") or 3)
            except (TypeError, ValueError):
                depth = 3
            return PlayerSpec(kind="engine", depth=max(1, min(depth, 6)))
        model_id = data.get("model_id")
        if not model_id:
            raise ValueError("请先选择一个模型，或选择本地引擎")
        entry = self.registry.get(model_id)
        return PlayerSpec(
            kind="llm",
            provider=entry.get("provider", ""),
            model=entry.get("model", ""),
            api_key=entry.get("api_key", ""),
            base_url=entry.get("base_url", ""),
            temperature=entry.get("temperature", 0.6),
            label=entry.get("label", ""),
        )

    # ------------------------------------------------------------- game files
    def maybe_save(self, match):
        if match is None or match.finished_at is None:
            return
        with self.lock:
            if match.id in self.saved:
                return
            os.makedirs(self.games_dir, exist_ok=True)
            path = os.path.join(self.games_dir, "%s-%s.json" % (time.strftime("%Y%m%d-%H%M%S"), match.id))
            try:
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(match.log(), handle, ensure_ascii=False, indent=2)
                self.saved[match.id] = path
                match.saved_path = path
            except OSError:
                pass


class Handler(BaseHTTPRequestHandler):
    server_version = "XiangqiDuel/" + __version__

    # ------------------------------------------------------------- utilities
    @property
    def state(self):
        return self.server.app

    def _authorized(self):
        password = self.server.app.password
        if not password:
            return True
        header = self.headers.get("Authorization") or ""
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return False
        if ":" not in decoded:
            return False
        user, given = decoded.split(":", 1)
        return (
            secrets.compare_digest(user, self.server.app.username)
            and secrets.compare_digest(given, password)
        )

    def _require_auth(self):
        if self._authorized():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Xiangqi Duel"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def log_message(self, fmt, *args):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise ValueError("body is not valid JSON")

    def _static(self, name):
        path = os.path.join(WEB_DIR, name)
        try:
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        suffix = os.path.splitext(name)[1]
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # -------------------------------------------------------------------- GET
    def do_GET(self):
        path = urlparse(self.path).path
        if path != "/api/health" and not self._require_auth():
            return
        if path in ("/", "/index.html"):
            self._static("index.html")
        elif path == "/favicon.svg":
            self._static("favicon.svg")
        elif path == "/api/health":
            self._json({"ok": True, "version": __version__})
        elif path == "/api/models":
            self._json(
                {
                    "ok": True,
                    "models": self.state.registry.public(),
                    "providers": provider_catalog(),
                    "home": DEFAULT_HOME,
                }
            )
        elif path == "/api/state":
            match = self.state.current()
            if match is not None:
                self.state.maybe_save(match)
            self._json(
                {
                    "ok": True,
                    "snapshot": match.snapshot() if match is not None else None,
                    "version": __version__,
                }
            )
        elif path == "/api/log":
            match = self.state.current()
            self._json(match.log() if match is not None else {"ok": False, "error": "no match"})
        elif path == "/api/events":
            self._events()
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)

    def do_HEAD(self):
        path = urlparse(self.path).path
        if path != "/api/health" and not self._require_auth():
            return
        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as handle:
                    size = len(handle.read())
            except OSError:
                size = 0
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(size))
            self.end_headers()
        else:
            self.send_response(204)
            self.end_headers()

    # ------------------------------------------------------------------- POST
    def do_POST(self):
        path = urlparse(self.path).path
        if not self._require_auth():
            return
        try:
            body = self._read_json()
        except ValueError as exc:
            self._json({"ok": False, "error": str(exc)}, status=400)
            return

        if path == "/api/models":
            try:
                entry = self.state.registry.add(
                    body.get("provider", ""),
                    body.get("model", ""),
                    body.get("api_key", ""),
                    body.get("base_url", ""),
                    body.get("label", ""),
                    body.get("temperature", 0.6),
                )
                self._json({"ok": True, "model": self.state.registry.to_public(entry)})
            except RegistryError as exc:
                self._json({"ok": False, "error": str(exc)}, status=400)
        elif path.startswith("/api/models/") and path.endswith("/test"):
            model_id = path[len("/api/models/"):-len("/test")].strip("/")
            try:
                result = self.state.registry.test(model_id)
                self._json(result)
            except (RegistryError, Exception) as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)}, status=400)
        elif path == "/api/models/discover":
            try:
                models = list_models(
                    body.get("provider", ""),
                    body.get("base_url", ""),
                    body.get("api_key", ""),
                )
                self._json({"ok": True, "models": models})
            except (LLMError, ValueError) as exc:
                self._json({"ok": False, "error": str(exc)}, status=400)
        elif path == "/api/new":
            self._new_match(body)
        elif path == "/api/move":
            match = self.state.current()
            if match is None:
                self._json({"ok": False, "error": "还没有对局"}, status=400)
                return
            try:
                match.submit_human_move(body.get("piece_id", ""), body.get("to", ""))
                self._json({"ok": True})
            except IllegalMove as exc:
                self._json({"ok": False, "error": str(exc)}, status=400)
        elif path == "/api/say":
            match = self.state.current()
            if match is None:
                self._json({"ok": False, "error": "还没有对局"}, status=400)
                return
            try:
                match.say(body.get("text", ""))
                self._json({"ok": True})
            except ValueError as exc:
                self._json({"ok": False, "error": str(exc)}, status=400)
        elif path == "/api/resign":
            match = self.state.current()
            if match is None:
                self._json({"ok": False, "error": "还没有对局"}, status=400)
                return
            side = body.get("side") or match.human_side
            if match.human_side is None or side != match.human_side:
                self._json({"ok": False, "error": "只有人类一方可以认输"}, status=400)
                return
            match.resign(side, "人类认输")
            self._json({"ok": True})
        elif path == "/api/rematch":
            match = self.state.current()
            if match is None:
                self._json({"ok": False, "error": "还没有对局"}, status=400)
                return
            try:
                players = dict(match.players)
                match.stop("开始新一局")
                for side, player in players.items():
                    reset = getattr(player, "reset_for_new_game", None)
                    if reset is not None:
                        reset(side)
                new_match = Match(
                    match.red_spec,
                    match.black_spec,
                    human_side=match.human_side,
                    max_plies=match.max_plies,
                    players=players,
                )
                new_match.start()
                self.state.set_match(new_match)
                self._json(
                    {
                        "ok": True,
                        "match_id": new_match.id,
                        "snapshot": new_match.snapshot(),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": "无法开始新一局：%s" % exc}, status=400)
        elif path == "/api/stop":
            self.state.stop_match()
            self._json({"ok": True})
        else:
            self.send_error(404)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if not self._require_auth():
            return
        if path.startswith("/api/models/"):
            model_id = path[len("/api/models/"):].strip("/")
            try:
                self.state.registry.remove(model_id)
                self._json({"ok": True})
            except RegistryError as exc:
                self._json({"ok": False, "error": str(exc)}, status=400)
        else:
            self.send_error(404)

    # ------------------------------------------------------------- new match
    def _new_match(self, body):
        try:
            red = self.state.spec_for(body.get("red") or {})
            black = self.state.spec_for(body.get("black") or {})
        except (ValueError, RegistryError) as exc:
            self._json({"ok": False, "error": str(exc)}, status=400)
            return
        human_side = body.get("human_side") or None
        if human_side not in (None, "", "red", "black"):
            self._json({"ok": False, "error": "human_side 只能是 red 或 black"}, status=400)
            return
        if human_side:
            spec = red if human_side == "red" else black
            spec.kind = "human"
            spec.provider = "human"
        try:
            max_plies = int(body.get("max_plies") or 300)
        except (TypeError, ValueError):
            max_plies = 300
        try:
            seed = int(body.get("seed") or 1)
        except (TypeError, ValueError):
            seed = 1
        fen = body.get("fen") or None
        self.state.stop_match()
        try:
            match = Match(
                red,
                black,
                human_side=human_side or None,
                max_plies=max(20, min(max_plies, 1000)),
                seed=seed,
                fen=fen,
            )
            match.start()
        except Exception as exc:  # noqa: BLE001
            self._json({"ok": False, "error": "无法开始对局：%s" % exc}, status=400)
            return
        self.state.set_match(match)
        self._json(
            {
                "ok": True,
                "match_id": match.id,
                "snapshot": match.snapshot(),
            }
        )

    # -------------------------------------------------------------------- SSE
    def _events(self):
        match = self.state.current()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        channel = None
        if match is None:
            self._sse_write({"type": "idle", "snapshot": None})
            return
        channel = match.subscribe()
        try:
            self._sse_write({"type": "state", "snapshot": match.snapshot()})
            last_ping = time.time()
            while True:
                try:
                    event = channel.get(timeout=1.0)
                except queue.Empty:
                    event = None
                if event is not None:
                    self._sse_write(event)
                if time.time() - last_ping > 12:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_ping = time.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            if channel is not None:
                match.unsubscribe(channel)

    def _sse_write(self, payload):
        body = ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()


def create_server(host="127.0.0.1", port=8765, registry=None, games_dir=None, password=None, username="duel"):
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.app = AppState(registry=registry, games_dir=games_dir, password=password, username=username)
    return server


def serve(host="127.0.0.1", port=8765, registry=None, games_dir=None, password=None, username="duel"):
    server = create_server(host, port, registry=registry, games_dir=games_dir, password=password, username=username)
    print("象棋对弈 · Xiangqi Duel %s" % __version__)
    print("打开 http://%s:%d" % (host, port))
    if host not in ("127.0.0.1", "localhost"):
        print("注意：正在监听外部地址，请确认只有可信网络可以访问。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        match = server.app.current()
        if match is not None:
            match.stop("服务关闭")
        server.server_close()
