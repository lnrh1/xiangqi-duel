# ------------------------------------------------------------------ agent.py
path = "xiangqi_duel/agent.py"
src = open(path, encoding="utf-8").read()
if "import threading" not in src:
    src = src.replace("import queue\nimport random", "import queue\nimport random\nimport threading", 1)

src = src.replace('''        self._delta_parts = []
        self._delta_last = 0.0''', '''        self._delta_parts = []
        self._delta_last = 0.0
        self._cancelled = False''', 1)

# chat via cancellable worker thread
src = src.replace('''            chat_kwargs = {"tools": tool_specs(self.enabled_tools)}
            if getattr(self.client, "supports_streaming", False):
                chat_kwargs["on_delta"] = self._on_delta
            try:
                result = self.client.chat(system, messages, **chat_kwargs)
            except LLMError as exc:''', '''            try:
                result = self._chat(system, messages, tool_specs(self.enabled_tools))
            except LLMError as exc:''', 1)
src = src.replace('''            self._flush_delta()
            self._merge_usage(result.usage)''', '''            if result is None:
                return self._abort(last_text, error="cancelled")
            self._flush_delta()
            self._merge_usage(result.usage)''', 1)

# cancellation checks
src = src.replace('''        step = 0
        while True:
            step += 1''', '''        step = 0
        while True:
            if self._cancelled:
                return self._abort(last_text, error="cancelled")
            step += 1''', 1)
src = src.replace("steps=step + 1", "steps=step")
src = src.replace("steps=step + 1", "steps=step")

# helper methods
anchor = "    def _messages(self):"
helper = '''    def cancel(self):
        self._cancelled = True
        cancel = getattr(self.client, "cancel", None)
        if cancel is not None:
            try:
                cancel()
            except Exception:  # noqa: BLE001
                pass

    def _chat(self, system, messages, tools):
        box = {}
        kwargs = {"tools": tools}
        if getattr(self.client, "supports_streaming", False):
            kwargs["on_delta"] = self._on_delta

        def run():
            try:
                box["result"] = self.client.chat(system, messages, **kwargs)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        while worker.is_alive():
            if self._cancelled:
                self.cancel()
                return None
            worker.join(0.1)
        if "error" in box:
            raise box["error"]
        return box.get("result")

'''
if "def _chat(self, system, messages, tools)" not in src:
    if anchor not in src:
        raise SystemExit("messages anchor missing")
    src = src.replace(anchor, helper + anchor, 1)

# engine cancel stub
src = src.replace('''    def reset_for_new_game(self, side=None):
        while True:
            try:
                self.inbox.get_nowait()
            except queue.Empty:
                break

    def farewell(self, game):
        return ""''', '''    def reset_for_new_game(self, side=None):
        while True:
            try:
                self.inbox.get_nowait()
            except queue.Empty:
                break

    def cancel(self):
        self._cancelled = True

    def farewell(self, game):
        return ""''', 1)
open(path, "w", encoding="utf-8").write(src)
print("agent cancellation wired")

# ------------------------------------------------------------------ arena.py
path = "xiangqi_duel/arena.py"
src = open(path, encoding="utf-8").read()
old = '''    def stop(self, reason="对局被终止"):
        self.stop_event.set()
        self.human_queue.put(None)
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=10)
        with self.lock:
            if self.game.status == "playing":
                self.game.abort(reason)
        self._broadcast({"type": "state", "snapshot": self.snapshot()})'''
new = '''    def stop(self, reason="对局被终止"):
        self.stop_event.set()
        self.human_queue.put(None)
        for player in list(self.players.values()):
            cancel = getattr(player, "cancel", None)
            if cancel is not None:
                try:
                    cancel()
                except Exception:  # noqa: BLE001
                    pass
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2)
        with self.lock:
            if self.game.status == "playing":
                self.game.abort(reason)
        self._broadcast({"type": "state", "snapshot": self.snapshot()})'''
if old not in src:
    raise SystemExit("match stop anchor missing")
src = src.replace(old, new, 1)

old = '''                    with self.lock:
                        if self.game.status != "playing":
                            break
                    if decision.resign:'''
new = '''                    if self.stop_event.is_set():
                        break
                    with self.lock:
                        if self.game.status != "playing":
                            break
                    if decision.resign:'''
if old not in src:
    raise SystemExit("loop stop anchor missing")
src = src.replace(old, new, 1)
open(path, "w", encoding="utf-8").write(src)
print("match stop cancels requests")
