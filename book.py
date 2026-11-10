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

    # ---- 页角藤蔓花饰（右上角有书签和关闭键，留白）----
    gold.setAlpha(210)
    for x, y, sx, sy in ((pr.left() + 7, pr.top() + 7, 1, 1), (pr.left() + 7, pr.bottom() - 7, 1, -1),
                         (pr.right() - 7, pr.bottom() - 7, -1, -1)):
        corner(p, x, y, sx, sy, gold)

    # ---- 页顶花饰线 ----
    flourish(p, pr.center().x(), pr.top() + (50 if titled else 18), pr.width() / 2 - 58, gold, QColor(c['rubric']))
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


def curl(path, x, y, r, down):
    """在 (x, y) 结尾打一个小卷：先向外再卷回来。down 为 1 向下卷，-1 向上卷。"""
    path.cubicTo(QPointF(x + r * 1.2, y), QPointF(x + r * 1.4, y + down * r * 1.3), QPointF(x + r * 0.4, y + down * r * 1.4))
    path.cubicTo(QPointF(x - r * 0.2, y + down * r * 1.4), QPointF(x - r * 0.3, y + down * r * 0.6), QPointF(x + r * 0.3, y + down * r * 0.6))


def corner(p, x, y, sx, sy, gold, scale=1.0):
    """页角花饰：沿两条边各一道细线，末端打卷，拐角处一片叶子和几个小圆点。sx / sy 决定朝哪个角。"""
    p.save()
    p.translate(x, y)
    p.scale(sx * scale, sy * scale)
    pen = QPen(gold, 1.2 / scale)
    pen.setCapStyle(Qt.RoundCap)
    for transpose in (False, True):              # 横一道、竖一道（竖的就是横的沿对角线翻过去）
        p.save()
        if transpose:
            p.rotate(90)
            p.scale(1, -1)
        path = QPainterPath(QPointF(4, 0))
        path.lineTo(QPointF(38, 0))
        curl(path, 38, 0, 5, 1)
        path.moveTo(QPointF(10, 4))               # 里面再一道短的
        path.cubicTo(QPointF(16, 4), QPointF(20, 6), QPointF(22, 11))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(gold)
        p.drawEllipse(QPointF(28, 5), 1.3, 1.3)
        p.restore()
    leaf = QPainterPath(QPointF(3, 3))           # 拐角一片叶子
    leaf.quadTo(QPointF(17, 4), QPointF(16, 16))
    leaf.quadTo(QPointF(4, 17), QPointF(3, 3))
    fill = QColor(gold)
    fill.setAlpha(90)
    p.setPen(pen)
    p.setBrush(fill)
    p.drawPath(leaf)
    p.setPen(QPen(gold, 0.8 / scale))
    p.drawLine(QPointF(4, 4), QPointF(13, 13))   # 叶脉
    p.restore()


def flourish(p, cx, y, half, gold, rubric, cross_r=6):
    """横向花饰带：两边细线从外往里渐显，靠近中间各打一对小卷，正中一个十字。"""
    p.save()
    for side in (-1, 1):
        x_out, x_in = cx + side * half, cx + side * (cross_r + 22)
        g = QLinearGradient(x_out, y, x_in, y)
        c0 = QColor(gold)
        c0.setAlpha(0)
        g.setColorAt(0, c0)
        g.setColorAt(1, gold)
        p.setPen(QPen(QBrush(g), 1))
        p.drawLine(QPointF(x_out, y), QPointF(x_in, y))
        pen = QPen(gold, 1.1)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for down in (1, -1):                     # 上下一对小卷，朝外
            path = QPainterPath(QPointF(x_in, y))
            path.cubicTo(QPointF(x_in - side * 6, y), QPointF(x_in - side * 8, y + down * 2), QPointF(x_in - side * 12, y + down * 5))
            path.cubicTo(QPointF(x_in - side * 15, y + down * 7), QPointF(x_in - side * 9, y + down * 9), QPointF(x_in - side * 8, y + down * 6))
            p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(gold)
        p.drawEllipse(QPointF(x_in + side * 4, y), 1.4, 1.4)
    cross(p, QPointF(cx, y), cross_r, rubric)
    p.restore()


def divider(width, gold, rubric):
    """对话之间的小花饰（窄一点的花饰带）。"""
    h = 18
    pix = QPixmap(int(width), h)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    flourish(p, width / 2, h / 2, width / 2 - 2, QColor(gold), QColor(rubric), cross_r=4)
    p.end()
    return pix


def frame_ornaments(p, r, color, k=1.0):
    """文字框的装饰：右下角一簇小藤蔓，左上角一个小角括，下边中间一粒小点。r 是边框矩形。"""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    c.setAlpha(210)
    corner(p, r.right() - 3, r.bottom() - 3, -1, -1, c, 0.42 * k)
    pen = QPen(c, 1.1)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    n = 9 * k
    x, y = r.left() + 3, r.top() + 3
    p.drawLine(QPointF(x, y + n), QPointF(x, y))
    p.drawLine(QPointF(x, y), QPointF(x + n, y))
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(x + 3 * k, y + 3 * k), 1.2 * k, 1.2 * k)
    p.drawEllipse(QPointF(r.center().x(), r.bottom()), 1.6 * k, 1.6 * k)
    p.restore()


def clip_icon(size, color):
    """回形针。"""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), size / 13)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.translate(size / 2, size / 2)
    p.rotate(40)
    s = size / 22
    path = QPainterPath(QPointF(2 * s, 4 * s))            # 一笔画：内弯 → 外圈 → 收尾
    path.lineTo(QPointF(2 * s, -5 * s))
    path.arcTo(QRectF(-4 * s, -8 * s, 6 * s, 6 * s), 0, 180)
    path.lineTo(QPointF(-4 * s, 6 * s))
    path.arcTo(QRectF(-4 * s, 2 * s, 8 * s, 8 * s), 180, 180)
    path.lineTo(QPointF(4 * s, -7 * s))
    p.drawPath(path)
    p.end()
    return pix
