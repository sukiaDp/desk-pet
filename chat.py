"""桌宠的聊天小窗：给开了 /desk-pet 的 CC 会话发消息、看回复、点选项回答提问。

和 cc-mod 之间用文件传话（都在 ~/.cache/desk-pet/chat/）：
  <会话id>.in.json   桌宠写：{msgs: [{id, text} | {id, answer: {qid, answers}} | {id, terminal: qid}]}
  <会话id>.out.json  mod 写：{ack, log: [{id, role, text, src, ts}], ask: {qid, questions} | null, perm: 工具名 | null}
权限确认只能在终端里点，这里只提醒。
"""
import html
import json
import os
import re
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QImage, QKeySequence, QPalette, QTextDocument, QGuiApplication, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

import book

CHAT = Path.home() / '.cache/desk-pet/chat'
PAGE = 30                                          # 聊天记录一页多少条
MEDIA = Path.home() / '.cache/desk-pet/media'      # 发出去的图片：media/<会话id>/
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
# 聊天窗大小：(宽, 高, 字号倍数)；托盘「设置 → 聊天窗大小」切换
SIZES = {'small': (440, 700, 1.0), 'medium': (560, 880, 1.25), 'large': (680, 1060, 1.5)}
SIZE_LABEL = {'small': '小', 'medium': '中', 'large': '大'}
STATE_LABEL = {'working': '工作中', 'reading': '查看中', 'waiting': '等你回复', 'done': '完成啦', 'error': '出错了', 'idle': '空闲'}

def rgba(hex_, a):
    q = QColor(hex_)
    return f'rgba({q.red()},{q.green()},{q.blue()},{a})'


def book_style(t):
    """书页外观：没有气泡，正文像印在纸上；你的话是朱红斜体，像经书里的红字批注。"""
    c = t['colors']
    font = ''                                    # 字体由 theme.register_fonts 设成程序默认字体
    return font + f"""
QWidget#chat {{ background: transparent; color: {c['ink']}; }}
QWidget#chat QLabel, QWidget#chat QCheckBox {{ color: {c['ink']}; background: transparent; }}
QScrollArea, QWidget#msgs {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 6px; }}
QScrollBar::handle:vertical {{ background: {rgba(c['gold'], 0.55)}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QWidget#chat QLabel[role="user"] {{ color: {c['rubric']}; font-style: italic; font-size: 14px; padding: 7px 22px 9px 14px;
  background: {rgba(c['rubric'], 0.06)}; border: 1px solid {rgba(c['rubric'], 0.35)}; border-radius: 4px; }}
QWidget#chat QLabel[role="cc"] {{ color: {c['ink']}; font-size: 14px; padding: 9px 22px 12px 15px;
  background: {rgba('#fffaf0', 0.45)}; border: 1px solid {rgba(c['gold'], 0.45)}; border-radius: 4px; }}
QWidget#chat QLabel[role="user"][pending="true"] {{ color: {c['muted']}; }}
QWidget#chat QLabel#meta {{ color: {c['muted']}; font-size: 11px; font-style: italic; }}
QWidget#chat QLabel#optdesc {{ color: {c['muted']}; font-size: 12px; }}
QWidget#chat QLabel#activity {{ color: {c['muted']}; font-style: italic; font-size: 12px; padding: 4px 6px; }}
QWidget#chat QLabel#sep {{ color: {c['gold']}; font-size: 12px; }}
QWidget#chat QLabel#perm {{ color: {c['rubric']}; background: {rgba(c['rubric'], 0.08)}; border-left: 3px solid {c['rubric']}; padding: 4px 8px; font-style: italic; }}
QFrame#ask {{ background: {rgba('#fffaf0', 0.45)}; border: none; border-top: 1px solid {c['gold']}; border-bottom: 1px solid {c['gold']}; }}
QFrame#ask QLabel {{ background: transparent; font-size: 14px; }}
QPushButton {{ color: {c['ink']}; background: transparent; border: 1px solid {c['border']}; border-radius: 3px; padding: 4px 12px; }}
QPushButton:hover {{ border-color: {c['gold']}; }}
QPushButton[opt="true"] {{ text-align: left; border: none; padding: 5px 8px; font-size: 14px; }}
QPushButton[opt="true"]:hover {{ background: {rgba(c['gold'], 0.18)}; }}
QPushButton[opt="true"]:checked {{ color: {c['rubric']}; background: {rgba(c['gold'], 0.3)}; font-weight: bold; }}
QCheckBox {{ spacing: 8px; padding: 4px 8px; font-size: 14px; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid {c['gold']}; border-radius: 2px; background: {rgba('#fffaf0', 0.7)}; }}
QCheckBox::indicator:checked {{ background: {c['rubric']}; border-color: {c['gold']}; }}
QComboBox {{ color: {c['ink']}; background: transparent; border: none; border-bottom: 1px solid {c['border']}; padding: 2px 4px; font-style: italic; }}
QComboBox QAbstractItemView {{ color: {c['ink']}; background: {c['page']}; selection-background-color: {c['gold']}; }}
QLineEdit {{ color: {c['ink']}; background: transparent; border: none; border-bottom: 1px solid {c['border']}; padding: 6px 2px; font-size: 14px; }}
QLineEdit:focus {{ border-bottom: 1px solid {c['gold']}; }}
QPushButton#send {{ padding: 0; border-radius: 19px; font-size: 20px; color: {c['accent_ink']};
  background: qradialgradient(cx:0.4, cy:0.35, radius:0.8, stop:0 {QColor(c['rubric']).lighter(135).name()}, stop:1 {QColor(c['rubric']).darker(140).name()});
  border: 2px solid {QColor(c['rubric']).darker(160).name()}; }}
QPushButton#send:disabled {{ background: {c['border']}; color: {c['muted']}; border-color: {c['border']}; }}
QPushButton#clip {{ background: transparent; border: none; padding: 0; }}
QPushButton#clip:hover {{ background: {rgba(c['gold'], 0.18)}; border-radius: 6px; }}
QLabel#thumb {{ border: 1px solid {c['gold']}; border-radius: 3px; }}
QWidget#chat QLabel#filechip {{ border: 1px solid {c['gold']}; border-radius: 3px; padding: 4px 22px 4px 8px; font-size: 12px; }}
QPushButton#unthumb {{ color: #fff; background: rgba(0,0,0,0.55); border: none; border-radius: 3px; padding: 0; font-size: 11px; }}
QPushButton#tobottom {{ color: {c['rubric']}; background: {rgba(c['page'], 0.95)}; border: 1px solid {c['gold']}; border-radius: 16px; padding: 0 8px; font-size: 14px; }}
QPushButton#tobottom:hover {{ background: {c['page']}; border-color: {c['rubric']}; }}
QPushButton#close {{ color: {c['muted']}; background: transparent; border: none; padding: 0; font-size: 15px; }}
QPushButton#close:hover {{ color: {c['rubric']}; }}
"""


