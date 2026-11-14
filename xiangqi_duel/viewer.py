"""生成可离线打开的对局回放页面（单个 HTML 文件）。"""
from __future__ import annotations

import html
import json

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#17130f; --panel:#231c15; --line:#3a2f24; --text:#f2e8da; --muted:#a89883; --accent:#d9a441; }
  * { box-sizing: border-box; }
  body { margin:0; background:radial-gradient(1000px 600px at 20% -10%, #2c241b, #17130f 60%); color:var(--text);
         font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",system-ui,sans-serif; min-height:100vh; }
  header { padding:20px 26px 6px; display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  h1 { margin:0; font-size:19px; }
  .sub { color:var(--muted); font-size:13px; }
  main { display:grid; grid-template-columns:minmax(300px,600px) minmax(280px,380px); gap:26px; justify-content:center; padding:10px 26px 40px; }
  .board { position:relative; width:min(70vh,100%); aspect-ratio:8/9; background:linear-gradient(150deg,#f0d6a4,#e9c98f 55%,#dcb87a);
           border-radius:16px; box-shadow:0 18px 44px rgba(0,0,0,.45); }
  .grid { position:absolute; inset:6.5%; }
  svg { position:absolute; inset:0; width:100%; height:100%; }
  svg line { stroke:#8a6435; stroke-width:1.2; vector-effect:non-scaling-stroke; }
  svg line.edge { stroke-width:2.4; }
  svg text { fill:rgba(120,84,40,.85); font-size:.42px; font-weight:700; text-anchor:middle; }
  .pieces,.markers { position:absolute; inset:0; }
  .piece { position:absolute; width:11.4%; aspect-ratio:1; transform:translate(-50%,-50%); border-radius:50%;
           display:grid; place-items:center; font-family:"Kaiti SC","STKaiti","KaiTi",serif; font-weight:800;
           font-size:var(--glyph,22px); transition:left .18s ease, top .18s ease; }
  .piece.red { background:radial-gradient(circle at 32% 28%, #fff7ea, #f0d6ae 70%); color:#b3261e; border:2px solid #b3261e; }
  .piece.black { background:radial-gradient(circle at 32% 28%, #f4f4f4, #d9d9d9 70%); color:#1d1d1f; border:2px solid #1d1d1f; }
  .lastmove { position:absolute; width:12.6%; aspect-ratio:1; transform:translate(-50%,-50%); border:2px dashed rgba(160,96,20,.75); border-radius:8px; }
  .panel { background:linear-gradient(180deg,var(--panel),#1d1813); border:1px solid var(--line); border-radius:18px; padding:16px;
           display:flex; flex-direction:column; gap:12px; }
  .players { display:flex; gap:8px; flex-wrap:wrap; font-size:13px; color:var(--muted); }
  .players b { color:var(--text); font-weight:600; }
  .result { padding:10px 12px; border-radius:10px; background:rgba(217,164,65,.12); border:1px solid rgba(217,164,65,.4); font-weight:700; }
  .controls { display:flex; gap:6px; flex-wrap:wrap; }
  button { background:#2b241c; color:var(--text); border:1px solid var(--line); border-radius:9px; padding:7px 12px; cursor:pointer; }
  button:hover { border-color:var(--accent); }
  .moves { list-style:none; margin:0; padding:0; overflow-y:auto; max-height:40vh; font-size:14px; }
  .moves li { padding:5px 8px; border-radius:7px; display:flex; gap:8px; cursor:pointer; }
  .moves li:nth-child(odd) { background:rgba(255,255,255,.025); }
  .moves li.active { background:rgba(217,164,65,.18); }
  .moves .ply { color:var(--muted); width:28px; text-align:right; font-size:12px; }
  .moves .notation { font-family:"Kaiti SC","STKaiti","KaiTi",serif; font-size:16px; }
  .moves .side { color:var(--muted); font-size:12px; }
  .comment { color:var(--muted); font-size:12px; padding:2px 10px 6px 44px; }
  .chat { border-top:1px solid var(--line); padding-top:10px; display:flex; flex-direction:column; gap:6px; max-height:22vh; overflow-y:auto; font-size:13px; }
  .chat div { padding:6px 9px; border-radius:8px; background:#2b241c; white-space:pre-wrap; }
  .chat .red { border-left:3px solid #e0533f; }
  .chat .black { border-left:3px solid #9fb4c9; }
  .hint { color:var(--muted); font-size:12px; }
  @media (max-width:940px){ main { grid-template-columns:1fr; } .board { width:min(88vw,520px); } }
</style>
</head>
<body>
<header>
  <h1>象棋对弈 · 回放</h1>
  <span class="sub" id="subtitle"></span>
</header>
<main>
  <section>
    <div class="board"><div class="grid" id="grid">
      <svg id="svg" viewBox="0 0 8 9" preserveAspectRatio="none"></svg>
      <div class="markers" id="markers"></div>
      <div class="pieces" id="pieces"></div>
    </div></div>
    <p class="hint">← → 切换手数，空格播放/暂停</p>
  </section>
  <aside class="panel">
    <div class="players" id="players"></div>
    <div class="result" id="result">对局进行中</div>
    <div class="controls">
      <button id="first">开局</button>
      <button id="prev">上一步</button>
      <button id="play">▶ 播放</button>
      <button id="next">下一步</button>
      <button id="last">终局</button>
    </div>
    <ol class="moves" id="moves"></ol>
    <div class="chat" id="chat"></div>
  </aside>
</main>
<script type="application/json" id="log">__DATA__</script>
<script>
(function () {
  'use strict';
  var log = JSON.parse(document.getElementById('log').textContent);
  var moves = log.moves || [];
  var frames = [{ fen: log.start_fen, last: null, move: null }];
  moves.forEach(function (move) {
    frames.push({ fen: move.fen, last: move, move: move });
  });
  var index = 0;
  var timer = null;
  var GLYPH = { red: {}, black: {} };
  var LETTERS = { r: 'chariot', n: 'horse', b: 'elephant', a: 'advisor', k: 'general', c: 'cannon', p: 'soldier' };
  var NAMES = {
    red: { general: '帥', advisor: '仕', elephant: '相', horse: '馬', chariot: '車', cannon: '炮', soldier: '兵' },
    black: { general: '將', advisor: '士', elephant: '象', horse: '馬', chariot: '車', cannon: '砲', soldier: '卒' }
  };
  var FILES = 'abcdefghi';

  function fenToPieces(fen) {
    var board = fen.split(' ')[0].split('/');
    var pieces = [];
    for (var row = 0; row < 10; row += 1) {
      var y = 9 - row;
      var x = 0;
      var line = board[row] || '9';
      for (var i = 0; i < line.length; i += 1) {
        var ch = line.charAt(i);
        if (ch >= '0' && ch <= '9') { x += parseInt(ch, 10); continue; }
        var color = ch === ch.toUpperCase() ? 'red' : 'black';
        var type = LETTERS[ch.toLowerCase()];
        pieces.push({ color: color, type: type, x: x, y: y, glyph: NAMES[color][type],
                      square: FILES.charAt(x) + y });
        x += 1;
      }
    }
    return pieces;
  }

  function leftFor(x) { return x / 8 * 100; }
  function topFor(y) { return (9 - y) / 9 * 100; }

  function drawGrid() {
    var svg = document.getElementById('svg');
    var NS = 'http://www.w3.org/2000/svg';
    function line(x1, y1, x2, y2, cls) {
      var el = document.createElementNS(NS, 'line');
      el.setAttribute('x1', x1); el.setAttribute('y1', y1);
      el.setAttribute('x2', x2); el.setAttribute('y2', y2);
      if (cls) { el.setAttribute('class', cls); }
      svg.appendChild(el);
    }
    for (var x = 0; x <= 8; x += 1) {
      if (x === 0 || x === 8) { line(x, 0, x, 9, 'edge'); }
      else { line(x, 0, x, 4, ''); line(x, 5, x, 9, ''); }
    }
    for (var y = 0; y <= 9; y += 1) { line(0, y, 8, y, y === 0 || y === 9 ? 'edge' : ''); }
    line(3, 0, 5, 2, ''); line(5, 0, 3, 2, '');
    line(3, 7, 5, 9, ''); line(5, 7, 3, 9, '');
    var t = document.createElementNS(NS, 'text');
    t.setAttribute('x', 2); t.setAttribute('y', 4.63); t.textContent = '楚 河';
    svg.appendChild(t);
    var t2 = document.createElementNS(NS, 'text');
    t2.setAttribute('x', 6); t2.setAttribute('y', 4.63); t2.textContent = '汉 界';
    svg.appendChild(t2);
  }

  function render() {
    var frame = frames[index];
    var pieces = fenToPieces(frame.fen);
    var layer = document.getElementById('pieces');
    layer.innerHTML = '';
    pieces.forEach(function (piece) {
      var el = document.createElement('div');
      el.className = 'piece ' + piece.color;
      el.textContent = piece.glyph;
      el.style.left = leftFor(piece.x) + '%';
      el.style.top = topFor(piece.y) + '%';
      layer.appendChild(el);
    });
    document.getElementById('markers').innerHTML = '';
    if (frame.last) {
      ['from', 'to'].forEach(function (key) {
        var name = frame.move[key];
        if (!name) { return; }
        var x = FILES.indexOf(name.charAt(0));
        var y = parseInt(name.slice(1), 10);
        var box = document.createElement('div');
        box.className = 'lastmove';
        box.style.left = leftFor(x) + '%';
        box.style.top = topFor(y) + '%';
        document.getElementById('markers').appendChild(box);
      });
    }
    fit();
    var items = document.querySelectorAll('#moves li');
    for (var i = 0; i < items.length; i += 1) {
      items[i].classList.toggle('active', i === index - 1);
    }
    if (index > 0) {
      var active = document.querySelector('#moves li.active');
      if (active) { active.scrollIntoView({ block: 'nearest' }); }
    }
    var subtitle = document.getElementById('subtitle');
    var current = index === 0 ? '开局' : ('第 ' + index + ' 手');
    subtitle.textContent = current + ' · 共 ' + moves.length + ' 手';
  }

  function fit() {
    var g = document.getElementById('grid');
    var cell = g.clientWidth / 8;
    document.documentElement.style.setProperty('--glyph', Math.max(12, Math.round(cell * 0.56)) + 'px');
  }

  function build() {
    drawGrid();
    document.getElementById('players').innerHTML = (function () {
      var red = log.players && log.players.red ? log.players.red.label || log.players.red.model : '红方';
      var black = log.players && log.players.black ? log.players.black.label || log.players.black.model : '黑方';
      return '<span>红方 <b>' + red + '</b></span><span>黑方 <b>' + black + '</b></span>';
    })();
    var result = log.result || {};
    var box = document.getElementById('result');
    var REASONS = {
      'checkmate': '将死',
      'stalemate': '困毙',
      'perpetual check': '长将判负',
      'threefold repetition': '三次重复局面判和',
      'sixty-move rule': '60 回合无吃子判和',
      'insufficient material': '子力不足判和',
      'move limit': '达到最大手数'
    };
    var reason = REASONS[result.reason] || result.reason || '';
    if (result.winner) {
      box.textContent = (result.winner === 'red' ? '红方' : '黑方') + '胜 · ' + reason;
    } else if (result.reason) {
      box.textContent = '和棋 · ' + reason;
    } else {
      box.textContent = '对局未结束';
    }
    var list = document.getElementById('moves');
    var html = '';
    moves.forEach(function (move, i) {
      html += '<li data-index="' + i + '"><span class="ply">' + move.ply + '</span>' +
        '<span class="side">' + (move.side === 'red' ? '红' : '黑') + '</span>' +
        '<span class="notation">' + move.notation + '</span></li>';
      if (move.comment) {
        html += '<div class="comment">' + move.comment.replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }) + '</div>';
      }
    });
    list.innerHTML = html;
    list.addEventListener('click', function (event) {
      var li = event.target.closest('li');
      if (!li) { return; }
      index = parseInt(li.getAttribute('data-index'), 10) + 1;
      stop();
      render();
    });
    var chatBox = document.getElementById('chat');
    chatBox.innerHTML = (log.chat || []).map(function (message) {
      var side = message.side === 'user' ? '观众' : (message.side === 'red' ? '红方' : '黑方');
      var cls = message.side === 'user' ? '' : message.side;
      return '<div class="' + cls + '"><b>' + side + '</b>：' + message.text + '</div>';
    }).join('');
    if (!chatBox.innerHTML) { chatBox.innerHTML = '<div class="hint">本局没有留言</div>'; }
    document.getElementById('first').onclick = function () { stop(); index = 0; render(); };
    document.getElementById('prev').onclick = function () { stop(); index = Math.max(0, index - 1); render(); };
    document.getElementById('next').onclick = function () { stop(); index = Math.min(frames.length - 1, index + 1); render(); };
    document.getElementById('last').onclick = function () { stop(); index = frames.length - 1; render(); };
    document.getElementById('play').onclick = function () { timer ? stop() : play(); };
    document.addEventListener('keydown', function (event) {
      if (event.key === 'ArrowLeft') { stop(); index = Math.max(0, index - 1); render(); }
      else if (event.key === 'ArrowRight') { stop(); index = Math.min(frames.length - 1, index + 1); render(); }
      else if (event.key === ' ') { event.preventDefault(); timer ? stop() : play(); }
    });
    window.addEventListener('resize', fit);
    render();
  }

  function play() {
    if (timer) { return; }
    timer = setInterval(function () {
      if (index >= frames.length - 1) { stop(); return; }
      index += 1;
      render();
    }, 900);
    document.getElementById('play').textContent = '⏸ 暂停';
  }

  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
    document.getElementById('play').textContent = '▶ 播放';
  }

  build();
})();
</script>
</body>
</html>
"""


def _escape_json(text):
    return text.replace("</", "<\\/")


def replay_html(log, title="象棋对弈 · 回放"):
    data = _escape_json(json.dumps(log, ensure_ascii=False))
    return (
        TEMPLATE.replace("__TITLE__", html.escape(title))
        .replace("__DATA__", data)
    )


def write_replay(log, path, title=None):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(replay_html(log, title or "象棋对弈 · 回放"))
    return path
