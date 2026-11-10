"""书页外观：厚皮封面 + 烫金压线 + 烫金书口 + 羊皮纸页 + 书签丝带。

主题 theme.json 里 "look": "book" 时聊天窗用它画背景；颜色取主题的 colors：
leather / leather_dark（皮面）、page / page_shade（纸）、page_edge（书口）、gold（烫金）、rubric（朱红标题）。
"""
import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QRadialGradient)

BORDER = 22          # 皮面露出来的宽度


def header(titled):
    """页顶留白：有标题时放标题 + 花饰线 + 会话名，没标题只放花饰线 + 会话名。"""
    return 84 if titled else 50


def noise(size, alpha, seed, light=False):
    """一块可平铺的颗粒纹理：皮革毛孔 / 纸纤维。"""
    rnd = random.Random(seed)
    img = QImage(size, size, QImage.Format_ARGB32)
    for y in range(size):
        for x in range(size):
            v = rnd.randint(200, 255) if light else rnd.randint(0, 60)
            img.setPixel(x, y, (rnd.randint(0, alpha) << 24) | (v << 16) | (v << 8) | v)
    return QPixmap.fromImage(img)


def page_rect(w, h):
    return QRectF(BORDER, BORDER, w - 2 * BORDER - 5, h - 2 * BORDER - 5)   # 右下留出书口厚度


def cover(w, h, c, titled=True):
    """画整张静态背景，缓存成图；窗口大小变了才重画。"""
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    rnd = random.Random(7)
    whole = QRectF(0.5, 0.5, w - 1, h - 1)

    # ---- 皮面 ----
    leather = QPainterPath()
    leather.addRoundedRect(whole, 14, 14)
    p.setClipPath(leather)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor(c['leather']))
    g.setColorAt(1, QColor(c['leather_dark']))
    p.fillPath(leather, g)
    for _ in range(int(w * h / 900)):            # 皮纹：一些深浅斑
        r = rnd.uniform(2, 9)
        col = QColor(0, 0, 0, rnd.randint(8, 26)) if rnd.random() < 0.6 else QColor(255, 220, 170, rnd.randint(4, 12))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(rnd.uniform(0, w), rnd.uniform(0, h)), r, r * rnd.uniform(0.5, 1))
    p.fillPath(leather, QBrush(noise(96, 70, 1)))
    v = QRadialGradient(w * 0.42, h * 0.38, max(w, h) * 0.8)   # 边角磨旧发暗，左上一点光
    v.setColorAt(0, QColor(255, 225, 180, 22))
    v.setColorAt(0.55, QColor(0, 0, 0, 0))
    v.setColorAt(1, QColor(0, 0, 0, 150))
    p.fillPath(leather, v)

    # ---- 烫金压线 + 四角花饰 ----
    gold = QColor(c['gold'])
    for inset, a, wdt in ((6, 200, 1.4), (10, 140, 0.8)):
        gold.setAlpha(a)
        p.setPen(QPen(gold, wdt))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(whole.adjusted(inset, inset, -inset, -inset), 11 - inset / 3, 11 - inset / 3)
    gold.setAlpha(220)
    for cx, cy in ((13, 13), (w - 13, 13), (13, h - 13), (w - 13, h - 13)):
        p.setPen(Qt.NoPen)
        p.setBrush(gold)
        p.drawPolygon(QPolygonF([QPointF(cx, cy - 4), QPointF(cx + 4, cy), QPointF(cx, cy + 4), QPointF(cx - 4, cy)]))
    p.setClipping(False)

    # ---- 书口：几层纸边，烫金 ----
    pr = page_rect(w, h)
    for i in range(5, 0, -1):
        edge = QColor(c['page_edge']).lighter(100 + (i % 2) * 14)
        p.setPen(Qt.NoPen)
        p.setBrush(edge)
        p.drawRoundedRect(pr.translated(i, i), 3, 3)

    # ---- 纸页 ----
    page = QPainterPath()
    page.addRoundedRect(pr, 3, 3)
    g = QLinearGradient(pr.left(), 0, pr.right(), 0)   # 左边靠书脊，暗一点、带弧度
    g.setColorAt(0, QColor(c['page_shade']))
    g.setColorAt(0.07, QColor(c['page']))
    g.setColorAt(0.93, QColor(c['page']))
    g.setColorAt(1, QColor(c['page_shade']))
    p.fillPath(page, g)
    p.fillPath(page, QBrush(noise(128, 26, 2, light=False)))
    v = QRadialGradient(pr.center(), max(pr.width(), pr.height()) * 0.75)   # 纸边泛黄
    v.setColorAt(0.6, QColor(0, 0, 0, 0))
    v.setColorAt(1, QColor(120, 80, 30, 70))
    p.fillPath(page, v)
    p.setPen(QPen(QColor(90, 60, 30, 90), 1))
    p.setBrush(Qt.NoBrush)
    p.drawPath(page)

    # ---- 书签丝带：从封面顶上垂下来，末端燕尾 ----
    rib = QColor(c['rubric'])
    x0, x1, bottom = pr.right() - 64, pr.right() - 50, pr.top() + 58
    tail = QPolygonF([QPointF(x0, 0), QPointF(x1, 0), QPointF(x1, bottom), QPointF((x0 + x1) / 2, bottom - 7), QPointF(x0, bottom)])
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 70))
    p.drawPolygon(tail.translated(2, 2))
    g = QLinearGradient(x0, 0, x1, 0)
    g.setColorAt(0, rib.darker(130))
    g.setColorAt(0.5, rib.lighter(115))
    g.setColorAt(1, rib.darker(140))
    p.setBrush(g)
    p.drawPolygon(tail)

    # ---- 标题下的花饰线：—— ✠ —— ----
    y = pr.top() + (50 if titled else 16)
    cx = pr.center().x()
    gold.setAlpha(200)
    p.setPen(QPen(gold, 1))
    p.drawLine(QPointF(pr.left() + 34, y), QPointF(cx - 16, y))
    p.drawLine(QPointF(cx + 16, y), QPointF(pr.right() - 34, y))
    for sx in (pr.left() + 34, pr.right() - 34):
        p.setBrush(gold)
        p.drawEllipse(QPointF(sx, y), 1.6, 1.6)
    cross(p, QPointF(cx, y), 6, QColor(c['rubric']))
    p.end()
    return img


def cross(p, at, r, color):
    """耶路撒冷十字式的小十字：四臂末端带横。"""
    p.save()
    p.setPen(QPen(color, 1.6, Qt.SolidLine, Qt.FlatCap))
    x, y = at.x(), at.y()
    p.drawLine(QPointF(x - r, y), QPointF(x + r, y))
    p.drawLine(QPointF(x, y - r), QPointF(x, y + r))
    for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r)):
        k = r * 0.45
        if dx:
            p.drawLine(QPointF(x + dx, y - k), QPointF(x + dx, y + k))
        else:
            p.drawLine(QPointF(x - k, y + dy), QPointF(x + k, y + dy))
    p.restore()


def ring_avatar(pix, color):
    """头像外加一圈金边，像书里的圆形肖像框。"""
    s = pix.width() + 4
    out = QPixmap(s, s)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.drawPixmap(2, 2, pix)
    p.setPen(QPen(QColor(color), 1.5))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(1, 1, s - 2, s - 2))
    p.end()
    return out


def seal_icon(size, color):
    """火漆印上压的十字。"""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    cross(p, QPointF(size / 2, size / 2), size * 0.36, QColor(color))
    p.end()
    return pix
