"""桌宠的聊天小窗：给开了 /desk-pet 的 CC 会话发消息、看回复、点选项回答提问。

和 cc-mod 之间用文件传话（都在 ~/.cache/desk-pet/chat/）：
  <会话id>.in.json   桌宠写：{msgs: [{id, text} | {id, answer: {qid, answers}} | {id, terminal: qid}]}
  <会话id>.out.json  mod 写：{ack, log: [{id, role, text, src, ts}], ask: {qid, questions} | null, perm: 工具名 | null}
权限确认只能在终端里点，这里只提醒。
"""
import json
import os
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

CHAT = Path.home() / '.cache/desk-pet/chat'
STATE_LABEL = {'working': '工作中', 'reading': '查看中', 'waiting': '等你回复', 'done': '完成啦', 'error': '出错了', 'idle': '空闲'}

def style(t):
    """按主题配色生成样式表；每个控件都写明颜色，不吃系统深色主题。"""
    c = t['colors']
    font = f"QWidget#chat, QWidget#chat * {{ font-family: '{t['font']}'; }}" if t['font'] else ''
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
"""


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


class ChatWindow(QWidget):
    def __init__(self, theme, neutral):
        super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint)
        self.t, self.tx = theme, theme['text']
        self.setObjectName('chat')
        self.setWindowTitle(self.tx['title'])
        self.setStyleSheet(style(theme))
        self.avatar = round_avatar(neutral, theme['avatar']) if theme.get('avatar') and not neutral.isNull() else None
        self.resize(420, 680)
        self.sessions = []           # [(sid, cwd, state)]
        self.sid = None
        self.shown_key = None        # 上次画的内容，没变就不重画
        self.ask_qid = None
        self.seen = {}               # sid -> 看过的最后一条 CC 回复 id
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
        bottom.addWidget(self.input, 1)
        bottom.addWidget(self.btn)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.perm)
        lay.addWidget(self.scroll, 1)
        lay.addWidget(self.ask)
        lay.addLayout(bottom)

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
        title = self.tx['title']
        self.setWindowTitle(f'{title} · {self.label(sessions[ids.index(self.sid)])}' if self.sid in ids else title)
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
        self.shown_key = None
        self.refresh()

    # ---- 画对话 ----
    def refresh(self):
        if not self.sid:
            self.draw([], None, None, [])
            return
        out = read_json(CHAT / f'{self.sid}.out.json') or {}
        ack = out.get('ack', 0)
        pending = [m for m in (read_json(CHAT / f'{self.sid}.in.json') or {}).get('msgs', [])
                   if m.get('id', 0) > ack and m.get('text')]
        self.draw(out.get('log', []), out.get('ask'), out.get('perm'), pending)
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
        self.shown_key = key
        while self.list.count() > 1:
            w = self.list.takeAt(1).widget()
            if w:
                w.deleteLater()
        if not log and not pending:
            self.add_note(self.tx['empty'])
        for e in log:
            self.add_msg(e['role'], e['text'], src=e.get('src'))
        for m in pending:
            self.add_msg('user', m['text'], pending=True)
        self.draw_ask(ask)
        bar = self.scroll.verticalScrollBar()       # 等布局排好再滚到底
        QTimer.singleShot(60, lambda: bar.setValue(bar.maximum()))

    def add_note(self, text):
        n = QLabel(text)
        n.setObjectName('meta')
        n.setWordWrap(True)
        n.setAlignment(Qt.AlignCenter)
        self.list.addWidget(n)

    def add_msg(self, role, text, src=None, pending=False):
        b = QLabel()
        b.setProperty('role', role)
        b.setProperty('pending', 'true' if pending else 'false')
        b.setTextFormat(Qt.MarkdownText if role == 'cc' else Qt.PlainText)
        b.setText(text + ('\n' + self.tx['sending'] if pending else ''))
        b.setWordWrap(True)
        b.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        b.setOpenExternalLinks(True)
        b.setMaximumWidth(int(self.width() * 0.8))
        b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        col = QVBoxLayout()
        col.setSpacing(1)
        if role == 'user' and src == 'terminal':
            m = QLabel(self.tx['from_terminal'])
            m.setObjectName('meta')
            m.setAlignment(Qt.AlignRight)
            col.addWidget(m)
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
                text = o.get('label', '') + (f'\n{d}' if d and d.strip().lower() != o.get('label', '').strip().lower() else '')
                if q.get('multiSelect'):
                    b = QCheckBox(text)
                    b.toggled.connect(lambda on, i=i, l=o['label']: self.toggle(i, l, on))
                else:
                    b = QPushButton(text)
                    b.setProperty('opt', 'true')
                    b.setCheckable(True)
                    b.clicked.connect(lambda _=False, i=i, l=o['label'], s=single: self.choose(i, l, s))
                btns.append(b)
                self.ask_box.addWidget(b)
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
            b.setChecked(b.text().split('\n')[0] == label)
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
        if not text or not self.sid:
            return
        send(self.sid, {'text': text})
        self.input.clear()
        self.refresh()

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
