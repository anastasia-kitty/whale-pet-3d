# -*- coding: utf-8 -*-
"""生成 3D 桌宠的预览图（开发 / README 用，不需要打开桌面窗口）。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QRadialGradient,
)
from PyQt5.QtWidgets import QApplication

from whale3d import draw_shadow, get_renderer


def _rounded(painter, rect, radius, color):
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(rect, radius, radius)


def _line(painter, x, y, width, height=7, color=QColor("#D7E2FA")):
    _rounded(
        painter,
        QRectF(x, y, width, height),
        height / 2.0,
        color,
    )


def render_pet(
    size=400,
    scale=2,
    yaw=0.0,
    pitch=1.5,
    zoom=1.04,
):
    """返回带阴影的透明小鲸鱼图（物理分辨率为 size * scale）。"""
    px = int(size * scale)
    image = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    draw_shadow(painter, px)
    whale = get_renderer().render(
        px,
        yaw,
        pitch,
        zoom,
        dpr=1.0,
    )
    painter.drawImage(0, 0, whale)
    painter.end()
    return image


def _desktop_background(painter, width, height):
    gradient = QLinearGradient(QPointF(0, 0), QPointF(width, height))
    gradient.setColorAt(0.0, QColor("#F8FBFF"))
    gradient.setColorAt(0.55, QColor("#E8F1FF"))
    gradient.setColorAt(1.0, QColor("#D5E3FF"))
    painter.fillRect(0, 0, width, height, gradient)

    glow = QRadialGradient(QPointF(width * 0.78, height * 0.28), width * 0.42)
    glow.setColorAt(0.0, QColor(255, 255, 255, 150))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(glow)
    painter.drawEllipse(
        QPointF(width * 0.78, height * 0.28),
        width * 0.42,
        width * 0.42,
    )

    glow2 = QRadialGradient(QPointF(width * 0.22, height * 0.82), width * 0.32)
    glow2.setColorAt(0.0, QColor(160, 190, 255, 65))
    glow2.setColorAt(1.0, QColor(160, 190, 255, 0))
    painter.setBrush(glow2)
    painter.drawEllipse(
        QPointF(width * 0.22, height * 0.82),
        width * 0.32,
        width * 0.32,
    )


def _draw_editor(painter, x, y, w, h):
    _rounded(painter, QRectF(x + 4, y + 12, w, h), 20, QColor(43, 65, 120, 24))
    _rounded(painter, QRectF(x, y, w, h), 20, QColor(255, 255, 255, 242))

    clip = QPainterPath()
    clip.addRoundedRect(QRectF(x, y, w, h), 20, 20)
    painter.save()
    painter.setClipPath(clip)
    painter.fillRect(QRectF(x, y, w, 40), QColor(246, 249, 255))

    for i, color in enumerate(("#FF9AA2", "#FFD59A", "#9AE6B4")):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(x + 24 + i * 17, y + 20), 5, 5)

    # 左侧栏
    _rounded(
        painter,
        QRectF(x + 16, y + 56, 132, h - 72),
        12,
        QColor("#F3F7FF"),
    )
    _line(painter, x + 32, y + 78, 76, 8, QColor("#B9CDF3"))
    for i in range(6):
        _line(
            painter,
            x + 32,
            y + 112 + i * 27,
            74 - (i % 3) * 13,
            7,
            QColor("#DCE7FB"),
        )

    # 代码区
    widths = [250, 330, 195, 360, 270, 320, 180, 300, 245, 345, 210, 280]
    colors = ["#C9D8F8", "#DDE7FB", "#C9D8F8", "#DDE7FB"]
    for i, line_w in enumerate(widths):
        _line(
            painter,
            x + 178,
            y + 82 + i * 28,
            line_w,
            7,
            QColor(colors[i % len(colors)]),
        )

    # 行号
    for i in range(12):
        _line(painter, x + 164, y + 83 + i * 28, 7, 5, QColor("#C4D3F1"))

    # 代码高亮块
    _line(painter, x + 178, y + 82, 55, 7, QColor("#9BB2E9"))
    _line(painter, x + 241, y + 82, 105, 7, QColor("#B8CDF3"))

    painter.restore()


def _draw_card(painter, x, y, w, h):
    _rounded(painter, QRectF(x + 4, y + 12, w, h), 20, QColor(43, 65, 120, 22))
    _rounded(painter, QRectF(x, y, w, h), 20, QColor(255, 255, 255, 244))

    clip = QPainterPath()
    clip.addRoundedRect(QRectF(x, y, w, h), 20, 20)
    painter.save()
    painter.setClipPath(clip)
    header = QLinearGradient(QPointF(x, y), QPointF(x + w, y + 130))
    header.setColorAt(0.0, QColor("#5460FF"))
    header.setColorAt(1.0, QColor("#8E9BFF"))
    painter.fillRect(QRectF(x, y, w, 130), header)

    glow = QRadialGradient(QPointF(x + w * 0.78, y + 48), 150)
    glow.setColorAt(0.0, QColor(255, 255, 255, 105))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(glow)
    painter.drawEllipse(QPointF(x + w * 0.78, y + 48), 150, 150)

    painter.setBrush(QColor(255, 255, 255, 242))
    painter.drawEllipse(QPointF(x + 56, y + 62), 24, 24)
    painter.setBrush(QColor("#59FFFF"))
    painter.drawEllipse(QPointF(x + 56, y + 62), 15, 15)
    painter.restore()

    _line(painter, x + 28, y + 158, 210, 9, QColor("#C9D8F8"))
    _line(painter, x + 28, y + 181, 150, 8, QColor("#DCE7FB"))
    for i in range(4):
        _line(
            painter,
            x + 28,
            y + 224 + i * 24,
            390 - (i % 3) * 55,
            7,
            QColor("#E0E9FB"),
        )

    # 一个蓝色的小按钮
    _rounded(painter, QRectF(x + 28, y + h - 58, 112, 30), 15, QColor("#EEF1FF"))
    _line(painter, x + 48, y + h - 47, 72, 8, QColor("#9DABE8"))


def _draw_taskbar(painter, width, height):
    bar_h = 62
    painter.fillRect(
        QRectF(0, height - bar_h, width, bar_h),
        QColor(255, 255, 255, 234),
    )
    painter.setPen(QColor(208, 220, 244))
    painter.drawLine(0, height - bar_h, width, height - bar_h)

    # 开始按钮
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#5460FF"))
    for row in range(2):
        for col in range(2):
            painter.drawRoundedRect(
                QRectF(
                    24 + col * 10,
                    height - 38 + row * 10,
                    7,
                    7,
                ),
                2,
                2,
            )

    # 搜索框
    _rounded(
        painter,
        QRectF(66, height - 45, 230, 32),
        16,
        QColor(240, 245, 255),
    )
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QColor("#9AA9CC"))
    painter.drawEllipse(QPointF(86, height - 29), 6, 6)
    painter.drawLine(QPointF(90.5, height - 24.5), QPointF(95, height - 20))
    _line(painter, 108, height - 31, 72, 5, QColor("#DDE7FB"))

    # 任务栏图标
    for i, color in enumerate(("#FFD59A", "#9AE6B4", "#B9CDF3", "#FFC2D1")):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(
            QRectF(330 + i * 38, height - 44, 25, 25),
            7,
            7,
        )
    painter.setBrush(QColor("#5460FF"))
    painter.drawRoundedRect(QRectF(482, height - 44, 25, 25), 7, 7)

    # 时钟
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QColor("#59678C"))
    painter.drawEllipse(QPointF(width - 50, height - 30), 8, 8)
    painter.drawLine(QPointF(width - 50, height - 34), QPointF(width - 50, height - 30))
    painter.drawLine(
        QPointF(width - 50, height - 30),
        QPointF(width - 46, height - 28),
    )


def render_desktop(path, width=1280, height=800):
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("#EAF2FF"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    _desktop_background(painter, width, height)
    _draw_editor(painter, 62, 76, 660, 500)
    _draw_card(painter, 650, 230, 500, 360)
    _draw_taskbar(painter, width, height)

    # 小鲸鱼身后的柔光
    pet_size = 400
    pet_x = width - pet_size - 18
    pet_y = height - 62 - pet_size - 2
    glow = QRadialGradient(
        QPointF(pet_x + pet_size * 0.52, pet_y + pet_size * 0.55),
        pet_size * 0.55,
    )
    glow.setColorAt(0.0, QColor(255, 255, 255, 170))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(glow)
    painter.drawEllipse(
        QPointF(pet_x + pet_size * 0.52, pet_y + pet_size * 0.55),
        pet_size * 0.55,
        pet_size * 0.55,
    )

    pet = render_pet(size=pet_size, scale=2)
    painter.drawImage(
        QRectF(pet_x, pet_y, pet_size, pet_size),
        pet,
    )

    painter.end()
    image.save(path)
    return image


def render_views(path, width=1680, height=460):
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("#EAF2FF"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    gradient = QLinearGradient(QPointF(0, 0), QPointF(0, height))
    gradient.setColorAt(0.0, QColor("#F8FBFF"))
    gradient.setColorAt(1.0, QColor("#E1EBFF"))
    painter.fillRect(0, 0, width, height, gradient)

    angles = [
        (0.0, 1.5),
        (-52.0, 8.0),
        (72.0, 3.0),
        (166.0, 3.0),
    ]
    size = 410
    gap = (width - size * 4) / 5.0
    for i, (yaw, pitch) in enumerate(angles):
        x = gap + i * (size + gap)
        y = (height - size) / 2.0
        pet = render_pet(size=size, scale=2, yaw=yaw, pitch=pitch, zoom=1.04)
        painter.drawImage(QRectF(x, y, size, size), pet)

    painter.end()
    image.save(path)
    return image


def main():
    app = QApplication(sys.argv)  # noqa: F841
    base = os.path.dirname(os.path.abspath(__file__))

    transparent = QImage(800, 800, QImage.Format_ARGB32_Premultiplied)
    transparent.fill(Qt.transparent)
    p = QPainter(transparent)
    p.setRenderHint(QPainter.Antialiasing, True)
    draw_shadow(p, 800)
    p.drawImage(
        0,
        0,
        get_renderer().render(800, 0.0, 1.5, 1.04, dpr=1.0),
    )
    p.end()
    transparent.save(os.path.join(base, "whale_3d_transparent.png"))

    render_desktop(os.path.join(base, "preview_3d.png"))
    render_views(os.path.join(base, "whale_3d_views.png"))
    print("saved: preview_3d.png, whale_3d_views.png, whale_3d_transparent.png")


if __name__ == "__main__":
    main()
