path = "xiangqi_duel/web/index.html"
src = open(path, encoding="utf-8").read()

# css transitions + pop animation
old = '''  .art-stage.flip img { transform: scaleX(-1); }'''
new = '''  .art-stage.flip img { transform: scaleX(-1); }
  .human-stage {
    transition: width .18s ease, height .18s ease, top .18s ease;
  }
  .art-stage.fx img { animation: artPop .34s cubic-bezier(.2, .9, .3, 1); }
  .art-stage.flip.fx img { animation: artPopFlip .34s cubic-bezier(.2, .9, .3, 1); }
  @keyframes artPop {
    0% { transform: scale(1); }
    35% { transform: scale(1.07); }
    100% { transform: scale(1); }
  }
  @keyframes artPopFlip {
    0% { transform: scaleX(-1) scale(1); }
    35% { transform: scaleX(-1) scale(1.07); }
    100% { transform: scaleX(-1) scale(1); }
  }'''
if old not in src:
    raise SystemExit("flip css anchor missing")
src = src.replace(old, new, 1)

# sound
src = src.replace('''      } else if (kind === 'draw') {
        tone(440, 0.3, 'sine', 0.1);
        tone(440, 0.3, 'sine', 0.08, 0.24);
      }''', '''      } else if (kind === 'draw') {
        tone(440, 0.3, 'sine', 0.1);
        tone(440, 0.3, 'sine', 0.08, 0.24);
      } else if (kind === 'art') {
        tone(880, 0.07, 'sine', 0.05);
        tone(1320, 0.11, 'triangle', 0.04, 0.045);
        noise(0.04, 0.025);
      }''', 1)

# click fx
old = '''      stage.addEventListener('click', function () { showArtInfo(key); });'''
new = '''      stage.addEventListener('click', function () {
        showArtInfo(key);
        stage.classList.remove('fx');
        void stage.offsetWidth;
        stage.classList.add('fx');
        setTimeout(function () { stage.classList.remove('fx'); }, 420);
        sound('art');
      });'''
if old not in src:
    raise SystemExit("art click anchor missing")
src = src.replace(old, new, 1)

# layout cache
old = '''  function layoutHumanArt() {
    var stage = $('art-stage-human');
    var info = $('art-info-human');
    var panel = $('side-panel');
    if (!stage || !info || !panel) { return; }
    if (!stage.classList.contains('on')) { return; }
    var rect = panel.getBoundingClientRect();
    var right = Math.max(16, window.innerWidth - rect.right);'''
new = '''  var humanArtBox = '';

  function layoutHumanArt() {
    var stage = $('art-stage-human');
    var info = $('art-info-human');
    var panel = $('side-panel');
    if (!stage || !info || !panel) { return; }
    if (!stage.classList.contains('on')) { return; }
    var rect = panel.getBoundingClientRect();
    var stamp = [Math.round(rect.bottom), Math.round(rect.right), Math.round(rect.width), window.innerHeight].join('|');
    if (stamp === humanArtBox) { return; }
    humanArtBox = stamp;
    var right = Math.max(16, window.innerWidth - rect.right);'''
if old not in src:
    raise SystemExit("layout cache anchor missing")
src = src.replace(old, new, 1)

# observe side panel
src = src.replace("    window.addEventListener('resize', function () { fitBoard(); layoutHumanArt(); });",
'''    window.addEventListener('resize', function () { fitBoard(); layoutHumanArt(); });
    if (window.ResizeObserver) {
      var side = $('side-panel');
      if (side) { new ResizeObserver(function () { layoutHumanArt(); }).observe(side); }
    }''', 1)

open(path, "w", encoding="utf-8").write(src)
print("art fx + layout cache")
