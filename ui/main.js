// 动画播放器：状态动画按 enter → sustain(循环) → exit 播放；空闲时视线跟随鼠标。
const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;
const W = 192, H = 208, TOP = 32, LEFT = 4;  // 单帧大小；帧画在 (4,32)，上面留给气泡
const cv = document.getElementById('c');
const ctx = cv.getContext('2d', { willReadFrequently: true });
let K = 1;   // 放大倍数；canvas 底层像素 = 窗口物理像素（页面可能被系统 DPI 缩放，CSS 尺寸只管铺满）
let bubble = '';

// CC 状态 → 素材状态 id（素材缺失时退回默认姿态）
const ANIM = { working: 'running', reading: 'review', waiting: 'waiting', done: 'waving', error: 'failed', idle: 'idle' };
const LABEL = { working: '工作中', reading: '查看中', waiting: '等你回复', done: '完成啦', error: '出错了', idle: '' };
// 切进某个状态时先播一遍的小动作
const INTRO = { done: 'jumping', waiting: 'startled-avert' };
// 空闲时偶尔播的小动作；循环类的播 4 秒
const RANDOM = ['prayer-peek', 'sneeze', 'brave-gaze'];
// 空闲（CC 空闲且鼠标没动）多久后坐下、打瞌睡；DESK_PET_DEBUG 时缩短
let SIT_MS = 120e3, SLEEP_MS = 300e3, RANDOM_MS = [20e3, 40e3], DEBUG = false;
const log = m => DEBUG && invoke('log', { msg: `${(performance.now() / 1000).toFixed(1)}s ${m}` });

const clips = {};   // key → { mode, phases: { enter, sustain, exit: [{img, ms}] } }
let neutral;

async function bytes(p) { return new Uint8Array(await invoke('read_asset', { path: p })); }
async function json(p) { return JSON.parse(new TextDecoder().decode(await bytes(p))); }
async function img(p) { return createImageBitmap(new Blob([await bytes(p)], { type: 'image/png' })); }

async function loadClip(key, meta) {
  try {
    const phases = {};
    for (const [name, ph] of Object.entries(meta.phases)) {
      phases[name] = await Promise.all(ph.durations_ms.map(async (ms, i) =>
        ({ img: await img(`${ph.path}/${String(i).padStart(2, '0')}.png`), ms })));
    }
    clips[key] = { mode: meta.mode, phases };
  } catch { /* 这个状态的素材不在，跳过 */ }
}

async function load() {
  neutral = await img('neutral-N.png');
  const st = await json('状态参数.json').catch(() => ({ states: [] }));
  const gz = await json('gaze/gaze.json').catch(() => ({ variants: [] }));
  await Promise.all([
    ...st.states.map(s => loadClip(s.id, s)),
    ...gz.variants.map(v => loadClip('gaze:' + v.angle_degrees, v)),
  ]);
}

// 视线角度 → 可用素材：本身 > 镜像 > 最近的可用角度
function gazeClip(a) {
  const key = x => 'gaze:' + ((x % 360 + 360) % 360);
  if (clips[key(a)]) return { key: key(a), flip: false };
  if (clips[key(360 - a)]) return { key: key(360 - a), flip: true };
  let best = null, bd = 999;
  for (const k of Object.keys(clips)) if (k.startsWith('gaze:')) {
    const d = Math.abs(((+k.slice(5) - a + 540) % 360) - 180);
    if (d < bd) { bd = d; best = k; }
  }
  return best && bd <= 45 ? { key: best, flip: false } : null;
}

// ---- 播放 ----
let ccState = 'idle', gaze = null;          // 目标
let temp = null;                             // 临时动作 { key, until? }：开场小动作、随机小动作
let drag = null, dragUntil = 0;              // 拖动时左右跑
let idleSince = 0, nextRandom = 0;
let cur = null, phase = 'sustain', idx = 0, flip = false, until = 0;
let frame = null;                            // 当前帧，供点穿判断

function targetKey(now) {
  if (drag && now < dragUntil && clips[drag]) return { key: drag };
  if (temp && temp.random && ccState === 'idle' && gaze) temp = null;   // 鼠标一动就不做随机小动作了
  if (temp && !(temp.until < now) && clips[temp.key]) return { key: temp.key };
  temp = null;
  if (ccState === 'idle') {
    if (gaze) return gaze;
    const idleFor = now - Math.max(idleSince, lastMove);
    if (idleFor > SLEEP_MS && clips['sleepy-nod']) return { key: 'sleepy-nod' };
    if (idleFor > SIT_MS && clips['sit-swing']) return { key: 'sit-swing' };
    // 站着发呆时偶尔做个小动作
    if (now > nextRandom) {
      nextRandom = now + RANDOM_MS[0] + Math.random() * (RANDOM_MS[1] - RANDOM_MS[0]);
      const pool = RANDOM.filter(k => clips[k]);
      if (pool.length) {
        const k = pool[Math.floor(Math.random() * pool.length)];
        temp = { key: k, random: true, until: clips[k].mode === 'oneshot' ? undefined : now + 4000 };
        return { key: k };
      }
    }
  }
  const k = ANIM[ccState];
  return clips[k] ? { key: k, flip: false } : (clips.idle ? { key: 'idle', flip: false } : null);
}

function start(t) { cur = t && t.key; flip = !!(t && t.flip); phase = 'enter'; idx = 0; log(`play ${cur}${flip ? ' (镜像)' : ''}`); }

