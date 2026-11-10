#!/usr/bin/env python3
"""羊角修女桌宠（PySide6）。

透明无边框置顶窗口；按 Claude Code 的状态播动画（状态由 cc-mod 写到 ~/.cache/desk-pet/sessions）；
点她一下行提裙礼，之后视线跟着鼠标一会儿；双击打开聊天小窗（chat.py）；按住拖动时按方向跑；托盘可退出。
透明处点穿用 setMask：窗口形状 = 当前画面的不透明像素。
"""
import json
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path

# KDE 设了 1.5 倍缩放；向下取整成 1，按物理像素一比一画，像素画不被缩放糊掉（要放大用 DESK_PET_SCALE）
os.environ['QT_SCALE_FACTOR_ROUNDING_POLICY'] = 'Floor'

# 输入法：pip 装的 PySide6 只带 ibus 插件，没有 fcitx 的；fcitx5 自带 ibus 兼容接口，所以这时改走 ibus
def _im_module():
    import importlib.util
    spec = importlib.util.find_spec('PySide6')
    plugins = Path(spec.submodule_search_locations[0]) / 'Qt/plugins/platforminputcontexts' if spec else None
    want = os.environ.get('QT_IM_MODULE', '')
    if want.startswith('fcitx') and plugins and not any('fcitx' in p.name for p in plugins.glob('*')):
        os.environ['QT_IM_MODULE'] = 'ibus'


_im_module()

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import (QAction, QActionGroup, QBitmap, QColor, QCursor, QFont, QGuiApplication, QIcon, QImage,
                           QPainter, QPixmap, QRegion, QTransform)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

import theme
from chat import SIZE_LABEL, ChatWindow

ROOT = Path(__file__).resolve().parent
THEME = theme.load()                                         # 形象：themes/<id>/（见 theme.py）
ASSETS = THEME['assets']
SESSIONS = Path.home() / '.cache/desk-pet/sessions'
ALIVE = Path.home() / '.cache/desk-pet/pet.json'      # 桌宠心跳：mod 据此决定提问发不发到聊天窗
SETTINGS = Path.home() / '.config/desk-pet/settings.json'   # 托盘「设置」写的：{mirror, scale}


def load_settings():
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(**kw):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps({**load_settings(), **kw}))


CFG = load_settings()
K = max(1, int(os.environ.get('DESK_PET_SCALE') or CFG.get('scale') or 1))     # 整数放大倍数
DEBUG = bool(os.environ.get('DESK_PET_DEBUG'))

W, H = 192, 208                 # 单帧大小
WIN_W, WIN_H = 200, 240         # 窗口（未放大）；帧画在 (LEFT, TOP)，上面留给气泡
LEFT, TOP = 4, 32

# CC 状态 → 素材状态 id（缺素材时退回 idle / 默认姿态）
ANIM = {'working': 'running', 'reading': 'review', 'waiting': 'waiting', 'done': 'waving', 'error': 'failed', 'idle': 'idle'}
LABEL = {'working': '工作中', 'reading': '查看中', 'waiting': '等你回复', 'done': '完成啦', 'error': '出错了', 'idle': ''}
PRIORITY = ['waiting', 'error', 'working', 'reading', 'done', 'idle']
INTRO = {'done': 'jumping', 'waiting': 'startled-avert'}   # 切进某个状态时先播一遍的小动作
RANDOM = ['prayer-peek', 'sneeze', 'brave-gaze']           # 空闲时偶尔播；循环类播 4 秒；平时就是站着
LONG_IDLE = ['sit-swing', 'sleepy-nod']                  # 闲置太久：随机坐下或打瞌睡，一直保持
if DEBUG:
    RANDOM_MS, BORED_MS, LONG_IDLE_MS = (3e3, 4e3), 8e3, 12e3
else:
    RANDOM_MS, BORED_MS, LONG_IDLE_MS = (20e3, 40e3), 60e3, 30 * 60e3
CLICK_CURTSY_MS, CLICK_GAZE_MS = 3000, 8000
DONE_MS = 6000          # 完成：跳一下 + 招手，约 6 秒后回到待命

