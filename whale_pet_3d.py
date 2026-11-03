# -*- coding: utf-8 -*-
"""
DeepSeek 小鲸鱼桌宠 · 3D 版

运行：
    python whale_pet_3d.py

特点：
    · 真正的 3D 网格（不是贴图 / 序列帧），可以旋转查看各个角度
    · 纯 PyQt5 + QPainter 软件渲染，不需要 OpenGL、numpy 或模型文件
    · 透明背景、右下角启动、始终置顶、无任务栏图标
    · 支持拍拍、喂鱼、喷水、转圈四种互动

操作：
    · 鼠标移入：显示拍拍 / 喂鱼 / 喷水 / 转圈操作条
    · 左键拖动：旋转小鲸鱼
    · 右键拖动 / Shift+左键拖动：移动桌宠
    · 滚轮：缩放
    · 双击：回到初始视角
    · 右键单击：菜单（互动 / 自动旋转 / 复位 / 回右下角 / 退出）
"""

from __future__ import annotations

import math
import sys
import time

from PyQt5.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

from whale3d import draw_shadow, face_anchors, get_renderer
from whale_effects import WhaleEffects

# ---------------------------------------------------------------------------
# 可调参数
# ---------------------------------------------------------------------------
PET_SIZE = 400                 # 桌宠窗口边长（逻辑像素）
SCREEN_MARGIN = 24             # 离屏幕右下角的距离
INITIAL_YAW = 0.0              # 初始水平角度：0 = 正对镜头，左右眼斑完全对称
INITIAL_PITCH = 1.5            # 初始俯仰角度
INITIAL_ZOOM = 1.04
MIN_PITCH = -58.0
MAX_PITCH = 68.0
MIN_ZOOM = 0.72
MAX_ZOOM = 1.45
YAW_PER_PIXEL = 0.50           # 左键拖动 1 像素转多少度
PITCH_PER_PIXEL = 0.32
IDLE_BOB = True                # 待机时轻轻上下浮动
SHOW_HINT = True               # 第一次出现时显示操作提示
HINT_SECONDS = 5.0
AUTO_SPIN_SPEED = 0.75         # 自动旋转速度（度 / 帧）

# 拖动时用稍低一点的分辨率渲染，松手后恢复到全分辨率
DRAG_RENDER_SCALE = 0.84

# 悬停操作条
ACTION_LABELS = (
    ("pat", "拍拍"),
    ("feed", "喂鱼"),
    ("spray", "喷水"),
    ("spin", "转圈"),
)
ACTION_BAR_TOP = 5.0
ACTION_BAR_HEIGHT = 28.0
ACTION_BAR_CHIP_WIDTH = 64.0
ACTION_BAR_GAP = 8.0
ACTION_HIDE_DELAY = 1.0        # 鼠标移开后，操作条再停留 1 秒