function step(now) {
  const t = targetKey(now);
  let same = t && cur === t.key && flip === !!t.flip;
  if (!cur) { if (t) start(t); }
  else {
    // 视线换方向：直接跳到新方向的保持帧，不回站立；只有开始看和不看了才播 enter / exit
    if (!same && t && cur.startsWith('gaze:') && t.key.startsWith('gaze:')) {
      cur = t.key; flip = !!t.flip; phase = 'sustain'; idx = 0; until = 0; same = true;
    }
    const c = clips[cur], frames = c.phases[phase];
    // 视线保持帧可以马上打断；循环要播完这一圈再退出
    const interrupt = !same && phase === 'sustain' && (c.mode === 'hold' || c.mode === 'parameterized_hold');
    if (interrupt) { phase = 'exit'; idx = 0; }
    else if (now >= until) {
      idx++;
      if (idx >= frames.length) {
        idx = 0;
        if (phase === 'enter') phase = 'sustain';
        else if (phase === 'sustain') {
          if (c.mode === 'oneshot') { phase = 'exit'; if (temp && temp.key === cur) temp = null; }
          else if (!same) phase = 'exit';
          else if (c.mode === 'hold') idx = frames.length - 1;
        } else { cur = null; if (t) start(t); }
      }
    } else return;
  }
  if (!cur) { frame = { img: neutral, ms: 200 }; }
  else {
    const fs = clips[cur].phases[phase];
    frame = fs[Math.min(idx, fs.length - 1)];
  }
  until = now + frame.ms;
  draw();
}

// 气泡画在 canvas 里、固定宽度（WebKitGTK 透明窗口里 DOM 元素缩小偶尔留残边）
function draw() {
  ctx.setTransform(K, 0, 0, K, 0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, 200, 240);
  ctx.save();
  ctx.translate(LEFT, TOP);
  if (flip) { ctx.translate(W, 0); ctx.scale(-1, 1); }
  ctx.drawImage(frame.img, 0, 0);
  ctx.restore();
  if (bubble) {
    ctx.font = '12px sans-serif';
    const w = 184;   // 固定宽度：气泡变窄时不留残边
    ctx.beginPath(); ctx.roundRect(100 - w / 2, 4, w, 22, 11);
    ctx.fillStyle = '#fff'; ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,.2)'; ctx.stroke();
    ctx.fillStyle = '#333'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(bubble, 100, 15.5, 184);
  }
}

// ---- 鼠标：视线 + 点穿 ----
let through = null, lastMove = 0, last = [0, 0];
listen('cursor', ({ payload: [px, py, ax, ay] }) => {
  const x = px / K - LEFT, y = py / K - TOP;
  // 用屏幕绝对坐标判断鼠标动没动（拖动窗口不算）
  if (Math.hypot(ax - last[0], ay - last[1]) > 2) { lastMove = performance.now(); last = [ax, ay]; }
  // 点穿：鼠标下是透明像素（或在窗口外）就让鼠标穿过去
  let hit = false;
  if (x >= 0 && y >= 0 && x < W && y < H) hit = ctx.getImageData(px | 0, py | 0, 1, 1).data[3] > 20;
  if (hit !== !through) { through = !hit; invoke('set_through', { on: through }); }
  // 视线：鼠标最近 3 秒动过、而且不在桌宠身上
  const dx = x - 96, dy = y - 80, far = Math.hypot(dx, dy) > 70;
  if (far && performance.now() - lastMove < 3000) {
    const a = (Math.atan2(dx, -dy) * 180 / Math.PI + 360) % 360;
    gaze = gazeClip(Math.round(a / 22.5) * 22.5 % 360);
  } else gaze = null;
});

// 拖动；窗口在动时按方向播左右跑
document.addEventListener('mousedown', e => {
  if (e.button === 0) window.__TAURI__.window.getCurrentWindow().startDragging();
});
let lastX = null;
listen('moved', ({ payload: [x] }) => {
  if (lastX !== null && Math.abs(x - lastX) > 2) {
    drag = x > lastX ? 'running-right' : 'running-left';
    dragUntil = performance.now() + 400;
  }
  lastX = x;
});

// ---- CC 状态轮询 ----
async function poll() {
  try {
    const r = await invoke('cc_state');
    if (r.state !== ccState) {
      log(`cc ${ccState} -> ${r.state}`);
      if (INTRO[r.state] && clips[INTRO[r.state]]) temp = { key: INTRO[r.state] };
      if (r.state === 'idle') idleSince = performance.now();
    }
    ccState = r.state;
    // 气泡：最要紧的状态（多个就 ×N），其他会话在忙的话补上，例如「等你回复 +2 工作中」
    const n = r.counts[ccState] || 0;
    const others = Object.entries(r.counts).filter(([k, v]) => k !== ccState && k !== 'idle' && v > 0);
    const text = LABEL[ccState] &&
      LABEL[ccState] + (n > 1 ? ` ×${n}` : '') + others.map(([k, v]) => ` +${v} ${LABEL[k]}`).join('');
    if (text !== bubble) { bubble = text; if (frame) draw(); }
  } catch (e) { console.error(e); }
}

invoke('pet_config').then(([k, debug]) => {
  K = k; cv.width = 200 * K; cv.height = 240 * K;
  if (debug) { DEBUG = true; SIT_MS = 8e3; SLEEP_MS = 16e3; RANDOM_MS = [3e3, 4e3]; }
}).then(load).then(() => {
  idleSince = performance.now(); nextRandom = idleSince + RANDOM_MS[0];
  log(`loaded ${Object.keys(clips).filter(k => !k.startsWith('gaze:'))}`);
  frame = { img: neutral, ms: 200 }; draw();
  const loop = now => { step(now); requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
  poll(); setInterval(poll, 1000);
});