T0 = time.monotonic()


def now_ms():
    return (time.monotonic() - T0) * 1000


def log(msg):
    if DEBUG:
        print(f'[pet] {now_ms() / 1000:.1f}s {msg}', file=sys.stderr, flush=True)


def load_json(name):
    try:
        return json.loads((ASSETS / name).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def load_clip(meta):
    """读一个状态的 enter / sustain / exit 帧；缺任何一帧就当这个状态不存在。"""
    phases = {}
    for name, ph in meta.get('phases', {}).items():
        frames = [(QImage(str(ASSETS / ph['path'] / f'{i:02d}.png')), ms) for i, ms in enumerate(ph['durations_ms'])]
        if not frames or any(img.isNull() for img, _ in frames):
            return None
        phases[name] = frames
    return {'mode': meta.get('mode', 'loop'), 'phases': phases} if len(phases) == 3 else None


def cc_state():
    """汇总所有 CC 会话：等你回复 > 出错 > 工作中 > 查看中 > 完成 > 空闲。
    3 分钟没心跳的不算；ended 和 1 天前的文件顺手删掉；完成/出错超过 2 分钟算空闲。"""
    counts, praised, now, live = {}, 0, time.time(), []
    for p in SESSIONS.glob('*.json'):
        try:
            age = now - p.stat().st_mtime
            v = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        st = v.get('state', '')
        if st == 'ended' or age > 86400:
            p.unlink(missing_ok=True)
            for f in (SESSIONS.parent / 'chat').glob(f'{p.stem}.*'):   # 这个会话的聊天文件也清掉
                f.unlink(missing_ok=True)
            shutil.rmtree(SESSIONS.parent / 'media' / p.stem, ignore_errors=True)   # 发过的图片也清掉
            continue
        if age > 180:
            continue
        praised = max(praised, v.get('praised') or 0)
        live.append((p.stem, v.get('cwd', ''), st, p.stat().st_mtime))
        if st in ('done', 'error') and age > 120:
            st = 'idle'
        counts[st] = counts.get(st, 0) + 1
    for f in (SESSIONS.parent / 'chat').glob('*'):                 # 会话文件已经没了的聊天记录，放一天后清掉
        try:
            if not (SESSIONS / f'{f.name.split(".")[0]}.json').exists() and now - f.stat().st_mtime > 86400:
                f.unlink()
        except OSError:
            pass
    live = [x[:3] for x in sorted(live, key=lambda x: -x[3])]       # 最近有动静的会话排前面
    return next((s for s in PRIORITY if s in counts), 'idle'), counts, praised, live


class Pet(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(WIN_W * K, WIN_H * K)
        self.canvas = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)

        # 素材
        self.neutral = QImage(str(ASSETS / 'neutral-N.png'))
        self.clips = {}
        for s in load_json('状态参数.json').get('states', []) + load_json('extra-states.json').get('states', []):
            if (c := load_clip(s)):
                self.clips[s['id']] = c
        for v in load_json('gaze/gaze.json').get('variants', []):
            if (c := load_clip(v)):
                self.clips[f"gaze:{v['angle_degrees']:g}"] = c
        log(f"loaded {[k for k in self.clips if not k.startswith('gaze:')]} | "
            f"{sum(k.startswith('gaze:') for k in self.clips)} 个视线方向")

        # 目标
        self.cc, self.bubble = 'idle', ''
        self.bubble_off = False                  # 点过一下：这条气泡先收起，内容变了再出来
        self.gaze, self.gaze_until = None, 0     # 点击后的一小段时间里视线跟着鼠标
        self.done_since = 0
        self.temp = None                         # 临时动作 {key, until, urgent, random}
        self.drag, self.drag_until = None, 0     # 拖动时左右跑
        self.idle_since = self.waiting_since = now_ms()
        self.long_idle = None                    # 这次闲置选中的坐下 / 打瞌睡
        self.next_random = now_ms() + RANDOM_MS[0]
        self.praised = None
        # 播放
        self.cur, self.phase, self.idx, self.flip, self.until = None, 'sustain', 0, False, 0
        self.frame = self.neutral
        # 鼠标
        self.press = None
        self.mirror = bool(CFG.get('mirror'))     # 设置：左右镜像
        self.chat = ChatWindow(THEME, self.neutral, CFG.get('chat_size', 'small'))
        self.chat.pet = self

        g = QGuiApplication.primaryScreen().availableGeometry()
        self.move(g.right() - 60 - self.width(), g.bottom() - 40 - self.height())
        self.render()

        for ms, fn in ((15, self.step), (40, self.track_cursor), (1000, self.poll)):
            t = QTimer(self)
            t.timeout.connect(fn)
            t.start(ms)
        self.poll()

    # ---- 选目标 ----
    def target(self, now):
        if self.drag and now < self.drag_until and self.drag in self.clips:
            return {'key': self.drag, 'urgent': True}
        t = self.temp
        if t and not (t.get('until') and t['until'] < now) and t['key'] in self.clips:
            return {'key': t['key'], 'urgent': t.get('urgent', False)}
        self.temp = None
        if self.gaze and now < self.gaze_until:
            return self.gaze
        cc = self.cc
        if cc == 'done' and now - self.done_since > DONE_MS:
            cc = 'idle'                          # 招手几秒就够了，之后站着待命、偶尔小动作
        if cc == 'idle':
            if now - self.idle_since > LONG_IDLE_MS:     # 闲置 30 分钟以上：随机坐下或打瞌睡，保持住
                if not self.long_idle:
                    self.long_idle = random.choice([k for k in LONG_IDLE if k in self.clips] or [None])
                    log(f'闲置太久 -> {self.long_idle}')
                if self.long_idle:
                    return {'key': self.long_idle}
            if now > self.next_random:           # 站着发呆时偶尔做个小动作
                self.next_random = now + random.uniform(*RANDOM_MS)
                pool = [k for k in RANDOM if k in self.clips]
                if pool:
                    k = random.choice(pool)
                    self.temp = {'key': k, 'random': True,
                                 'until': None if self.clips[k]['mode'] == 'oneshot' else now + 4000}
                    return {'key': k}
        k = ANIM[cc]
        if cc == 'waiting' and now - self.waiting_since > BORED_MS and 'bored-wait' in self.clips:
            k = 'bored-wait'                     # 等你回复太久没人理
        if k in self.clips:
            return {'key': k}
        return {'key': 'idle'} if 'idle' in self.clips else None

    def gaze_clip(self, a):
        """视线角度 → 可用素材：本身 > 镜像 > 最近的可用角度。"""
        key = lambda x: f'gaze:{x % 360:g}'
        if key(a) in self.clips:
            return {'key': key(a)}
        if key(360 - a) in self.clips:
            return {'key': key(360 - a), 'flip': True}
        best = min((k for k in self.clips if k.startswith('gaze:')),
                   key=lambda k: abs((float(k[5:]) - a + 540) % 360 - 180), default=None)
        return {'key': best} if best else None

    # ---- 播放：enter → sustain(循环) → exit ----
    def start(self, t):
        self.cur, self.flip, self.phase, self.idx = t['key'], t.get('flip', False), 'enter', 0
        log(f"play {self.cur}{' (镜像)' if self.flip else ''}")

    def step(self):
        now = now_ms()
        t = self.target(now)
        same = bool(t) and self.cur == t['key'] and self.flip == t.get('flip', False)
        if not self.cur:
            if t:
                self.start(t)
        else:
            # 视线换方向：直接跳到新方向的保持帧，不回站立
            if not same and t and self.cur.startswith('gaze:') and t['key'].startswith('gaze:'):
                self.cur, self.flip, self.phase, self.idx, self.until = t['key'], t.get('flip', False), 'sustain', 0, 0
                same = True
            c = self.clips[self.cur]
            frames = c['phases'][self.phase]
            # 视线保持帧、拖动/点击可以马上打断；其他循环播完这一圈再退出
            if not same and self.phase == 'sustain' and (c['mode'] in ('hold', 'parameterized_hold') or (t and t.get('urgent'))):
                self.phase, self.idx = 'exit', 0
            elif now >= self.until:
                self.idx += 1
                if self.idx >= len(frames):
                    self.idx = 0
                    if self.phase == 'enter':
                        self.phase = 'sustain'
                    elif self.phase == 'sustain':
                        if c['mode'] == 'oneshot':
                            self.phase = 'exit'
                            if self.temp and self.temp['key'] == self.cur:
                                self.temp = None
                        elif not same:
                            self.phase = 'exit'
                        elif c['mode'] == 'hold':
                            self.idx = len(frames) - 1
                    else:
                        self.cur = None
                        if t:
                            self.start(t)
            else:
                return
        if self.cur:
            fs = self.clips[self.cur]['phases'][self.phase]
            self.frame, ms = fs[min(self.idx, len(fs) - 1)]
        else:
            self.frame, ms = self.neutral, 200
        self.until = now + ms
        self.render()

    # ---- 画面 + 点穿形状 ----
    def render(self):
        self.canvas.fill(Qt.transparent)
        p = QPainter(self.canvas)
        p.scale(K, K)
        p.translate(LEFT, TOP)
        if self.flip != self.mirror:             # 动作自己的镜像 × 设置里的镜像
            p.setTransform(QTransform(-1, 0, 0, 1, W, 0), True)
        p.drawImage(0, 0, self.frame)
        p.resetTransform()
        if self.bubble and not self.bubble_off:
            p.scale(K, K)
            p.setRenderHint(QPainter.Antialiasing)
            c = THEME['colors']
            p.setPen(QColor(c['bubble_border']))
            p.setBrush(QColor(c['bubble_bg']))
            p.drawRoundedRect(8, 4, 184, 22, 11, 11)
            f = QFont(THEME['font']) if THEME['font'] else QFont()
            f.setPixelSize(12)
            p.setFont(f)
            p.setPen(QColor(c['bubble_ink']))
            p.drawText(QRect(8, 4, 184, 22), Qt.AlignCenter, self.bubble)
        p.end()
        self.setMask(QRegion(QBitmap.fromImage(self.canvas.createAlphaMask())))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(0, 0, self.canvas)

    # ---- 鼠标 ----
    def track_cursor(self):
        """视线方向（只在点击后的一小段时间里用）；鼠标在她身上时不转头。"""
        rel = QCursor.pos() - self.pos()
        dx, dy = rel.x() / K - LEFT - 96, rel.y() / K - TOP - 80
        if math.hypot(dx, dy) > 70:
            a = (math.degrees(math.atan2(dx, -dy)) + 360) % 360
            if self.mirror:                      # 整体镜像了：视线角度也左右对调
                a = 360 - a
            self.gaze = self.gaze_clip(round(a / 22.5) * 22.5 % 360)
        else:
            self.gaze = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            g = e.globalPosition().toPoint()
            self.press, self.press_win, self.dragging, self.drag_x = g, self.pos(), False, g.x()

    def mouseMoveEvent(self, e):
        if self.press is None:
            return
        g = e.globalPosition().toPoint()
        if not self.dragging and (g - self.press).manhattanLength() > 4:
            self.dragging = True
        if self.dragging:                        # 按住移动超过几像素算拖动，按方向跑
            self.move(self.press_win + (g - self.press))
            if abs(g.x() - self.drag_x) > 2:
                right = (g.x() > self.drag_x) != self.mirror   # 镜像时反过来选，翻转后正好朝移动方向跑
                self.drag = 'running-right' if right else 'running-left'
                self.drag_until, self.drag_x = now_ms() + 400, g.x()

    def mouseReleaseEvent(self, e):
        if self.press is not None and not self.dragging:   # 没移动就松开算点击：行提裙礼，之后看鼠标
            now = now_ms()
            self.temp = {'key': 'modest-curtsy', 'until': now + CLICK_CURTSY_MS, 'urgent': True}
            self.gaze_until = now + CLICK_CURTSY_MS + CLICK_GAZE_MS
            self.idle_since, self.long_idle = now, None   # 点醒她，重新计闲置
            self.bubble_off = True
            if self.chat.unread:                     # 有新回复：点一下直接打开聊天窗
                self.chat.open_near(self)
            self.render()
            log('点击')
        self.press = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.chat.open_near(self)

    # ---- CC 状态 ----
    def poll(self):
        state, counts, praised, live = cc_state()
        now = now_ms()
        try:
            ALIVE.write_text(json.dumps({'ts': int(time.time() * 1000)}))
        except OSError:
            pass
        self.chat.update_sessions(live)
        if state != self.cc:
            log(f'cc {self.cc} -> {state}')
            if INTRO.get(state) in self.clips:
                self.temp = {'key': INTRO[state]}
            if state == 'idle':
                self.idle_since, self.long_idle = now, None
            if state == 'waiting':
                self.waiting_since = now
            if state == 'done':
                self.done_since = now
                self.idle_since, self.long_idle = now, None   # 招完手才开始算闲置
        self.cc = state
        if self.praised is not None and praised > self.praised:   # 被夸了：藏脸
            self.temp = {'key': 'hidden-blush', 'until': now + 4500}
            log('被夸')
        self.praised = praised
        # 气泡：最要紧的状态（多个就 ×N），其他会话在忙的话补上，例如「等你回复 +2 工作中」
        n = counts.get(state, 0)
        others = ''.join(f' +{v} {LABEL.get(k, k)}' for k, v in counts.items() if k not in (state, 'idle') and v > 0)
        text = LABEL[state] + (f' ×{n}' if n > 1 else '') + others if LABEL[state] else ''
        if self.chat.unread:
            text = THEME['text']['new_reply']
        if text != self.bubble:
            self.bubble, self.bubble_off = text, False
            self.render()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('desk-pet')
    app.setQuitOnLastWindowClosed(False)
    pet = Pet()
    pet.show()

    tray = QSystemTrayIcon(QIcon(QPixmap.fromImage(pet.neutral)), app)
    tray.setToolTip(THEME['name'])
    menu = QMenu()
    chat = QAction('聊天', menu)
    chat.triggered.connect(lambda: pet.chat.open_near(pet))
    menu.addAction(chat)
    restart = lambda: os.execv(sys.executable, [sys.executable, *sys.argv])
    settings = menu.addMenu('设置')
    mirror = QAction('镜像（左右翻转）', settings, checkable=True, checked=pet.mirror)
    def set_mirror(on):
        pet.mirror = on
        save_settings(mirror=on)
        pet.render()
    mirror.toggled.connect(set_mirror)
    settings.addAction(mirror)
    size = settings.addMenu('大小')                # 改大小要重启（窗口和素材按倍数建）
    for n in (1, 2, 3):
        a = QAction(f'{n} 倍', size, checkable=True, checked=n == K)
        a.triggered.connect(lambda _=False, n=n: (save_settings(scale=n), restart()))
        size.addAction(a)
    chat_size = settings.addMenu('聊天窗大小')      # 马上生效，不用重启
    group = QActionGroup(chat_size)
    for key, name in SIZE_LABEL.items():
        a = QAction(name, chat_size, checkable=True, checked=key == CFG.get('chat_size', 'small'))
        a.triggered.connect(lambda _=False, key=key: (save_settings(chat_size=key), pet.chat.apply_size(key)))
        group.addAction(a)
        chat_size.addAction(a)
    looks = menu.addMenu('形象')                  # 换形象：记下选择，重启自己
    for tid, name in theme.available():
        a = QAction(name, looks, checkable=True, checked=tid == THEME['id'])
        a.triggered.connect(lambda _=False, tid=tid: (theme.choose(tid), os.execv(sys.executable, [sys.executable, *sys.argv])))
        looks.addAction(a)
    toggle = QAction('显示 / 隐藏', menu)
    toggle.triggered.connect(lambda: pet.setVisible(not pet.isVisible()))
    quit_ = QAction('退出', menu)
    quit_.triggered.connect(app.quit)
    menu.addAction(toggle)
    menu.addAction(quit_)
    tray.setContextMenu(menu)
    tray.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