class WhalePet(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(PET_SIZE, PET_SIZE)
        self.setCursor(Qt.OpenHandCursor)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setMouseTracking(True)

        self._renderer = get_renderer()
        self._effects = WhaleEffects()
        self._clock = QElapsedTimer()
        self._clock.start()

        self._hover_inside = False
        self._hover_action = None
        self._bar_alpha = 0.0
        self._actions_grace_until = 0.0
        self._button_pressed = False
        self._spin_frames = []
        self._spin_key = None
        self._spin_duration = 1.35

        self._yaw = INITIAL_YAW
        self._pitch = INITIAL_PITCH
        self._zoom = INITIAL_ZOOM

        self._mode = None                 # "rotate" / "move"
        self._move_offset = QPoint(0, 0)
        self._last_global = QPoint(0, 0)
        self._press_global = QPoint(0, 0)
        self._right_moved = False
        self._dragging = False

        self._auto_spin = False
        self._hint_started = time.monotonic()
        self._hint_until = (
            self._hint_started + HINT_SECONDS if SHOW_HINT else 0.0
        )

        self._timer = QTimer(self)
        self._timer.setInterval(33)       # 约 30 FPS；待机时只重绘缓存，很轻
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(420)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

        self._place_bottom_right()

    # ------------------------------------------------------------------
    # 位置 / 窗口
    # ------------------------------------------------------------------
    def _place_bottom_right(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = area.right() - self.width() - SCREEN_MARGIN + 1
        y = area.bottom() - self.height() - SCREEN_MARGIN + 1
        self.move(x, y)
        self.raise_()

    def _ensure_on_screen(self) -> None:
        """不让小鲸鱼被完全拖出屏幕。"""
        frame = self.frameGeometry()
        for screen in QApplication.screens():
            if screen.availableGeometry().intersects(frame):
                return
        self._place_bottom_right()

    # ------------------------------------------------------------------
    # 动画 / 绘制
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        now = time.monotonic()
        need_update = False
        was_spin = self._effects.name == "spin"
        if self._auto_spin and not self._dragging and not was_spin:
            self._yaw = (self._yaw + AUTO_SPIN_SPEED) % 360.0
            need_update = True
        if IDLE_BOB and not self._dragging and not self._auto_spin:
            need_update = True
        if now < self._hint_until:
            need_update = True

        was_active = self._effects.active
        if self._effects.tick(now):
            need_update = True
        elif was_active:
            need_update = True

        bar_allowed = self._hover_inside or now < self._actions_grace_until
        target = 1.0 if (bar_allowed and not self._effects.active) else 0.0
        if abs(self._bar_alpha - target) > 0.01:
            self._bar_alpha += (target - self._bar_alpha) * 0.28
            if abs(self._bar_alpha - target) < 0.02:
                self._bar_alpha = target
            need_update = True
        if not bar_allowed and self._bar_alpha <= 0.01:
            self._actions_grace_until = 0.0

        if need_update:
            self.update()

    def _render_size(self) -> int:
        if self._dragging and self._mode == "rotate":
            return max(200, int(round(PET_SIZE * DRAG_RENDER_SCALE)))
        return PET_SIZE

    def _current_image(self):
        dpr = max(1.0, float(self.devicePixelRatioF()))
        size = self._render_size()
        return self._renderer.render(
            size,
            self._yaw,
            self._pitch,
            self._zoom,
            dpr=dpr,
        ), size

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        draw_shadow(painter, PET_SIZE)

        image, render_size = self._current_image()
        now = time.monotonic()
        bob = 0.0
        if IDLE_BOB and not self._dragging:
            phase = self._clock.elapsed() / 1000.0
            bob = math.sin(phase * math.tau / 4.6) * 1.7
        nod = self._effects.nod_offset(now)
        y_shift = bob + nod

        if self._effects.name == "spin" and self._spin_frames:
            progress = (now - self._effects.start) / self._spin_duration
            progress = max(0.0, min(1.0, progress))
            index = min(
                len(self._spin_frames) - 1,
                int(progress * len(self._spin_frames)),
            )
            hop = -8.0 * math.sin(math.pi * progress)
            target = QRectF(
                0.0,
                y_shift + hop,
                float(PET_SIZE),
                float(PET_SIZE),
            )
            painter.drawImage(target, self._spin_frames[index])
        else:
            target = QRectF(0.0, y_shift, float(PET_SIZE), float(PET_SIZE))
            painter.drawImage(target, image)

        anchors = face_anchors(
            PET_SIZE,
            self._yaw,
            self._pitch,
            self._zoom,
        )
        self._effects.draw(painter, anchors, y_shift, now)

        self._draw_hint(painter)
        self._draw_action_bar(painter)
        painter.end()

    def _draw_hint(self, painter: QPainter) -> None:
        now = time.monotonic()
        if now >= self._hint_until:
            return
        remaining = self._hint_until - now
        # 最后 0.8 秒淡出
        alpha = min(1.0, remaining / 0.8)
        alpha = max(0.0, alpha)

        text = "左键旋转 · 右键移动 · 悬停出现互动按钮"
        font = QFont("Microsoft YaHei UI", 8)
        font.setStyleStrategy(QFont.PreferAntialias)
        metrics = QFontMetrics(font)
        text_w = metrics.horizontalAdvance(text)
        pad_x = 13.0
        box_w = text_w + pad_x * 2.0
        box_h = 25.0
        box = QRectF(
            (PET_SIZE - box_w) / 2.0,
            7.0,
            box_w,
            box_h,
        )

        painter.save()
        # 小气泡尾巴
        pointer = QPolygonF(
            [
                QPointF(PET_SIZE / 2.0 - 5.0, box.bottom() - 0.5),
                QPointF(PET_SIZE / 2.0 + 5.0, box.bottom() - 0.5),
                QPointF(PET_SIZE / 2.0, box.bottom() + 6.0),
            ]
        )
        border = QPen(QColor(89, 255, 255, int(205 * alpha)))
        border.setWidthF(1.2)
        border.setJoinStyle(Qt.RoundJoin)
        painter.setPen(border)
        painter.setBrush(QColor(255, 255, 255, int(234 * alpha)))
        painter.drawRoundedRect(box, box_h / 2.0, box_h / 2.0)
        painter.drawPolygon(pointer)
        painter.setFont(font)
        painter.setPen(QColor(61, 72, 112, int(245 * alpha)))
        painter.drawText(box, Qt.AlignCenter, text)
        painter.restore()

    # ------------------------------------------------------------------
    # 悬停操作条
    # ------------------------------------------------------------------
    def _action_layout(self):
        total = (
            ACTION_BAR_CHIP_WIDTH * len(ACTION_LABELS)
            + ACTION_BAR_GAP * (len(ACTION_LABELS) - 1)
        )
        x = (PET_SIZE - total) / 2.0
        result = []
        for name, label in ACTION_LABELS:
            rect = QRectF(
                x,
                ACTION_BAR_TOP,
                ACTION_BAR_CHIP_WIDTH,
                ACTION_BAR_HEIGHT,
            )
            result.append((name, label, rect))
            x += ACTION_BAR_CHIP_WIDTH + ACTION_BAR_GAP
        return result

    def _action_at(self, pos) -> str:
        if self._effects.active or self._bar_alpha < 0.35:
            return None
        point = QPointF(pos)
        for name, _label, rect in self._action_layout():
            if rect.contains(point):
                return name
        return None

    def _draw_action_bar(self, painter: QPainter) -> None:
        if self._bar_alpha <= 0.01 or self._effects.active:
            return

        alpha = max(0.0, min(1.0, self._bar_alpha))
        font = QFont("Microsoft YaHei UI", 9)
        font.setStyleStrategy(QFont.PreferAntialias)
        painter.save()
        painter.setOpacity(alpha)
        painter.setFont(font)
        for name, label, rect in self._action_layout():
            hovered = name == self._hover_action
            fill = QColor(238, 241, 255, 244) if hovered else QColor(255, 255, 255, 232)
            border = QColor(89, 255, 255, 225)
            pen = QPen(border, 1.2)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, rect.height() / 2.0, rect.height() / 2.0)
            painter.setPen(QColor(59, 70, 104, 245))
            painter.drawText(rect, Qt.AlignCenter, label)
        painter.restore()

    # ------------------------------------------------------------------
    # 互动
    # ------------------------------------------------------------------
    def _build_spin_frames(self) -> None:
        """把当前视角的缓存图预渲染成 36 帧转圈动画。"""
        image, _render_size = self._current_image()
        dpr = max(1.0, float(image.devicePixelRatio()))
        key = (
            round(self._yaw, 1),
            round(self._pitch, 1),
            round(self._zoom, 3),
            round(dpr, 2),
        )
        if self._spin_key == key and self._spin_frames:
            return
        px = max(2, int(round(PET_SIZE * dpr)))
        count = 36
        frames = []
        for i in range(count):
            u = i / float(count - 1)
            ease = u * u * (3.0 - 2.0 * u)
            angle = 360.0 * ease
            frame = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
            frame.setDevicePixelRatio(dpr)
            frame.fill(Qt.transparent)

            p = QPainter(frame)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)

            def draw_at(deg: float, opacity: float) -> None:
                p.save()
                p.setOpacity(opacity)
                p.translate(PET_SIZE * 0.5, PET_SIZE * 0.5)
                p.rotate(deg)
                p.scale(0.91, 0.91)
                p.translate(-PET_SIZE * 0.5, -PET_SIZE * 0.5)
                p.drawImage(
                    QRectF(0.0, 0.0, float(PET_SIZE), float(PET_SIZE)),
                    image,
                )
                p.restore()

            # 一点点残影，让转圈更有速度感
            draw_at(angle - 9.0, 0.16)
            draw_at(angle, 1.0)
            p.end()
            frames.append(frame)
        self._spin_frames = frames
        self._spin_key = key

    def _trigger_effect(self, name: str) -> None:
        if name == "spin":
            if self._effects.active:
                return
            self._build_spin_frames()
            if not self._effects.trigger("spin"):
                return
        else:
            if not self._effects.trigger(name):
                return
        self._hide_hint()
        self._button_pressed = False
        self._hover_action = None
        self.update()

    def _update_hover_action(self, pos) -> None:
        action = self._action_at(pos)
        if action != self._hover_action:
            self._hover_action = action
            self.update()
        if action:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.OpenHandCursor)

    # ------------------------------------------------------------------
    # 鼠标操作
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        self._hide_hint()
        if self._effects.name == "spin" and event.button() == Qt.LeftButton:
            event.accept()
            return
        self._press_global = event.globalPos()
        self._last_global = event.globalPos()
        self._right_moved = False
        self._button_pressed = False

        if event.button() == Qt.LeftButton:
            action = self._action_at(event.pos())
            if action:
                self._button_pressed = True
                self._trigger_effect(action)
                event.accept()
                return
            if event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier):
                self._start_move(event.globalPos())
            else:
                self._mode = "rotate"
                self._dragging = True
                self.setCursor(Qt.ClosedHandCursor)
                self.raise_()
            event.accept()
            return

        if event.button() in (Qt.RightButton, Qt.MiddleButton):
            self._start_move(event.globalPos())
            event.accept()
            return

        super().mousePressEvent(event)

    def _start_move(self, global_pos: QPoint) -> None:
        self._mode = "move"
        self._dragging = True
        self._move_offset = global_pos - self.frameGeometry().topLeft()
        self.setCursor(Qt.SizeAllCursor)
        self.raise_()

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            self._update_hover_action(event.pos())
            super().mouseMoveEvent(event)
            return

        pos = event.globalPos()
        if self._mode == "rotate" and event.buttons() & Qt.LeftButton:
            dx = pos.x() - self._last_global.x()
            dy = pos.y() - self._last_global.y()
            self._yaw = (self._yaw + dx * YAW_PER_PIXEL) % 360.0
            self._pitch = min(
                MAX_PITCH,
                max(MIN_PITCH, self._pitch + dy * PITCH_PER_PIXEL),
            )
            self._last_global = pos
            self.update()
            event.accept()
            return

        if self._mode == "move":
            if (pos - self._press_global).manhattanLength() > 3:
                self._right_moved = True
            self.move(pos - self._move_offset)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._button_pressed:
            self._button_pressed = False
            self._mode = None
            self._dragging = False
            self._update_hover_action(event.pos())
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._mode == "rotate":
            self._mode = None
            self._dragging = False
            self.setCursor(Qt.OpenHandCursor)
            self._ensure_on_screen()
            self.update()
            event.accept()
            return

        if event.button() in (Qt.RightButton, Qt.MiddleButton):
            was_moving = self._mode == "move"
            moved = self._right_moved
            self._mode = None
            self._dragging = False
            self.setCursor(Qt.OpenHandCursor)
            self._ensure_on_screen()
            self.update()
            event.accept()
            if event.button() == Qt.RightButton and was_moving and not moved:
                self._show_menu(event.globalPos())
            return

        if event.button() == Qt.LeftButton and self._mode == "move":
            self._mode = None
            self._dragging = False
            self.setCursor(Qt.OpenHandCursor)
            self._ensure_on_screen()
            self.update()
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self._effects.name != "spin":
                self._reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        self._hide_hint()
        if self._effects.name == "spin":
            event.accept()
            return
        steps = event.angleDelta().y() / 120.0
        if abs(steps) > 0.01:
            self._zoom = min(
                MAX_ZOOM,
                max(MIN_ZOOM, self._zoom * (1.10 ** steps)),
            )
            self.update()
        event.accept()

    def enterEvent(self, event) -> None:
        self._hover_inside = True
        self._actions_grace_until = 0.0
        self._hide_hint()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_inside = False
        self._hover_action = None
        self._actions_grace_until = time.monotonic() + ACTION_HIDE_DELAY
        if not self._dragging:
            self.setCursor(Qt.OpenHandCursor)
        self.update()
        super().leaveEvent(event)

    def _hide_hint(self) -> None:
        self._hint_until = 0.0

    def _reset_view(self) -> None:
        self._yaw = INITIAL_YAW
        self._pitch = INITIAL_PITCH
        self._zoom = INITIAL_ZOOM
        self._auto_spin = False
        self.update()

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------
    def _show_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background: #FFFFFF;
                color: #3B4668;
                border: 2px solid #59FFFF;
                border-radius: 9px;
                padding: 6px 8px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 7px 28px 7px 14px;
                border-radius: 5px;
            }
            QMenu::item:selected {
                background: #EEF1FF;
                color: #5460FF;
            }
            QMenu::separator {
                height: 1px;
                background: #DDE6FF;
                margin: 5px 8px;
            }
            """
        )

        effect_actions = {
            menu.addAction("拍拍"): "pat",
            menu.addAction("喂鱼"): "feed",
            menu.addAction("喷水"): "spray",
            menu.addAction("转圈"): "spin",
        }
        menu.addSeparator()
        spin_action = menu.addAction("自动旋转展示")
        spin_action.setCheckable(True)
        spin_action.setChecked(self._auto_spin)
        reset_action = menu.addAction("重置视角")
        menu.addSeparator()
        back_action = menu.addAction("回到右下角")
        menu.addSeparator()
        quit_action = menu.addAction("退出小鲸鱼")

        chosen = menu.exec_(global_pos)
        if chosen in effect_actions:
            self._trigger_effect(effect_actions[chosen])
        elif chosen == spin_action:
            self._auto_spin = not self._auto_spin
            self._hide_hint()
            self.update()
        elif chosen == reset_action:
            self._reset_view()
        elif chosen == back_action:
            self._place_bottom_right()
        elif chosen == quit_action:
            QApplication.quit()

    # ------------------------------------------------------------------
    # 显示
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._fade.state() != QPropertyAnimation.Running:
            self._fade.start()


def main() -> None:
    if hasattr(QApplication, "setAttribute"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if hasattr(QApplication, "setHighDpiScaleFactorRoundingPolicy") and hasattr(
        Qt, "HighDpiScaleFactorRoundingPolicy"
    ):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    app = QApplication(sys.argv)
    app.setApplicationName("DeepSeek Whale Pet 3D")
    app.setQuitOnLastWindowClosed(True)

    pet = WhalePet()
    pet.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