def style(t, k=1.0):
    """按主题配色生成样式表，再按大小倍数 k 缩放所有字号。"""
    css = book_style(t) if t.get('look') == 'book' else plain_style(t)
    css = re.sub(r'font-size: (\d+)px', lambda m: f'font-size: {round(int(m.group(1)) * k)}px', css)
    return f'QWidget#chat * {{ font-size: {round(13 * k)}px; }}\n' + css   # 没写字号的控件用这个，放最前面好被覆盖


def plain_style(t):
    """普通聊天窗；每个控件都写明颜色，不吃系统深色主题。"""
    c = t['colors']
    font = ''                                    # 字体由 theme.register_fonts 设成程序默认字体
    return font + f"""
QWidget#chat {{ background: {c['bg']}; color: {c['ink']}; }}
QWidget#chat QLabel, QWidget#chat QCheckBox {{ color: {c['ink']}; }}
QScrollArea, QWidget#msgs {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QWidget#chat QLabel[role="user"] {{ background: {c['user_bg']}; color: {c['user_ink']}; border-radius: 12px; padding: 7px 10px; }}
QWidget#chat QLabel[role="cc"] {{ background: {c['pet_bg']}; color: {c['pet_ink']}; border: 1px solid {c['border']}; border-radius: 12px; padding: 7px 10px; }}
QWidget#chat QLabel[role="user"][pending="true"] {{ color: {c['muted']}; }}
QWidget#chat QLabel#meta {{ color: {c['muted']}; font-size: 11px; }}
QWidget#chat QLabel#optdesc {{ color: {c['muted']}; font-size: 12px; }}
QWidget#chat QLabel#activity {{ color: {c['muted']}; font-style: italic; font-size: 12px; padding: 4px 6px; }}
QWidget#chat QLabel#perm {{ background: {c['warn_bg']}; color: {c['warn_ink']}; border-radius: 8px; padding: 6px 9px; }}
QFrame#ask {{ background: {c['panel']}; border: 1px solid {c['gold']}; border-radius: 12px; }}
QFrame#ask QLabel {{ background: transparent; }}
QPushButton {{ color: {c['ink']}; background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 5px 12px; }}
QPushButton:hover {{ border-color: {c['gold']}; }}
QPushButton[opt="true"] {{ text-align: left; padding: 7px 10px; }}
QPushButton[opt="true"]:checked {{ background: {c['gold']}; color: {c['accent_ink']}; border-color: {c['accent']}; }}
QCheckBox {{ spacing: 8px; padding: 3px 0; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {c['gold']}; border-radius: 4px; background: {c['panel']}; }}
QCheckBox::indicator:checked {{ background: {c['gold']}; border-color: {c['accent']}; }}
QComboBox {{ color: {c['ink']}; background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 4px 9px; }}
QComboBox QAbstractItemView {{ color: {c['ink']}; background: {c['panel']}; selection-background-color: {c['gold']}; }}
QLineEdit {{ color: {c['ink']}; padding: 7px 11px; border: 1px solid {c['border']}; border-radius: 16px; background: {c['panel']}; }}
QLineEdit:focus {{ border-color: {c['gold']}; }}
QPushButton#send {{ padding: 6px 16px; border-radius: 15px; background: {c['accent']}; color: {c['accent_ink']}; border: 1px solid {c['gold']}; }}
QPushButton#send:disabled {{ background: {c['border']}; color: {c['muted']}; border-color: {c['border']}; }}
QPushButton#tobottom {{ color: {c['accent']}; background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 16px; padding: 0 8px; font-size: 14px; }}
QPushButton#clip {{ background: transparent; border: none; padding: 0; }}
QPushButton#clip:hover {{ background: {rgba(c['gold'], 0.18)}; border-radius: 6px; }}
QLabel#thumb {{ border: 1px solid {c['gold']}; border-radius: 3px; }}
QWidget#chat QLabel#filechip {{ border: 1px solid {c['gold']}; border-radius: 3px; padding: 4px 22px 4px 8px; font-size: 12px; }}
QPushButton#unthumb {{ color: #fff; background: rgba(0,0,0,0.55); border: none; border-radius: 3px; padding: 0; font-size: 11px; }}
"""


def human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def file_chip(m, short=False):
    """文件条上的字：▤ 名字 · 大小；文件夹 ▦ 名字/。"""
    name = m.get('name') or Path(m.get('path', '')).name
    if short and len(name) > 22:
        name = name[:10] + '…' + name[-9:]
    return f'▦ {name}/' if m.get('kind') == 'dir' else f'▤ {name} · {human_size(m.get("size", 0))}'


_PATH = re.compile(r'(`?)(/(?:[\w.@+~-]+/)*[\w.@+~-]+/?)\1')


