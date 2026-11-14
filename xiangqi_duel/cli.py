"""命令行入口：serve / play / models / replay / start / selftest。"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys

from . import __version__
from .arena import Match, PlayerSpec
from .board import Board
from .coords import FILES, parse_square
from .game import Game, IllegalMove
from .llm import PRESETS
from .models import ModelRegistry, RegistryError
from .server import serve as serve_http
from .viewer import write_replay


# --------------------------------------------------------------------- helpers
def model_spec(entry):
    return PlayerSpec(
        kind="llm",
        provider=entry.get("provider", ""),
        model=entry.get("model", ""),
        api_key=entry.get("api_key", ""),
        base_url=entry.get("base_url", ""),
        temperature=entry.get("temperature", 0.6),
        label=entry.get("label", ""),
    )


def spec_from_ref(ref, registry, depth=3):
    ref = str(ref or "engine").strip()
    if ref in ("engine", "local", "离线"):
        return PlayerSpec(kind="engine", depth=depth)
    if ref in ("human", "me", "user", "人类"):
        return PlayerSpec(kind="human")
    if ref.startswith("model:"):
        return model_spec(registry.get(ref[len("model:"):]))
    if ":" in ref:
        provider, model = ref.split(":", 1)
        if provider not in PRESETS:
            raise SystemExit(
                "未知提供商 %r；可用：%s" % (provider, "、".join(sorted(PRESETS)))
            )
        return PlayerSpec(kind="llm", provider=provider, model=model)
    try:
        return model_spec(registry.get(ref))
    except RegistryError:
        raise SystemExit(
            "无法识别选手 %r；可用：engine、human、model:<模型库编号>、"
            "provider:model（如 deepseek:deepseek-chat）" % (ref,)
        )


def print_move(record, show_comments=True):
    side = "红" if record["side"] == "red" else "黑"
    text = "第%2d手  %s  %-6s  %s" % (
        record["ply"], side, record["notation"], record["ucci"]
    )
    print(text)
    if show_comments and record.get("comment"):
        print("        AI：%s" % record["comment"])


def print_result(result, snapshot):
    if not result:
        print("对局中止")
        return
    if result.get("winner"):
        winner = "红方" if result["winner"] == "red" else "黑方"
        print("结果：%s胜（%s），共 %d 手" % (winner, result.get("reason"), snapshot["ply"]))
    else:
        print("结果：和棋（%s），共 %d 手" % (result.get("reason"), snapshot["ply"]))


def parse_move_input(text, snapshot):
    parts = text.replace("，", " ").replace(",", " ").split()
    if len(parts) == 2:
        return parts[0], parts[1]
    if len(parts) == 1 and len(parts[0]) == 4:
        frm = parts[0][:2]
        to = parts[0][2:]
        x, y = parse_square(frm)
        piece = None
        for item in snapshot["pieces"]:
            if item["x"] == x and item["y"] == y:
                piece = item
                break
        if piece is None:
            raise ValueError("%s 上没有棋子" % (frm,))
        return piece["id"], to
    raise ValueError("格式应为：red_horse_1 c2 或 b0c2")


# -------------------------------------------------------------------- commands
def cmd_serve(args):
    registry = ModelRegistry(args.models)
    if not registry.entries():
        added = registry.bootstrap_from_env()
        if added:
            print("已从环境变量导入 %d 个模型到模型库。" % len(added))
    serve_http(
        host=args.host,
        port=args.port,
        registry=registry,
        games_dir=args.games_dir,
        password=args.password or os.environ.get("XIANGQI_DUEL_PASSWORD"),
    )


def cmd_play(args):
    registry = ModelRegistry(args.models)
    red = spec_from_ref(args.red, registry, args.depth)
    black = spec_from_ref(args.black, registry, args.depth)
    if red.kind == "human" and black.kind == "human":
        raise SystemExit("不能两边都是人类")
    human = "red" if red.kind == "human" else ("black" if black.kind == "human" else None)
    match = Match(red, black, human_side=human, max_plies=args.max_plies, seed=args.seed)
    channel = match.subscribe()
    match.start()
    snapshot = match.snapshot()
    print("对局开始：红 %s vs 黑 %s" % (snapshot["players"]["red"]["label"], snapshot["players"]["black"]["label"]))
    shown = 0
    shown_chat = 0
    prompted_ply = -1
    try:
        while True:
            event = channel.get()
            if event["type"] == "state":
                snapshot = event["snapshot"]
                for record in snapshot["moves"][shown:]:
                    print_move(record)
                shown = len(snapshot["moves"])
                for message in snapshot["chat"][shown_chat:]:
                    who = "观众" if message["side"] == "user" else ("红方" if message["side"] == "red" else "黑方")
                    print("  %s 留言：%s" % (who, message["text"]))
                shown_chat = len(snapshot["chat"])
                if (
                    human
                    and snapshot["status"] == "playing"
                    and snapshot["turn"] == human
                    and snapshot["ply"] != prompted_ply
                ):
                    prompted_ply = snapshot["ply"]
                    print()
                    print(snapshot["board"])
                    ask_human(match, snapshot, human)
            elif event["type"] == "end":
                snapshot = event.get("snapshot") or match.snapshot()
                print_result(event.get("result"), snapshot)
                break
    except KeyboardInterrupt:
        print("\n已中断。")
        match.stop("用户中断")
    finally:
        if not match.is_running():
            pass
        if args.out:
            path = write_log(match, args.out)
            print("对局日志：%s" % path)


def ask_human(match, snapshot, human):
    while True:
        try:
            line = input("请走棋（red_horse_1 c2 / b0c2；board 看棋盘，resign 认输）：").strip()
        except EOFError:
            match.stop("输入结束")
            return
        if not line:
            continue
        if line in ("board", "b", "棋盘"):
            print(snapshot["board"])
            continue
        if line in ("moves", "m", "棋谱"):
            for record in snapshot["moves"][-10:]:
                print_move(record, show_comments=False)
            continue
        if line in ("resign", "认输", "quit", "exit"):
            match.resign(human, "人类认输")
            return
        try:
            piece_id, to = parse_move_input(line, snapshot)
            match.submit_human_move(piece_id, to)
            return
        except (IllegalMove, ValueError) as exc:
            print("无效着法：%s" % exc)


def write_log(match, path):
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(match.log(), handle, ensure_ascii=False, indent=2)
    return path


def cmd_models(args):
    registry = ModelRegistry(args.models)
    if args.action == "list":
        entries = registry.public()
        if not entries:
            print("模型库为空。用 xiangqi-duel models add 添加，或设置环境变量后 models import-env。")
            return
        for entry in entries:
            print(
                "%-12s %-14s %-28s %s%s"
                % (
                    entry["id"],
                    entry["provider"],
                    entry["model"],
                    entry["label"],
                    "" if entry["has_key"] else "  （缺少 Key）",
                )
            )
    elif args.action == "add":
        try:
            entry = registry.add(
                args.provider, args.model, args.api_key, args.base_url, args.label, args.temperature
            )
        except RegistryError as exc:
            raise SystemExit(str(exc))
        print("已添加模型：%s" % registry.to_public(entry)["label"])
        print("编号：%s" % entry["id"])
    elif args.action == "remove":
        try:
            registry.remove(args.id)
        except RegistryError as exc:
            raise SystemExit(str(exc))
        print("已删除：%s" % args.id)
    elif args.action == "test":
        try:
            result = registry.test(args.id)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit("测试失败：%s" % exc)
        print("可用：%s（%.2fs，回复：%s）" % (args.id, result["seconds"], result["reply"]))
    elif args.action == "import-env":
        added = registry.bootstrap_from_env()
        if not added:
            print("没有发现可导入的环境变量 Key。")
        for entry in added:
            print("已导入：%s（%s）" % (entry["id"], entry["model"]))


def cmd_replay(args):
    try:
        with open(args.path, encoding="utf-8") as handle:
            log = json.load(handle)
    except OSError as exc:
        raise SystemExit("无法读取对局：%s" % exc)
    result = log.get("result") or {}
    players = log.get("players") or {}
    print("红方：%s" % (players.get("red") or {}).get("label", "?"))
    print("黑方：%s" % (players.get("black") or {}).get("label", "?"))
    if args.text:
        for record in log.get("moves") or []:
            print_move(record)
        if result.get("winner"):
            print("结果：%s胜（%s）" % ("红方" if result["winner"] == "red" else "黑方", result.get("reason")))
        else:
            print("结果：和棋（%s）" % result.get("reason"))
    if args.html:
        path = write_replay(log, args.html)
        print("回放页面：%s" % path)
        return
    if not args.text:
        for record in log.get("moves") or []:
            print_move(record, show_comments=False)
        if result.get("winner"):
            print("结果：%s胜（%s）" % ("红方" if result["winner"] == "red" else "黑方", result.get("reason")))
        else:
            print("结果：和棋（%s）" % result.get("reason"))


def cmd_start(args):
    game = Game()
    print(game.ascii(unicode=True))
    print()
    print(game.board.to_fen())
    print("红方 16 子，黑方 16 子，红先。")
    print("合法着法总数：%d" % len(game.legal_moves()))


def cmd_selftest(args):
    game = Game()
    print("初始局面合法着法：%d（标准值 44）" % len(game.legal_moves()))
    match = Match(
        PlayerSpec(kind="engine", depth=args.depth),
        PlayerSpec(kind="engine", depth=args.depth),
        max_plies=args.max_plies,
    )
    match.start(block=True)
    print("引擎自测结束：%s，共 %d 手" % (match.game.result, len(match.game.history)))
    for record in match.game.history:
        print_move(record, show_comments=False)
    print("OK")


# ----------------------------------------------------------------------- main
def build_parser():
    parser = argparse.ArgumentParser(
        prog="xiangqi-duel",
        description="中国象棋 AI 对弈：双 AI 观战 / 人机对弈 / 模型库管理。",
    )
    parser.add_argument("--version", action="version", version="xiangqi-duel " + __version__)
    parser.add_argument("--models", default=None, help="模型库文件路径（默认 ~/.xiangqi-duel/models.json）")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="启动本地 Web 界面")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--games-dir", default=None)
    serve.add_argument("--password", default="", help="HTTP Basic 认证密码（也可用 XIANGQI_DUEL_PASSWORD）")
    serve.set_defaults(func=cmd_serve)

    play = sub.add_parser("play", help="在终端运行一局")
    play.add_argument("--red", default="engine", help="红方：engine / human / model:<id> / provider:model")
    play.add_argument("--black", default="engine", help="黑方：同上")
    play.add_argument("--max-plies", type=int, default=300)
    play.add_argument("--depth", type=int, default=3, help="本地引擎深度")
    play.add_argument("--seed", type=int, default=1)
    play.add_argument("--out", default="", help="对局 JSON 输出路径")
    play.set_defaults(func=cmd_play)

    models = sub.add_parser("models", help="管理模型库")
    models.add_argument("action", choices=["list", "add", "remove", "test", "import-env"])
    models.add_argument("id", nargs="?", default="")
    models.add_argument("--provider", default="deepseek")
    models.add_argument("--model", default="")
    models.add_argument("--api-key", default="")
    models.add_argument("--base-url", default="")
    models.add_argument("--label", default="")
    models.add_argument("--temperature", type=float, default=0.6)
    models.set_defaults(func=cmd_models)

    replay = sub.add_parser("replay", help="查看/导出对局回放")
    replay.add_argument("path")
    replay.add_argument("--html", default="", help="导出离线 HTML 回放")
    replay.add_argument("--text", action="store_true")
    replay.set_defaults(func=cmd_replay)

    start = sub.add_parser("start", help="打印初始局面")
    start.set_defaults(func=cmd_start)

    selftest = sub.add_parser("selftest", help="离线自检（规则 + 引擎对局）")
    selftest.add_argument("--depth", type=int, default=2)
    selftest.add_argument("--max-plies", type=int, default=16)
    selftest.set_defaults(func=cmd_selftest)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
