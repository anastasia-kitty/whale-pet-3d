# -*- coding: utf-8 -*-
"""
小鲸鱼互动特效。

特效全部画在现有 3D 画面的上层，不重新生成 3D 网格：
  - 拍拍：眯眼 + 爱心
  - 喂鱼：小鱼干落下 + 点头 + tokens 气泡
  - 喷水：头顶浅蓝色水珠喷泉
"""

from __future__ import annotations

import math
import random
import time
from typing import Dict, List, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF

EFFECT_DURATIONS = {
    "pat": 1.40,
    "feed": 3.40,
    "spray": 3.00,
}

PINK = (255, 115, 160)
LIGHT_PINK = (255, 180, 205)
FISH_YELLOW = (255, 209, 92)
FISH_OUTLINE = (219, 158, 51)
WATER = (184, 237, 255)
BLACK = (5, 6, 10)
FACE_BLUE = (84, 96, 255)


def _smoothstep(a: float, b: float, x: float) -> float:
    if a == b:
        return 0.0 if x < a else 1.0
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


class WhaleEffects:
    def __init__(self) -> None:
        self.name = None  # type: str
        self.start = 0.0
        self.duration = 0.0
        self._spray_particles = []  # type: List[Tuple[float, float, float, float, float, float]]

    @property
    def active(self) -> bool:
        return self.name is not None

    def trigger(self, name: str, now: float = None) -> bool:
        if self.active or name not in EFFECT_DURATIONS:
            return False
        if now is None:
            now = time.monotonic()
        self.name = name
        self.start = now
        self.duration = EFFECT_DURATIONS[name]
        self._spray_particles = []
        if name == "spray":
            self._make_spray(now)
        return True

    def tick(self, now: float) -> bool:
        if self.active and now - self.start >= self.duration:
            self.reset()
            return False
        return self.active

    def reset(self) -> None:
        self.name = None
        self.start = 0.0
        self.duration = 0.0
        self._spray_particles = []

    def nod_offset(self, now: float) -> float:
        """喂鱼时小鲸鱼轻轻点头，返回屏幕 y 偏移。"""
        if self.name != "feed":
            return 0.0
        t = now - self.start
        if 0.62 <= t <= 1.18:
            return math.sin(math.pi * (t - 0.62) / 0.56) * 6.0
        return 0.0

    # ------------------------------------------------------------------
    # 绘制入口
    # ------------------------------------------------------------------
    def draw(
        self,
        painter: QPainter,
        anchors: Dict[str, Tuple[float, float]],
        y_shift: float,
        now: float,
    ) -> None:
        if not self.active:
            return
        elapsed = now - self.start
        if elapsed < 0.0 or elapsed > self.duration:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self.name == "pat":
            self._draw_pat(painter, anchors, y_shift, elapsed)
        elif self.name == "feed":
            self._draw_feed(painter, anchors, y_shift, elapsed)
        elif self.name == "spray":
            self._draw_spray(painter, anchors, y_shift, elapsed)
        painter.restore()

    # ------------------------------------------------------------------
    # 拍一拍
    # ------------------------------------------------------------------
    def _draw_pat(self, painter, anchors, y_shift, t) -> None:
        squint = _smoothstep(0.0, 0.16, t) * (1.0 - _smoothstep(0.95, 1.30, t))
        if squint > 0.01:
            eye_r = max(5.0, anchors["eye_radius"][0])
            for key in ("eye_left", "eye_right"):
                x, y = anchors[key]
                y += y_shift
                # 盖住原来的黑色圆眼，再画一条弯弯的闭眼线
                painter.setPen(Qt.NoPen)
                painter.setBrush(
                    QColor(FACE_BLUE[0], FACE_BLUE[1], FACE_BLUE[2], int(255 * squint))
                )
                painter.drawEllipse(
                    QPointF(x, y),
                    eye_r * 1.35,
                    eye_r * 1.45,
                )
                pen = QPen(
                    QColor(BLACK[0], BLACK[1], BLACK[2], int(255 * squint)),
                    max(2.2, eye_r * 0.42),
                )
                pen.setCapStyle(Qt.RoundCap)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                path = QPainterPath()
                path.moveTo(x - eye_r * 0.72, y + 2.0)
                path.quadTo(x, y - eye_r * 0.62, x + eye_r * 0.72, y + 2.0)
                painter.drawPath(path)

        # 头顶爱心
        origin_x, origin_y = anchors["head_top"]
        origin_y += y_shift
        hearts = (
            (-45.0, 0.00, 11.0),
            (-25.0, 0.07, 14.0),
            (0.0, 0.11, 16.0),
            (25.0, 0.04, 14.0),
            (45.0, 0.12, 11.0),
        )
        for dx, delay, size in hearts:
            age = t - delay
            if age <= 0.0:
                continue
            life = 1.22
            if age > life:
                continue
            p = age / life
            alpha = min(1.0, age / 0.12) * (1.0 - _smoothstep(0.62, 1.0, p))
            x = origin_x + dx + math.sin(age * 6.0 + dx) * 4.0
            y = origin_y - 16.0 - 70.0 * p
            draw_size = size * (1.0 - 0.16 * p)
            # 柔光底
            self._draw_heart(
                painter,
                x,
                y,
                draw_size * 1.55,
                QColor(PINK[0], PINK[1], PINK[2], int(55 * alpha)),
                QColor(LIGHT_PINK[0], LIGHT_PINK[1], LIGHT_PINK[2], 0),
            )
            self._draw_heart(
                painter,
                x,
                y,
                draw_size,
                QColor(PINK[0], PINK[1], PINK[2], int(235 * alpha)),
                QColor(LIGHT_PINK[0], LIGHT_PINK[1], LIGHT_PINK[2], int(150 * alpha)),
            )

    def _draw_heart(self, painter, x, y, size, fill, highlight) -> None:
        path = QPainterPath()
        path.moveTo(x, y + size * 0.34)
        path.cubicTo(
            x - size * 0.92,
            y - size * 0.20,
            x - size * 0.54,
            y - size * 0.88,
            x,
            y - size * 0.34,
        )
        path.cubicTo(
            x + size * 0.54,
            y - size * 0.88,
            x + size * 0.92,
            y - size * 0.20,
            x,
            y + size * 0.34,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawPath(path)
        painter.setBrush(highlight)
        painter.drawEllipse(
            QPointF(x - size * 0.25, y - size * 0.22),
            size * 0.16,
            size * 0.12,
        )

    # ------------------------------------------------------------------
    # 喂饭
    # ------------------------------------------------------------------
    def _draw_feed(self, painter, anchors, y_shift, t) -> None:
        mouth_x, mouth_y = anchors["mouth"]
        mouth_y += y_shift - 7.0

        if t < 0.72:
            u = min(1.0, t / 0.72)
            x = mouth_x + math.sin(u * math.pi) * 5.0
            y = -28.0 + (mouth_y + 28.0) * (u * u)
            self._draw_fish(painter, x, y, 12.0 + 16.0 * u, 1.0)

        # 气泡在鱼落到嘴边后出现
        if t >= 0.72:
            alpha = _smoothstep(0.72, 0.90, t)
            alpha *= 1.0 - _smoothstep(3.00, 3.36, t)
            if alpha > 0.01:
                self._draw_feed_bubble(
                    painter,
                    anchors["head_top"],
                    y_shift,
                    alpha,
                )

    def _draw_fish(self, painter, x, y, angle, scale) -> None:
        painter.save()
        painter.translate(x, y)
        painter.rotate(angle)
        painter.scale(scale, scale)

        painter.setPen(QPen(QColor(*FISH_OUTLINE), 1.3))
        painter.setBrush(QColor(*FISH_YELLOW))
        # 鱼身
        painter.drawEllipse(QPointF(-2.0, 0.0), 13.0, 7.0)
        # 鱼尾
        tail = QPolygonF(
            [
                QPointF(8.0, 0.0),
                QPointF(18.0, -7.0),
                QPointF(16.0, 0.0),
                QPointF(18.0, 7.0),
            ]
        )
        painter.drawPolygon(tail)
        # 眼睛和鱼鳍
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(70, 60, 45))
        painter.drawEllipse(QPointF(-9.5, -2.0), 1.6, 1.6)
        painter.setPen(QPen(QColor(*FISH_OUTLINE), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(QRectF(-8.0, 1.0, 9.0, 7.0), 200 * 16, 130 * 16)
        painter.restore()

    def _draw_feed_bubble(self, painter, head_top, y_shift, alpha) -> None:
        hx, hy = head_top
        hy += y_shift
        box = QRectF(65.0, 22.0, 270.0, 56.0)
        tail = QPolygonF(
            [
                QPointF(hx - 7.0, box.bottom() - 1.0),
                QPointF(hx + 7.0, box.bottom() - 1.0),
                QPointF(hx, hy - 8.0),
            ]
        )

        painter.setPen(QPen(QColor(89, 255, 255, int(225 * alpha)), 1.4))
        painter.setBrush(QColor(255, 255, 255, int(242 * alpha)))
        painter.drawRoundedRect(box, 14.0, 14.0)
        painter.drawPolygon(tail)

        font = QFont("Microsoft YaHei UI", 9)
        font.setStyleStrategy(QFont.PreferAntialias)
        painter.setFont(font)
        painter.setPen(QColor(61, 72, 112, int(248 * alpha)))
        painter.drawText(
            box,
            Qt.AlignCenter,
            "tokens + 1M💗\n感谢投喂！",
        )

    # ------------------------------------------------------------------
    # 喷水
    # ------------------------------------------------------------------
    def _make_spray(self, now: float) -> None:
        rng = random.Random(int(now * 1000.0) & 0x7FFFFFFF)
        particles = []
        for _ in range(78):
            delay = rng.uniform(0.0, 2.25)
            vx = rng.uniform(-46.0, 46.0)
            vy = rng.uniform(-270.0, -150.0)
            life = rng.uniform(0.72, 1.12)
            size = rng.uniform(3.0, 6.2)
            phase = rng.uniform(0.0, math.tau)
            particles.append((delay, vx, vy, life, size, phase))
        self._spray_particles = particles

    def _draw_spray(self, painter, anchors, y_shift, t) -> None:
        x0, y0 = anchors["blowhole"]
        y0 += y_shift
        # 水柱根部的青色光晕和小水花
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(WATER[0], WATER[1], WATER[2], 46))
        painter.drawEllipse(QPointF(x0, y0 - 4.0), 16.0, 10.0)
        painter.setBrush(QColor(WATER[0], WATER[1], WATER[2], 155))
        painter.drawEllipse(QPointF(x0, y0), 11.0, 4.0)

        for delay, vx, vy, life, size, phase in self._spray_particles:
            age = t - delay
            if age < 0.0 or age > life:
                continue
            p = age / life
            x = x0 + vx * age + math.sin(phase + age * 8.0) * 2.8
            y = y0 + vy * age + 0.5 * 360.0 * age * age
            alpha = int(225 * (1.0 - p))
            if alpha <= 0:
                continue
            painter.setBrush(QColor(WATER[0], WATER[1], WATER[2], alpha))
            painter.drawEllipse(QPointF(x, y), size, size * 1.15)
            if size > 4.0:
                painter.setBrush(QColor(255, 255, 255, int(alpha * 0.8)))
                painter.drawEllipse(
                    QPointF(x - size * 0.3, y - size * 0.35),
                    size * 0.28,
                    size * 0.28,
                )