def linkify(text):
    """CC 回复里提到的、本机确实存在的绝对路径变成可点的链接（代码块里的不动）。"""
    parts = text.split('```')
    for i in range(0, len(parts), 2):            # 偶数段在代码块外
        def sub(m):
            tick, p = m.group(1), m.group(2)
            start = m.start()
            seg = parts[i]
            if start >= 2 and seg[start - 2:start] == '](':  # 已经是链接
                return m.group(0)
            if p.count('/') < 2 or not Path(p).exists():
                return m.group(0)
            name = (Path(p).name or p) + ('/' if Path(p).is_dir() else '')   # 只显示名字，完整路径在链接里
            return f'[{tick}{name}{tick}]({QUrl.fromLocalFile(p).toString()})'
        parts[i] = _PATH.sub(sub, parts[i])
    return '```'.join(parts)


def image_paths(text):
    """回复里提到的、本机存在的图片路径（代码块外，去重，最多 6 张）。"""
    out = []
    for i, seg in enumerate(text.split('```')):
        if i % 2:
            continue
        for m in _PATH.finditer(seg):
            p = m.group(2)
            if Path(p).suffix.lower() in IMAGE_EXT and p not in out and Path(p).is_file():
                out.append(p)
    return out[:6]


def round_avatar(img, box, size=34):
    """从默认姿态图里裁出头像，最近邻放大（像素画不糊），裁成圆形。"""
    x, y, n = box
    src = QPixmap.fromImage(img.copy(x, y, n, n)).scaled(size, size, Qt.KeepAspectRatio, Qt.FastTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    p.setClipPath(path)
    p.drawPixmap(0, 0, src)
    p.end()
    return out


def read_json(p):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def write_json(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(v, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, p)


def send(sid, item):
    """往会话的收件箱追加一条；mod 处理过的（id ≤ ack）顺手清掉。"""
    out = read_json(CHAT / f'{sid}.out.json') or {}
    inbox = CHAT / f'{sid}.in.json'
    msgs = [m for m in (read_json(inbox) or {}).get('msgs', []) if m.get('id', 0) > out.get('ack', 0)]
    last = max([m['id'] for m in msgs] + [out.get('ack', 0)])
    item = {'id': max(int(time.time() * 1000), last + 1), **item}
    msgs.append(item)
    write_json(inbox, {'msgs': msgs})
    return item


class Framed(QLabel):
    """书页外观的文字框：样式表画底色和细边，这里再补上角饰。"""
    def __init__(self, color, k):
        super().__init__()
        self.color, self.k = color, k

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        book.frame_ornaments(p, QRectF(self.rect()).adjusted(0.5, 0.5, -1.5, -1.5), self.color, self.k)
        p.end()


class ChatWindow(QWidget):
    def __init__(self, theme, neutral, size='small'):
        self.book = theme.get('look') == 'book'
        flags = Qt.Window | Qt.WindowStaysOnTopHint | (Qt.FramelessWindowHint if self.book else Qt.Widget)
        super().__init__(None, flags)
        self.t, self.tx = theme, theme['text']
        self.setObjectName('chat')
        self.setWindowTitle(self.tx['title'] or theme['name'])
        self.neutral, self.k, self.avatar = neutral, 1.0, None
        if self.book:
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.cover, self.drag_from, self.subtitle = None, None, ''
            self.close_btn = QPushButton('✕', self)
            self.close_btn.setObjectName('close')
            self.close_btn.setCursor(Qt.PointingHandCursor)
            self.close_btn.clicked.connect(self.hide)
        self.sessions = []           # [(sid, cwd, state)]
        self.sid = None
        self.shown_key = None        # 上次画的内容，没变就不重画
        self.ask_qid = None
        self.seen = {}               # sid -> 看过的最后一条 CC 回复 id
        self.hist = {}               # sid -> 全部聊天记录（chat/<sid>.history.jsonl，桌宠自己存）
        self.show_n = PAGE           # 当前会话显示最近多少条；滚到顶再加一页
        self.keep_from_bottom = None # 加载更早的记录时，保持离底部的距离不变
        self.activity, self.dots, self.more = '', 0, False
        self.unread = False          # 窗口没开时来了新回复 / 新提问

        top = QHBoxLayout()
        self.pick = QComboBox()
        self.pick.currentIndexChanged.connect(self.on_pick)
        top.addWidget(self.pick, 1)

        self.perm = QLabel()
        self.perm.setObjectName('perm')
        self.perm.setWordWrap(True)
        self.perm.hide()

        self.msgs = QWidget()
        self.msgs.setObjectName('msgs')
        self.list = QVBoxLayout(self.msgs)
        self.list.setContentsMargins(4, 4, 4, 4)
        self.list.setSpacing(6)
        self.list.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.msgs)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(220)
        self.scroll.verticalScrollBar().valueChanged.connect(self.on_scroll)
        self.scroll.verticalScrollBar().rangeChanged.connect(lambda *_: self.update_down())
        self.down = QPushButton('↓', self.scroll)   # 不在最底下时：右下角一个「回到底部」
        self.down.setObjectName('tobottom')
        self.down.setCursor(Qt.PointingHandCursor)
        self.down.clicked.connect(self.to_bottom)
        self.down.hide()
        self.new_below, self.force_bottom = False, False
        self.anim = QPropertyAnimation(self.scroll.verticalScrollBar(), b'value', self)   # 平滑滚动
        self.anim.setDuration(260)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.finished.connect(self.anim_done)
        self.stick, self.target = False, 0
        self.scroll.viewport().installEventFilter(self)
        self.act = QLabel()                      # 页尾一行：CC 正在做什么
        self.act.setObjectName('activity')
        self.act.hide()
        tick = QTimer(self)                      # 省略号一跳一跳
        tick.timeout.connect(self.tick_dots)
        tick.start(450)

        self.ask = QFrame()
        self.ask.setObjectName('ask')
        self.ask_box = QVBoxLayout(self.ask)
        self.ask.hide()

        bottom = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(self.tx['placeholder'])
        self.input.returnPressed.connect(self.on_send)
        self.btn = QPushButton(self.tx['send'])
        self.btn.setObjectName('send')
        self.btn.clicked.connect(self.on_send)
        self.clip = QPushButton()                # 回形针：选图片
        self.clip.setObjectName('clip')
        self.clip.setCursor(Qt.PointingHandCursor)
        self.clip.setToolTip('附上文件或图片（也可以直接拖进来，或在输入框里粘贴截图）')
        self.clip.clicked.connect(self.pick_files)
        bottom.addWidget(self.clip)
        bottom.addWidget(self.input, 1)
        bottom.addWidget(self.btn)
        self.pending_imgs = []                   # 待发图片：[(QImage 或 None, 源文件路径 或 None)]
        self.pending_files = []                  # 待发的其他文件 / 文件夹：路径（不复制，直接把原路径给 CC）
        self.tray = QWidget()                    # 待发缩略图一排
        self.tray_row = QHBoxLayout(self.tray)
        self.tray_row.setContentsMargins(0, 0, 0, 0)
        self.tray.hide()
        self.input.installEventFilter(self)      # 粘贴截图
        self.setAcceptDrops(True)                # 拖图片进来

        lay = QVBoxLayout(self)
        if self.book:                            # 内容放在纸页里，顶上留给标题
            b = book.BORDER
            lay.setContentsMargins(b + 16, b + book.header(bool(self.tx['title'])), b + 5 + 16, b + 5 + 24)   # 底下给页角花饰留位置
            self.btn.setText(self.tx.get('seal', self.tx['send']))   # 圆形火漆印；没写字就压一个十字（大小在 apply_size 里定）
        lay.addLayout(top)
        lay.addWidget(self.perm)
        lay.addWidget(self.scroll, 1)
        lay.addWidget(self.tray)
        lay.addLayout(bottom)
        self.apply_size(size)

    def apply_size(self, name):
        """小 / 中 / 大：窗口、字号、头像、火漆印一起缩放，马上生效。"""
        self.size_name = name if name in SIZES else 'small'
        w, h, k = SIZES.get(name, SIZES['small'])
        if not self.book:
            w, h = w - 20, h - 20
        self.k = k
        self.setStyleSheet(style(self.t, k))
        pal = self.palette()                     # 文字里的链接用主题色，不用默认的亮蓝
        pal.setColor(QPalette.Link, QColor(self.t['colors']['rubric' if self.book else 'accent']))
        self.setPalette(pal)
        a = None
        if self.t.get('avatar') and not self.neutral.isNull():
            a = round_avatar(self.neutral, self.t['avatar'], round(34 * k))
            if self.book:
                a = book.ring_avatar(a, self.t['colors']['gold'])
        self.avatar = a
        if self.book:
            n = round(38 * k)
            self.btn.setFixedSize(n, n)
            self.btn.setStyleSheet(f'border-radius: {n // 2}px;')
            if not self.btn.text():
                self.btn.setIcon(QIcon(book.seal_icon(round(22 * k), self.t['colors']['accent_ink'])))
                self.btn.setIconSize(QSize(round(22 * k), round(22 * k)))
        n = round(34 * k)                         # 回形针按钮
        self.clip.setFixedSize(n, n)
        self.clip.setIcon(QIcon(book.clip_icon(round(22 * k), self.t['colors']['muted'])))
        self.clip.setIconSize(QSize(round(22 * k), round(22 * k)))
        self.draw_tray()
        self.resize(w, h)
        QTimer.singleShot(0, self.update_down)
        self.shown_key = None                    # 头像、气泡宽度都变了：重画对话
        self.refresh()
        self.update()

    # ---- 桌宠每秒调一次 ----
    def update_sessions(self, sessions):
        """sessions: [(sid, cwd, state)]，只含开了 /desk-pet、还有心跳的会话。"""
        self.sessions = sessions
        ids = [s[0] for s in sessions]
        if sorted(self.pick.itemData(i) for i in range(self.pick.count())) == sorted(ids):
            for i in range(self.pick.count()):   # 会话没变：只改文字，不重建（不然打开的下拉框会被关掉）
                s = sessions[ids.index(self.pick.itemData(i))]
                if self.pick.itemText(i) != self.label(s):
                    self.pick.setItemText(i, self.label(s))
        else:
            self.pick.blockSignals(True)
            self.pick.clear()
            for s in sessions:
                self.pick.addItem(self.label(s), s[0])
            self.pick.blockSignals(False)
            if self.sid in ids:
                self.pick.setCurrentIndex(ids.index(self.sid))
            elif ids:
                self.pick.setCurrentIndex(0)
                self.sid = ids[0]
            else:
                self.sid = None
        self.pick.setVisible(len(sessions) > 1)
        title = self.tx['title'] or self.t['name']
        self.setWindowTitle(f'{title} · {self.label(sessions[ids.index(self.sid)])}' if self.sid in ids else title)
        if self.book:
            sub = '' if len(sessions) > 1 else (self.label(sessions[ids.index(self.sid)]) if self.sid in ids else '')
            if sub != self.subtitle:
                self.subtitle = sub
                self.update()
        has = bool(sessions)
        self.input.setEnabled(has)
        self.btn.setEnabled(has)
        if not has:
            self.input.setPlaceholderText(self.tx['no_session'])
        else:
            self.input.setPlaceholderText(self.tx['placeholder'])

        # 没开窗口时：其他会话来了新回复或提问也要提醒
        for sid, _, _ in sessions:
            out = read_json(CHAT / f'{sid}.out.json') or {}
            self.archive(sid, out.get('log', []))
            last = max([e['id'] for e in out.get('log', []) if e.get('role') == 'cc'] or [0])
            if sid not in self.seen:
                self.seen[sid] = last          # 第一次见到这个会话：旧的不算未读
            if out.get('ask'):
                if not self.isVisible() or self.sid != sid:
                    self.sid = sid
                    self.pick.setCurrentIndex(self.pick.findData(sid))
                    self.open_near()           # 有提问要选：直接弹出来
            elif last > self.seen[sid] and (not self.isVisible() or self.sid != sid):
                self.unread = True
        self.refresh()

    @staticmethod
    def label(s):
        return f'{Path(s[1]).name or s[1]} · {STATE_LABEL.get(s[2], s[2])}'

    def on_pick(self, i):
        self.sid = self.pick.itemData(i)
        self.shown_key, self.show_n = None, PAGE
        self.refresh()

    # ---- 画对话 ----
    def refresh(self):
        if not self.sid:
            self.draw([], None, None, [])
            return
        out = read_json(CHAT / f'{self.sid}.out.json') or {}
        ack = out.get('ack', 0)
        pending = [m for m in (read_json(CHAT / f'{self.sid}.in.json') or {}).get('msgs', [])
                   if m.get('id', 0) > ack and (m.get('text') or m.get('media'))]
        self.archive(self.sid, out.get('log', []))
        hist = self.hist.get(self.sid, [])
        self.more = len(hist) > self.show_n
        self.activity = '' if out.get('ask') else (out.get('activity') or '')
        self.tick_dots(step=False)
        self.draw(hist[-self.show_n:], out.get('ask'), out.get('perm'), pending)
        if self.isVisible():
            self.seen[self.sid] = max([e['id'] for e in out.get('log', []) if e.get('role') == 'cc'] or [0])
            self.unread = False

    def draw(self, log, ask, perm, pending):
        key = json.dumps([self.sid, log, ask, pending], ensure_ascii=False)
        self.perm.setVisible(bool(perm))
        if perm:
            self.perm.setText('⚠ ' + self.tx['perm'].format(tool=perm))
        if key == self.shown_key:
            return
        fresh = self.shown_key is None or self.force_bottom   # 刚打开 / 换会话 / 自己发了消息：一律到底
        self.shown_key = key
        bar = self.scroll.verticalScrollBar()
        was_bottom = fresh or self.at_bottom()
        old_val = bar.value()
        while self.list.count() > 1:
            w = self.list.takeAt(1).widget()
            if w and w not in (self.ask, self.act):   # 提问区、进度行留着，重新排到最后
                w.deleteLater()
        if not log and not pending:
            self.add_note(self.tx['empty'])
        items = [(e['role'], e['text'], e.get('src'), False, e.get('media')) for e in log] + \
                [('user', m.get('text', ''), None, True, m.get('media')) for m in pending]
        for i, (role, text, src, pend, media) in enumerate(items):
            if self.book and role == 'user' and i > 0:   # 每段问答之间一个小花饰
                sep = QLabel()
                sep.setPixmap(book.divider(round(150 * self.k), self.t['colors']['gold'], self.t['colors']['rubric']))
                sep.setAlignment(Qt.AlignCenter)
                self.list.addWidget(sep)
            self.add_msg(role, text, src=src, pending=pend, media=media)
        self.list.addWidget(self.act)            # 进度一行、提问区接在对话后面，跟着一起滚动
        self.list.addWidget(self.ask)
        self.draw_ask(ask)
        # 等布局排好再滚：本来在底下就跟着到底；往上翻着看就停在原处，右下角提示有新消息；加载更早的记录时保持离底部的距离
        keep, self.keep_from_bottom, self.force_bottom = self.keep_from_bottom, None, False
        if keep is None and not was_bottom:
            self.new_below = True
        def settle():
            if keep is not None:
                bar.setValue(bar.maximum() - keep)
            elif fresh:                          # 刚打开 / 换会话 / 自己发了消息：直接到底
                self.anim.stop()
                bar.setValue(bar.maximum())
            elif was_bottom:                     # 本来就在底下：从原位置平滑滑到底
                bar.setValue(old_val)
                self.smooth_to(bar.maximum(), stick=True)
            else:
                bar.setValue(old_val)
            self.update_down()
        QTimer.singleShot(60, settle)

    # ---- 聊天记录：桌宠自己存一份全量的，mod 那边只留最近 40 条 ----
    def archive(self, sid, log):
        h = self.hist.get(sid)
        f = CHAT / f'{sid}.history.jsonl'
        if h is None:                            # 第一次：从文件读
            h = []
            try:
                for line in f.read_text(encoding='utf-8').splitlines():
                    h.append(json.loads(line))
            except (OSError, ValueError):
                pass
            self.hist[sid] = h
        last = h[-1]['id'] if h else 0
        new = [e for e in log if e.get('id', 0) > last]
        if new:
            h.extend(new)
            try:
                with f.open('a', encoding='utf-8') as fp:
                    fp.writelines(json.dumps(e, ensure_ascii=False) + '\n' for e in new)
            except OSError:
                pass

    def at_bottom(self):
        bar = self.scroll.verticalScrollBar()
        if self.stick and self.anim.state() == QAbstractAnimation.Running:
            return True                          # 正在滑向底部：算在底部
        return bar.value() >= bar.maximum() - round(6 * self.k)

    def to_bottom(self):
        self.smooth_to(self.scroll.verticalScrollBar().maximum(), stick=True)

    # ---- 平滑滚动：滚轮、回到底部都用动画滑过去 ----
    def smooth_to(self, v, stick=False):
        bar = self.scroll.verticalScrollBar()
        v = max(bar.minimum(), min(bar.maximum(), int(v)))
        self.anim.stop()
        self.stick, self.target = stick, v
        self.anim.setStartValue(bar.value())
        self.anim.setEndValue(v)
        self.anim.start()

    def anim_done(self):
        bar = self.scroll.verticalScrollBar()
        if self.stick and bar.value() < bar.maximum():   # 滑的途中内容又变长了：补到真正的底
            bar.setValue(bar.maximum())
        self.stick = False
        self.update_down()

    def wheel(self, e):
        """鼠标滚轮：一格滑一段，带缓动；连续滚就往同一个目标累加。触摸板（有像素增量）照常。"""
        if not e.pixelDelta().isNull() or not e.angleDelta().y():
            return False
        bar = self.scroll.verticalScrollBar()
        base = self.target if self.anim.state() == QAbstractAnimation.Running else bar.value()
        self.smooth_to(base - e.angleDelta().y() / 120 * round(90 * self.k))
        return True

    def update_down(self):
        """右下角的「回到底部」：不在最底下才显示；翻着看时来了新消息就写上「新消息」。"""
        if self.at_bottom():
            self.new_below = False
            self.down.hide()
            return
        self.down.setText('↓ ' + self.tx['new_below'] if self.new_below else '↓')
        h = round(32 * self.k)
        self.down.setFixedHeight(h)
        self.down.setFixedWidth(max(h, self.down.sizeHint().width() + round(14 * self.k)) if self.new_below else h)
        vp = self.scroll.viewport().geometry()
        self.down.move(vp.right() - self.down.width() - round(10 * self.k), vp.bottom() - h - round(8 * self.k))
        self.down.show()
        self.down.raise_()

    def on_scroll(self, v):
        self.update_down()
        # 滚到顶：再加载一页更早的记录
        if v == 0 and self.more and self.keep_from_bottom is None:
            self.keep_from_bottom = self.scroll.verticalScrollBar().maximum()
            self.show_n += PAGE
            self.refresh()

    def tick_dots(self, step=True):
        if step:
            self.dots = (self.dots + 1) % 3
        self.act.setVisible(bool(self.activity))
        if self.activity:
            self.act.setText(self.tx['activity'].format(what=self.activity) + ' ' + '·' * (self.dots + 1))

    def add_note(self, text):
        n = QLabel(text)
        n.setObjectName('meta')
        n.setWordWrap(True)
        n.setAlignment(Qt.AlignCenter)
        self.list.addWidget(n)

    def add_msg(self, role, text, src=None, pending=False, media=None):
        c = self.t['colors']
        b = Framed(c['rubric'] if role == 'user' else c['gold'], self.k) if self.book else QLabel()
        b.setProperty('role', role)
        b.setProperty('pending', 'true' if pending else 'false')
        imgs = [m['path'] for m in media or [] if m.get('kind') == 'image' and Path(m.get('path', '')).exists()]
        files = [m for m in media or [] if m.get('kind') in ('file', 'dir')]
        chips = [file_chip(m) for m in files]
        if imgs or files:                        # 带附件：文字 + 缩略图 / 文件条，点一下用系统默认程序打开
            w = round(150 * self.k)
            pics = ' '.join(f'<a href="{QUrl.fromLocalFile(p).toString()}"><img src="{QUrl.fromLocalFile(p).toString()}" width="{w}"></a>'
                            for p in imgs)
            body = html.escape(text).replace('\n', '<br>')
            align = 'right' if self.book and role == 'user' else 'left'
            links = '<br>'.join(f'<a href="{QUrl.fromLocalFile(m["path"]).toString()}" style="color:{c["rubric"] if self.book else c["accent"]}">'
                                f'{html.escape(label)}</a>' for m, label in zip(files, chips))
            parts = [x for x in (body, pics, links) if x]
            b.setTextFormat(Qt.RichText)
            b.setText(f'<div align="{align}">{"<br>".join(parts)}'
                      f'{"<br>" + html.escape(self.tx["sending"]) if pending else ""}</div>')
        elif role == 'cc' and (shown := image_paths(text)):   # CC 提到的图片：直接显示在回复下面
            imgs = shown
            w = round(150 * self.k)
            doc = QTextDocument()
            doc.setMarkdown(linkify(text))
            link = self.t['colors']['rubric' if self.book else 'accent']
            body = doc.toHtml().replace('color:#0000ff', f'color:{link}')   # 转 HTML 时写死了默认蓝色，换成主题色
            pics = ' '.join(f'<a href="{QUrl.fromLocalFile(p).toString()}"><img src="{QUrl.fromLocalFile(p).toString()}" width="{w}"></a>'
                            for p in shown)
            b.setTextFormat(Qt.RichText)
            b.setText(body.replace('</body>', f'<p>{pics}</p></body>'))
        else:
            b.setTextFormat(Qt.MarkdownText if role == 'cc' else Qt.PlainText)
            b.setText((linkify(text) if role == 'cc' else text) + ('\n' + self.tx['sending'] if pending else ''))
        b.setWordWrap(True)
        b.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        b.setOpenExternalLinks(True)
        # 能用的宽度：窗口减去书页边距 / 窗口边距、滚动条，她的话再减去头像
        avail = self.width() - ((book.BORDER * 2 + 5 + 32) if self.book else 22) - 22
        if role == 'cc' and self.avatar:
            avail -= self.avatar.width() + 8
        maxw = int(avail * (0.96 if role == 'cc' else 0.85))
        b.setMaximumWidth(maxw)
        # 自动换行的标签会估得太窄：按最长一行的实际宽度给最小宽度（这时样式表还没套上，按样式里的字号自己量）
        f = QFont(QApplication.font())
        f.setPixelSize(round((14 if self.book else 13) * self.k))
        f.setItalic(self.book and role == 'user')
        fm = QFontMetrics(f)
        longest = max((fm.horizontalAdvance(line) for line in text.splitlines() or ['']), default=0)
        if imgs:                                 # 缩略图一行排几张
            longest = max(longest, min(len(imgs), 3) * (round(150 * self.k) + 6))
        if chips:
            longest = max([longest] + [fm.horizontalAdvance(x) for x in chips])
        b.setMinimumWidth(min(int(longest * 1.05) + round(44 * self.k), maxw))   # 加上文字框的内边距和边框，留点余量
        if self.book and role == 'user':
            b.setAlignment(Qt.AlignRight)
        b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(b)
        if role == 'user':
            row.addStretch(1)
            row.addLayout(col)
        else:
            if self.avatar:                      # 她说的话：左边带头像
                a = QLabel()
                a.setPixmap(self.avatar)
                a.setAlignment(Qt.AlignTop)
                row.addWidget(a, 0, Qt.AlignTop)
            row.addLayout(col)
            row.addStretch(1)
        w = QWidget()
        w.setLayout(row)
        self.list.addWidget(w)

    # ---- 选项 ----
    def draw_ask(self, ask):
        qid = ask and ask.get('qid')
        if qid == self.ask_qid:
            return
        self.ask_qid = qid
        while self.ask_box.count():
            it = self.ask_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                while it.layout().count():
                    w = it.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()
        self.ask.setVisible(bool(ask))
        if not ask:
            return
        qs = ask.get('questions', [])
        self.picks = [set() for _ in qs]
        self.groups = []
        single = len(qs) == 1 and not qs[0].get('multiSelect')
        for i, q in enumerate(qs):
            t = QLabel(f"<b>{q.get('header', '')}</b>　{q.get('question', '')}")
            t.setWordWrap(True)
            self.ask_box.addWidget(t)
            btns = []
            for o in q.get('options', []):
                d = o.get('description') or ''
                text = ('❧  ' if self.book and not q.get('multiSelect') else '') + o.get('label', '')
                if q.get('multiSelect'):
                    b = QCheckBox(text)
                    b.toggled.connect(lambda on, i=i, l=o['label']: self.toggle(i, l, on))
                else:
                    b = QPushButton(text)
                    b.setProperty('opt', 'true')
                    b.setCheckable(True)
                    b.setProperty('label', o['label'])
                    b.clicked.connect(lambda _=False, i=i, l=o['label'], s=single: self.choose(i, l, s))
                btns.append(b)
                self.ask_box.addWidget(b)
                if d and d.strip().lower() != o.get('label', '').strip().lower():   # 说明另起一行，能自动换行
                    m = QLabel(d)
                    m.setObjectName('optdesc')
                    m.setWordWrap(True)
                    m.setContentsMargins(26, 0, 4, 4)
                    self.ask_box.addWidget(m)
            self.groups.append(btns)
        row = QHBoxLayout()
        back = QPushButton(self.tx['back_to_terminal'])
        back.clicked.connect(lambda: self.answer(terminal=True))
        row.addWidget(back)
        row.addStretch(1)
        if not single:
            self.ok = QPushButton(self.tx['submit'])
            self.ok.setObjectName('send')
            self.ok.setEnabled(False)
            self.ok.clicked.connect(lambda: self.answer())
            row.addWidget(self.ok)
        self.ask_box.addLayout(row)
        self.qs = qs

    def choose(self, i, label, submit_now):
        self.picks[i] = {label}
        for b in self.groups[i]:
            b.setChecked(b.property('label') == label)
        if submit_now:
            self.answer()
        else:
            self.ok.setEnabled(all(self.picks))

    def toggle(self, i, label, on):
        (self.picks[i].add if on else self.picks[i].discard)(label)
        self.ok.setEnabled(all(self.picks))

    def answer(self, terminal=False):
        if not (self.sid and self.ask_qid):
            return
        if terminal:
            send(self.sid, {'terminal': self.ask_qid})
        else:
            ans = {q['question']: ', '.join(l for o in q.get('options', []) if (l := o['label']) in self.picks[i])
                   for i, q in enumerate(self.qs)}
            send(self.sid, {'answer': {'qid': self.ask_qid, 'answers': ans}})
        self.ask.setEnabled(False)
        QTimer.singleShot(2500, lambda: self.ask.setEnabled(True))

    # ---- 发消息 ----
    def on_send(self):
        text = self.input.text().strip()
        if not (text or self.pending_imgs or self.pending_files) or not self.sid:
            return
        item, notes = {'text': text}, []
        if self.pending_imgs:                    # 图片存到 media/<会话>/，消息里写上路径，CC 用 Read 看
            d = MEDIA / self.sid
            d.mkdir(parents=True, exist_ok=True)
            stamp, paths = int(time.time() * 1000), []
            for i, (img, src) in enumerate(self.pending_imgs):
                if src:
                    dst = d / f'{stamp}-{i}{Path(src).suffix.lower()}'
                    shutil.copyfile(src, dst)
                else:
                    dst = d / f'{stamp}-{i}.png'
                    img.save(str(dst), 'PNG')
                paths.append(str(dst))
            item['media'] = [{'kind': 'image', 'path': p} for p in paths]
            notes.append(self.tx['image_note'].format(n=len(paths), paths='\n'.join(paths)))
            self.pending_imgs = []
        if self.pending_files:                   # 其他文件：不复制，原路径给 CC
            fs = [{'kind': 'dir' if Path(p).is_dir() else 'file', 'path': p, 'name': Path(p).name,
                   'size': 0 if Path(p).is_dir() else Path(p).stat().st_size} for p in self.pending_files if Path(p).exists()]
            item['media'] = item.get('media', []) + fs
            notes.append(self.tx['file_note'].format(n=len(fs), paths='\n'.join(
                f['path'] + ('/（文件夹）' if f['kind'] == 'dir' else f'（{human_size(f["size"])}）') for f in fs)))
            self.pending_files = []
        if notes:
            item['prompt'] = '\n\n'.join(([text] if text else []) + notes)
            self.draw_tray()
        send(self.sid, item)
        self.force_bottom = True                 # 自己发的：回到底部看
        self.input.clear()
        self.refresh()

    # ---- 附件：选、拖、粘贴；图片走图片，其他文件 / 文件夹走文件 ----
    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, '选文件', str(Path.home()))
        for f in files:
            self.add_path(f)

    def add_path(self, p):
        if not p or not Path(p).exists():
            return
        if Path(p).is_file() and Path(p).suffix.lower() in IMAGE_EXT:
            self.add_image(src=p)
        elif p not in self.pending_files:
            self.pending_files.append(p)
            self.draw_tray()

    def add_image(self, img=None, src=None):
        if src and Path(src).suffix.lower() not in IMAGE_EXT:
            return
        if img is None and src:
            img = QImage(src)
        if img is None or img.isNull():
            return
        self.pending_imgs.append((img, src))
        self.draw_tray()

    def draw_tray(self):
        while self.tray_row.count():
            w = self.tray_row.takeAt(0).widget()
            if w:
                w.hide()                         # 先藏起来：deleteLater 要等下一轮事件才删，不然会叠在新卡片下面
                w.deleteLater()
        n = round(54 * self.k)
        for i, (img, _) in enumerate(self.pending_imgs):
            cell = QLabel()
            cell.setPixmap(QPixmap.fromImage(img).scaled(n, n, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation).copy(0, 0, n, n))
            cell.setFixedSize(n, n)
            cell.setObjectName('thumb')
            x = QPushButton('✕', cell)           # 右上角小叉：拿掉这张
            x.setObjectName('unthumb')
            x.setFixedSize(round(18 * self.k), round(18 * self.k))
            x.move(n - x.width(), 0)
            x.setCursor(Qt.PointingHandCursor)
            x.clicked.connect(lambda _=False, i=i: (self.pending_imgs.pop(i), self.draw_tray()))
            self.tray_row.addWidget(cell)
        for i, p in enumerate(self.pending_files):   # 文件：一张小卡片，文件名 + 大小
            q = Path(p)
            m = {'kind': 'dir' if q.is_dir() else 'file', 'name': q.name, 'size': 0 if q.is_dir() else q.stat().st_size}
            cell = QLabel(file_chip(m, short=True))
            cell.setObjectName('filechip')
            cell.setFixedHeight(n)
            cell.setToolTip(p)
            x = QPushButton('✕', cell)
            x.setObjectName('unthumb')
            x.setFixedSize(round(18 * self.k), round(18 * self.k))
            cell.adjustSize()
            cell.setFixedWidth(min(max(cell.sizeHint().width() + x.width(), n * 2), n * 4))
            x.move(cell.width() - x.width(), 0)
            x.setCursor(Qt.PointingHandCursor)
            x.clicked.connect(lambda _=False, i=i: (self.pending_files.pop(i), self.draw_tray()))
            self.tray_row.addWidget(cell)
        self.tray_row.addStretch(1)
        self.tray.setVisible(bool(self.pending_imgs or self.pending_files))

    def eventFilter(self, obj, e):
        if obj is self.scroll.viewport() and e.type() == QEvent.Wheel:
            return self.wheel(e)
        if obj is self.input and e.type() == QEvent.KeyPress and e.matches(QKeySequence.Paste):
            md = QApplication.clipboard().mimeData()
            if md.hasImage():                    # 剪贴板里是截图
                self.add_image(img=QImage(md.imageData()))
                return True
            files = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            if files:                            # 在文件管理器里复制的文件
                for f in files:
                    self.add_path(f)
                return True
        return super().eventFilter(obj, e)

    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasImage() or any(u.isLocalFile() for u in md.urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        files = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        for f in files:
            self.add_path(f)
        if not files and md.hasImage():
            self.add_image(img=QImage(md.imageData()))
        e.acceptProposedAction()

    # ---- 书页外观：画背景、标题；拖封面移动 ----
    def paintEvent(self, e):
        if not self.book:
            return super().paintEvent(e)
        if self.cover is None or self.cover.size() != self.size():
            self.cover = book.cover(self.width(), self.height(), self.t['colors'], bool(self.tx['title']))
        p = QPainter(self)
        p.drawImage(0, 0, self.cover)
        p.setRenderHint(QPainter.TextAntialiasing)
        pr = book.page_rect(self.width(), self.height())
        f = QFont(QApplication.font())
        f.setPixelSize(round(20 * self.k))
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 6)
        p.setFont(f)
        p.setPen(QColor(self.t['colors']['rubric']))
        top = 34 if self.tx['title'] else 0         # 没有标题：花饰线和会话名往上提
        if self.tx['title']:
            p.drawText(QRectF(pr.left(), pr.top() + 8, pr.width(), 30), Qt.AlignCenter, self.tx['title'])
        if self.subtitle:
            f.setPixelSize(round(11 * self.k))
            f.setBold(False)
            f.setItalic(True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 1)
            p.setFont(f)
            p.setPen(QColor(self.t['colors']['muted']))
            p.drawText(QRectF(pr.left(), pr.top() + 26 + top, pr.width(), 16), Qt.AlignCenter, self.subtitle)

    def resizeEvent(self, e):
        if self.book:
            pr = book.page_rect(self.width(), self.height())
            self.close_btn.setGeometry(int(pr.right()) - 28, int(pr.top()) + 6, 22, 22)
        super().resizeEvent(e)

    def mousePressEvent(self, e):
        if self.book and e.button() == Qt.LeftButton:
            self.drag_from = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self.book and self.drag_from is not None:
            self.move(e.globalPosition().toPoint() - self.drag_from)

    def mouseReleaseEvent(self, e):
        if self.book:
            self.drag_from = None

    # ---- 打开 ----
    def open_near(self, pet=None):
        """在桌宠旁边打开：放得下就放左边，否则右边。"""
        pet = pet or getattr(self, 'pet', None)
        if pet is not None and not self.isVisible():
            self.pet = pet
            g = (pet.screen() or QGuiApplication.primaryScreen()).availableGeometry()
            x = pet.x() - self.width() - 8
            if x < g.left():
                x = pet.x() + pet.width() + 8
            y = min(max(g.top(), pet.y() + pet.height() - self.height()), g.bottom() - self.height())
            self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
        self.unread = False
        self.shown_key = None
        self.refresh()
