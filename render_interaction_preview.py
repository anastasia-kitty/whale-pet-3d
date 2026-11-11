# -*- coding: utf-8 -*-
"""
重新生成互动效果预览图 interaction_preview.png（开发用）。

运行：
    $env:QT_QPA_PLATFORM="offscreen"
    $env:QT_QPA_FONTDIR="C:\\Windows\\Fonts"
    .\\.venv\\Scripts\\python.exe render_interaction_preview.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ["WHALE_PET_DATA_DIR"] = tempfile.mkdtemp(prefix="whale-bar-preview-")

from PyQt5.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from whale_pet_3d import WhalePet  # noqa: E402

COLS = 3
ROWS = 2
CELL_W = 410
CELL_H = 440
CANVAS_W = 1230
CANVAS_H = 880
PET_SIZE = 340


def grab(pet: WhalePet) -> QImage:
    pet.repaint()
    image = pet.grab().toImage()
    return image


def draw_title(painter: QPainter, text: str, center_x: float, top: float) -> None:
    font = QFont("Microsoft YaHei UI", 13)
    font.setStyleStrategy(QFont.PreferAntialias)
    font.setWeight(QFont.DemiBold)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    width = metrics.horizontalAdvance(text) + 34.0
    height = 38.0
    rect = QRectF(center_x - width / 2.0, top, width, height)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 238))
    painter.drawRoundedRect(rect, height / 2.0, height / 2.0)
    painter.setPen(QColor(59, 70, 104))
    painter.drawText(rect, Qt.AlignCenter, text)


def main() -> None:
    app = QApplication([])
    pet = WhalePet()
    pet.show()
    QTest.qWait(200)
    pet._hide_hint()

    shots = []

    # 1. 悬停操作条
    pet._hover_inside = True
    pet._bar_alpha = 1.0
    pet.update()
    QTest.qWait(80)
    shots.append(("悬停操作条", grab(pet)))
    pet._hover_inside = False
    pet._bar_alpha = 0.0

    # 2. 拍拍
    pet._trigger_effect("pat")
    QTest.qWait(320)
    shots.append(("拍拍", grab(pet)))
    QTest.qWait(1300)

    # 3. 喂鱼：小鱼干下落
    pet._trigger_effect("feed")
    QTest.qWait(340)
    shots.append(("喂鱼 · 小鱼干", grab(pet)))
    # 4. 喂鱼：tokens 气泡
    QTest.qWait(700)
    shots.append(("喂鱼 · tokens 气泡", grab(pet)))
    QTest.qWait(2700)

    # 5. 喷水
    pet._trigger_effect("spray")
    QTest.qWait(700)
    shots.append(("喷水", grab(pet)))
    QTest.qWait(2600)

    # 6. 转圈
    pet._trigger_effect("spin")
    QTest.qWait(460)
    shots.append(("转圈 · 水平转身", grab(pet)))
    QTest.qWait(1200)

    canvas = QImage(CANVAS_W, CANVAS_H, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(QColor("#EAF0FB"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    for index, (title, image) in enumerate(shots):
        col = index % COLS
        row = index // COLS
        cell_x = col * CELL_W
        cell_y = row * CELL_H
        draw_title(painter, title, cell_x + CELL_W / 2.0, cell_y + 18.0)
        target = QRectF(
            cell_x + (CELL_W - PET_SIZE) / 2.0,
            cell_y + 66.0,
            PET_SIZE,
            PET_SIZE,
        )
        painter.drawImage(target, image)

    painter.end()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "interaction_preview.png")
    canvas.save(path)
    print(path)

    pet.close()


if __name__ == "__main__":
    main()
