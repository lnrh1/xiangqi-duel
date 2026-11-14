# 架构说明

## 分层

```
┌──────────────┐   工具调用    ┌──────────────┐
│  LLM 棋手     │ ───────────▶ │  ToolBox     │
│ (agent.py)   │ ◀─────────── │ (tools.py)   │
└──────┬───────┘   结果 JSON   └──────┬───────┘
       │ 决策 (piece_id, to)          │ 只校验，不落子
       ▼                              ▼
┌──────────────────────────────────────────────┐
│ Match (arena.py)                              │
│  - 权威棋局 Game (game.py)                     │
│  - 事件广播 / 留言 / 统计                       │
└──────┬────────────────────────────────────────┘
       │ snapshot / SSE
       ▼
┌──────────────┐        ┌──────────────────────┐
│ server.py    │ ─────▶ │ web/index.html        │
│ HTTP + SSE   │        │ 观战 / 人机 / 模型库    │
└──────────────┘        └──────────────────────┘
```

## 线程模型

- 每场对局一个后台线程运行 `Match._run()`，串行推进双方着法。
- UI 线程只做两件事：读 `Match.snapshot()`、把人类着法放进队列。
- 棋手（LLM / 引擎）拿到的是一份 **棋局克隆**（`Game.clone()`），
  它们在克隆盘上搜索和试用着法，不会碰到权威棋盘；由此避免了
  make/unmake 与 UI 快照并发时的数据竞争。
- 权威棋盘的写操作（`game.play`、`game.resign`）和快照生成都在
  同一把可重入锁内完成。

## 工具协议

工具定义是 OpenAI function-calling 的 JSON Schema（中文描述），
`ToolBox.call(name, arguments)` 负责分发、参数校验和错误转文本。

约定：

- `move` 只做合法性校验并返回预览（含落子后的 ASCII 棋盘与 FEN），
  真正落子由 `Match` 执行，便于统一记录历史、留言和用量；
- 所有错误都以 `{"ok": false, "error": "..."}` 返回，代理看得到原因并可重试；
- 棋子编号统一经 `normalize_piece_id` 归一化，兼容中文与各种写法。

## 上下文管理

每个 `LLMPlayer` 用 `blocks` 保存自己的回合块（一个块 = 一个 user 提示 +
若干 assistant/tool 消息）。保留最近 12 个块，超出后整块丢弃，
保证不会把半截 tool 调用留在上下文里。当前局面每次都写进新的回合提示，
所以丢弃旧块不会丢失局面信息。

对局开始时每回合的提示包含：轮次、是否被将军、上一步、最近着法、子力、ASCII 棋盘。
对手和观众的留言以独立的 user 消息插在回合提示前。

## 事件与可见性

`Match._agent_event` 把棋手事件分成两类：

- 可见事件：`thinking`（思路/推理）、`tool_call`、`llm_step`、`error`；
- 控制事件：状态快照。

观战模式（`mode == "aivai"`）把可见事件写入 `trace` 并实时广播；
人机模式只写入日志、不广播，`snapshot()` 里的 `trace` 也返回空数组，
所以前端拿不到 AI 的内部过程。

留言走 `chat` 通道，两种模式都可见，因为那是 AI 主动公开说的话。

## 模型库与密钥

`models.py` 把「棋手」和「模型」解耦：模型条目包含 provider、model、base_url、
api_key、temperature，存在 `~/.xiangqi-duel/models.json`（0600）。
接口只返回 `has_key` 布尔值；对局日志和快照都只带 provider/model/label。

## 规则实现要点

- 走子生成后逐着执行，若己方被将军（含将帅照面）则判为非法；
- `is_attacked` 直接按棋子类型反向扫描，避免为每次将军判断生成全部着法；
- 重复局面按「局面键 + 行棋方」计数，三次重复时检查重复区间内的将军情况：
  一方每一步都在将军 → 长将判负，否则判和；
- perft 与公开标准值一致，用作规则回归测试。

## 扩展点

- **新增提供商**：在 `llm.PRESETS` 里加一项（OpenAI 兼容或 anthropic），
  或直接用自定义 base_url；
- **新增棋手类型**：实现 `choose(game)` 返回 `AgentDecision` 的类，
  在 `PlayerSpec.make_player` 里分支即可；
- **新增工具**：在 `tools.tool_specs` 加 schema，在 `ToolBox` 里加
  `_t_<name>` 方法。
