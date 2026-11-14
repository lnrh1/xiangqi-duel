# 示例

- `demo-game.json` —— 内置引擎（深度 3）自战 93 手的完整对局日志，三次重复判和
- `demo-replay.html` —— 由上面的日志导出的单文件离线回放

自己导出一份回放：

```bash
xiangqi-duel replay examples/demo-game.json --html my-replay.html
```
- `deepseek-game.json` —— 真实 DeepSeek 自战 24 手（含中文思考与工具调用）
- `deepseek-replay.html` —— 对应的离线回放
