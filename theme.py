"""形象主题：themes/<id>/theme.json + 素材。换形象就是加一个目录。

选哪个：环境变量 DESK_PET_THEME > ~/.config/desk-pet/theme（托盘「形象」菜单写的）> sheep-nun。
theme.json 里没写的字段用下面的默认值；DESK_PET_ASSETS 仍可直接指定素材目录。
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
THEMES = ROOT / 'themes'
CHOICE = Path.home() / '.config/desk-pet/theme'
DEFAULT_ID = 'sheep-nun'

DEFAULT = {
    'name': '桌宠',
    'assets': 'assets',
    'font': '',
    'avatar': None,                 # [x, y, 边长]：从默认姿态图里裁头像；不写就不显示头像
    'colors': {
        'bg': '#e7ebf0', 'panel': '#ffffff', 'ink': '#222222', 'muted': '#8a929a', 'border': '#c9d3dd',
        'accent': '#3d8ee6', 'accent_ink': '#ffffff', 'gold': '#5c9ded',
        'user_bg': '#d7f5c4', 'user_ink': '#1d2a18', 'pet_bg': '#ffffff', 'pet_ink': '#222222',
        'warn_bg': '#fff3cd', 'warn_ink': '#6b5200',
        'bubble_bg': '#ffffff', 'bubble_ink': '#333333', 'bubble_border': '#00000032',
    },
    'text': {
        'title': '和 CC 聊天', 'placeholder': '发给 CC…（回车发送）',
        'empty': '还没有消息。在下面输入发给 CC，或在终端里正常聊天，这里会同步显示。',
        'send': '发送', 'submit': '提交', 'back_to_terminal': '回终端答', 'from_terminal': '在终端里发的',
        'sending': '（发送中…）', 'perm': '终端里在等你批准：{tool}（权限只能在终端里点）',
        'new_reply': '有新回复，点我看', 'no_session': '没有开 /desk-pet 的会话：在 CC 里输入 /desk-pet',
    },
}


def available():
    """[(id, 名字)]"""
    out = []
    for d in sorted(THEMES.glob('*/theme.json')):
        try:
            out.append((d.parent.name, json.loads(d.read_text(encoding='utf-8')).get('name', d.parent.name)))
        except (OSError, ValueError):
            pass
    return out


def current_id():
    want = os.environ.get('DESK_PET_THEME')
    if not want:
        try:
            want = CHOICE.read_text().strip()
        except OSError:
            want = ''
    ids = [i for i, _ in available()]
    return want if want in ids else (DEFAULT_ID if DEFAULT_ID in ids else (ids[0] if ids else DEFAULT_ID))


def choose(theme_id):
    CHOICE.parent.mkdir(parents=True, exist_ok=True)
    CHOICE.write_text(theme_id)


def load(theme_id=None):
    theme_id = theme_id or current_id()
    d = THEMES / theme_id
    try:
        raw = json.loads((d / 'theme.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raw = {}
    t = {**DEFAULT, **raw, 'id': theme_id}
    t['colors'] = {**DEFAULT['colors'], **raw.get('colors', {})}
    t['text'] = {**DEFAULT['text'], **raw.get('text', {})}
    t['assets'] = Path(os.environ.get('DESK_PET_ASSETS') or d / t['assets'])
    return t
