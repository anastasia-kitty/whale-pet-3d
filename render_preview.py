# -*- coding: utf-8 -*-
"""把桌宠形象渲染成 PNG，方便在不开窗口的情况下预览。"""

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

from whale_pet import DESIGN_H, DESIGN_W, paint_whale


def render_transparent(path, scale=2):
    image = QImage(
        DESIGN_W * scale, DESIGN_H * scale, QImage.Format_ARGB32_Premultiplied
    )
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.scale(scale, scale)
    paint_whale(painter, QRectF(0, 0, DESIGN_W, DESIGN_H), phase=0.0)
    painter.end()
    image.save(path)


def _rounded_rect(painter, rect, radius, color):
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(rect, radius, radius)


def _line(painter, x, y, width, height=8, color=QColor("#D7E2FA")):
    _rounded_rect(
        painter,
        QRectF(x, y, width, height),
        height / 2.0,
        color,
    )


def render_on_background(path, width=1200, height=800):
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("#EAF2FF"))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)

    background = QLinearGradient(QPointF(0, 0), QPointF(0, height))
    background.setColorAt(0.0, QColor("#F8FBFF"))
    background.setColorAt(0.55, QColor("#E8F0FF"))
    background.setColorAt(1.0, QColor("#D6E4FF"))
    painter.fillRect(0, 0, width, height, background)

    # 背景里的柔和光斑
    glow = QRadialGradient(QPointF(930, 300), 330)
    glow.setColorAt(0.0, QColor(255, 255, 255, 150))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(glow)
    painter.drawEllipse(QPointF(930, 300), 330, 330)

    # 后面的窗口：代码编辑器
    shadow = QRectF(86, 104, 646, 390)
    _rounded_rect(painter, shadow.translated(0, 10), 20, QColor(70, 96, 165, 24))
    _rounded_rect(painter, QRectF(80, 96, 646, 390), 20, QColor(255, 255, 255, 236))

    # 标题栏
    painter.save()
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(80, 96, 646, 390), 20, 20)
    painter.setClipPath(clip)
    painter.fillRect(QRectF(80, 96, 646, 40), QColor(246, 249, 255))
    painter.restore()
    for i, color in enumerate(("#FF9AA2", "#FFD59A", "#9AE6B4")):
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(104 + i * 18, 116), 5, 5)

    # 左侧栏
    _rounded_rect(painter, QRectF(96, 152, 126, 318), 12, QColor("#F3F7FF"))
    _line(painter, 112, 174, 76, 8, QColor("#C8D7F7"))
    for i in range(5):
        _line(painter, 112, 208 + i * 28, 70 - (i % 3) * 12, 7, QColor("#DCE7FB"))

    # 代码行
    widths = [250, 330, 210, 380, 290, 340, 190, 300, 260, 360, 220]
    colors = ["#C9D8F8", "#DDE7FB", "#C9D8F8", "#DDE7FB"]
    for i, w in enumerate(widths):
        _line(
            painter,
            250,
            170 + i * 26,
            w,
            7,
            QColor(colors[i % len(colors)]),
        )
    _line(painter, 250, 170, 60, 7, QColor("#8FA8E8"))
    _line(painter, 320, 170, 120, 7, QColor("#B9CDF3"))

    # 前面的窗口：浏览器 / 资料卡
    shadow2 = QRectF(608, 278, 534, 330)
    _rounded_rect(painter, shadow2.translated(0, 12), 20, QColor(70, 96, 165, 26))
    _rounded_rect(painter, QRectF(602, 270, 534, 330), 20, QColor(255, 255, 255, 242))
    painter.save()
    clip2 = QPainterPath()
    clip2.addRoundedRect(QRectF(602, 270, 534, 330), 20, 20)
    painter.setClipPath(clip2)
    painter.fillRect(QRectF(602, 270, 534, 38), QColor(246, 249, 255))
    painter.restore()
    _rounded_rect(painter, QRectF(620, 286, 110, 7), 3.5, QColor("#C8D7F7"))
    _rounded_rect(painter, QRectF(746, 286, 60, 7), 3.5, QColor("#E1EAFB"))

    hero = QLinearGradient(QPointF(622, 330), QPointF(1114, 470))
    hero.setColorAt(0.0, QColor("#E4EDFF"))
    hero.setColorAt(1.0, QColor("#F7FAFF"))
    _rounded_rect(painter, QRectF(622, 330, 492, 150), 12, QColor("#EAF1FF"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(hero)
    painter.drawRoundedRect(QRectF(630, 338, 476, 134), 10, 10)
    _line(painter, 622, 502, 310, 8, QColor("#D7E2FA"))
    _line(painter, 622, 522, 230, 8, QColor("#E1EAFB"))
    _line(painter, 622, 542, 350, 8, QColor("#E1EAFB"))

    # 任务栏
    painter.fillRect(QRectF(0, height - 56, width, 56), QColor(255, 255, 255, 238))
    painter.setPen(QColor(207, 220, 244))
    painter.drawLine(0, height - 56, width, height - 56)

    # 开始按钮
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#5460FF"))
    for row in range(2):
        for col in range(2):
            painter.drawRoundedRect(
                QRectF(22 + col * 10, height - 38 + row * 10, 7, 7), 2, 2
            )

    # 搜索框（用图形代替文字，避免离屏渲染依赖字体）
    _rounded_rect(
        painter, QRectF(66, height - 43, 210, 30), 15, QColor(240, 245, 255)
    )
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QColor("#9AA9CC"))
    painter.drawEllipse(QPointF(86, height - 28), 6, 6)
    painter.drawLine(
        QPointF(90.5, height - 23.5), QPointF(95, height - 19)
    )
    _line(painter, 108, height - 30, 62, 5, QColor("#DDE7FB"))

    # 任务栏图标
    for i, color in enumerate(("#FFD59A", "#9AE6B4", "#B9CDF3")):
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(
            QRectF(310 + i * 36, height - 42, 22, 22), 6, 6
        )

    # 时钟图标
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QColor("#59678C"))
    painter.drawEllipse(QPointF(width - 48, height - 28), 8, 8)
    painter.drawLine(
        QPointF(width - 48, height - 32), QPointF(width - 48, height - 28)
    )
    painter.drawLine(
        QPointF(width - 48, height - 28), QPointF(width - 44, height - 26)
    )

    # 桌宠本体
    pet_w = 320
    pet_h = pet_w * DESIGN_H / DESIGN_W
    pet_x = width - pet_w - 24
    pet_y = height - 56 - pet_h - 14
    glow2 = QRadialGradient(
        QPointF(pet_x + pet_w * 0.48, pet_y + pet_h * 0.68), pet_w * 0.55
    )
    glow2.setColorAt(0.0, QColor(255, 255, 255, 145))
    glow2.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(glow2)
    painter.drawEllipse(
        QPointF(pet_x + pet_w * 0.48, pet_y + pet_h * 0.68),
        pet_w * 0.55,
        pet_w * 0.55,
    )
    paint_whale(painter, QRectF(pet_x, pet_y, pet_w, pet_h), phase=0.0)

    painter.end()
    image.save(path)


def main():
    app = QApplication(sys.argv)  # noqa: F841
    base = os.path.dirname(os.path.abspath(__file__))
    render_transparent(os.path.join(base, "whale_preview.png"))
    render_on_background(os.path.join(base, "preview.png"))
    print("saved: whale_preview.png, preview.png")


if __name__ == "__main__":
    main()
