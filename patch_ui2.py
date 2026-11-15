path = "xiangqi_duel/tools.py"
src = open(path, encoding="utf-8").read()
src = src.replace('"x 是列号 0-8（a=0 ... i=8），y 是行号 0-9"',
                  '"x 是列号 1-9，y 是行号 1-10"', 1)
src = src.replace('"description": "最小列号 0-8，默认 0"', '"description": "最小列号 1-9，默认 1"', 1)
src = src.replace('"description": "最大列号 0-8，默认 8"', '"description": "最大列号 1-9，默认 9"', 1)
src = src.replace('"description": "最小行号 0-9，默认 0"', '"description": "最小行号 1-10，默认 1"', 1)
src = src.replace('"description": "最大行号 0-9，默认 9"', '"description": "最大行号 1-10，默认 10"', 1)
src = src.replace('"description": "格子名，例如 h2"', '"description": "格子，例如 8-2（列 1-9，行 1-10）"', 1)
open(path, "w", encoding="utf-8").write(src)
print("tool descriptions")

path = "xiangqi_duel/web/index.html"
src = open(path, encoding="utf-8").read()
src = src.replace("hint.textContent = '你的留言会在 AI 下一回合被读到；它可以用 send_message 回复你。';",
                  "hint.textContent = '';", 1)
src = src.replace("if (!html) { html = '<p class="empty">还没有人说话。AI 可以用 send_message 留言。</p>'; }",
                  "if (!html) { html = ''; }", 1)
open(path, "w", encoding="utf-8").write(src)
print("chat hints removed")

path = "README.md"
src = open(path, encoding="utf-8").read()
src = src.replace('"to": "c2"', '"to": "3-3"', 1)
src = src.replace('{"x_min": 0, "x_max": 4, "y_min": 0, "y_max": 4}', '{"x_min": 1, "x_max": 5, "y_min": 1, "y_max": 5}', 1)
src = src.replace('{"square": "h2"}', '{"square": "8-2"}', 1)
open(path, "w", encoding="utf-8").write(src)
print("readme examples")
