import re

# ------------------------------------------------------------------ tools.py
path = "xiangqi_duel/tools.py"
src = open(path, encoding="utf-8").read()

# filter get_board out of the exposed list
old = "    return [\n        {\n            \"type\": \"function\",\n            \"function\": {\n                \"name\": \"get_board\","
new = "    specs = [\n        {\n            \"type\": \"function\",\n            \"function\": {\n                \"name\": \"get_board\","
if old not in src:
    raise SystemExit("tool_specs head anchor missing")
src = src.replace(old, new, 1)
old = "    ]\n\n\nTOOL_NAMES"
new = "    ]\n    specs = [s for s in specs if s["function"]["name"] != "get_board"]\n    if allowed:\n        specs = [s for s in specs if s["function"]["name"] in allowed]\n    return specs\n\n\nTOOL_NAMES"
if old not in src:
    raise SystemExit("tool_specs tail anchor missing")
src = src.replace(old, new, 1)
src = src.replace("def tool_specs():", "def tool_specs(allowed=None):", 1)

# add offer_draw + note specs before resign spec
anchor = "        {\n            \"type\": \"function\",\n            \"function\": {\n                \"name\": \"resign\","
addition = '''        {
            "type": "function",
            "function": {
                "name": "offer_draw",
                "description": (
                    "向对手提议和棋，note 会显示在对局界面上。如果对手也调用 "
                    "offer_draw，双方同意，立即和棋。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note": {
                            "type": "string",
                            "description": "附言，例如“局面均势，和棋吧”。",
                        }
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "note",
                "description": (
                    "给自己记一条备忘，不发给对手；后续回合会出现在你的提示里。"
                    "适合记录计划、要防守的点或对手的习惯。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "备忘内容，40 字以内。"}
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
            },
        },
'''
if anchor not in src:
    raise SystemExit("resign spec anchor missing")
src = src.replace(anchor, addition + anchor, 1)

# toolbox: allowed / draw_offer / notes
old = """    def __init__(self, game, side):
        self.game = game
        self.side = side
        self.pending = None
        self.outbox = []
        self.messages_sent = 0
        self.resign_reason = """""
new = """    def __init__(self, game, side, allowed=None):
        self.game = game
        self.side = side
        self.pending = None
        self.outbox = []
        self.messages_sent = 0
        self.resign_reason = ""
        self.draw_offer = None
        self.notes = []
        self.allowed = set(allowed) if allowed else None"""
if old not in src:
    raise SystemExit("toolbox init anchor missing")
src = src.replace(old, new, 1)

old = """    def call(self, name, arguments=None):
        if isinstance(arguments, str):"""
new = """    def call(self, name, arguments=None):
        if self.allowed is not None and name not in self.allowed and name != "move":
            return {"ok": False, "error": "工具 %s 已被对局设置禁用" % (name,)}
        if isinstance(arguments, str):"""
if old not in src:
    raise SystemExit("toolbox call anchor missing")
src = src.replace(old, new, 1)

# offer_draw + note handlers before _t_resign
anchor2 = "    def _t_resign(self, reason=""):"
handlers = '''    def _t_offer_draw(self, note=""):
        note = str(note or "").strip()[:80]
        self.draw_offer = note or "和棋"
        return {
            "ok": True,
            "note": note,
            "message": "已向对手提议和棋，等对手回应。",
        }

    def _t_note(self, text=""):
        text = str(text or "").strip()[:120]
        if not text:
            return {"ok": False, "error": "备忘不能为空"}
        self.notes.append(text)
        self.notes = self.notes[-10:]
        return {"ok": True, "notes": list(self.notes)}

'''
if "def _t_offer_draw" not in src:
    if anchor2 not in src:
        raise SystemExit("resign handler anchor missing")
    src = src.replace(anchor2, handlers + anchor2, 1)

# remove get_board handler block
start = src.find("    def _t_get_board(self):")
if start != -1:
    end = src.find("    def _t_list_pieces", start)
    src = src[:start] + src[end:]

open(path, "w", encoding="utf-8").write(src)
print("tools updated")
