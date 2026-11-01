# -*- coding: utf-8 -*-
"""
DeepSeek 小鲸鱼桌宠（PyQt5 版）

运行：
    python whale_pet.py

如果不想安装 PyQt5，可以使用同目录下的 tkinter 版：whale_pet_tk.py

操作：
    - 按住左键拖动小鲸鱼
    - 右键打开菜单（回到右下角 / 退出）
"""

import math
import sys

from PyQt5.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PyQt5.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

# ---------------------------------------------------------------------------
# 配色（来自设定图）
# ---------------------------------------------------------------------------
OUTLINE = QColor("#59FFFF")   # H180 S65 V100
BLUE = QColor("#5460FF")      # H236 S67 V100
WHITE = QColor("#FFFFFF")     # H0 S0 V100

# 设计稿坐标：1000 x 720
DESIGN_W = 1000
DESIGN_H = 720
DESIGN_OFFSET_Y = -135

# 桌宠窗口大小（逻辑像素，会自动适配高 DPI 屏幕）
PET_WIDTH = 320
PET_HEIGHT = 230
SCREEN_MARGIN = 20
IDLE_ANIMATION = True
FACE_LEFT = True


# ---------------------------------------------------------------------------
# 绘图
# ---------------------------------------------------------------------------
def _draw_filled(painter, path, color, outline_width=15.0):
    """填充一个形状并描边。"""
    pen = QPen(OUTLINE)
    pen.setWidthF(outline_width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(color)
    painter.drawPath(path)


def _draw_shadow(painter):
    """鲸鱼下方的一团柔和阴影。"""
    painter.save()
    painter.translate(500, 808)
    painter.scale(1.0, 0.12)

    gradient = QRadialGradient(QPointF(0, 0), 335)
    gradient.setColorAt(0.00, QColor(32, 44, 100, 58))
    gradient.setColorAt(0.55, QColor(32, 44, 100, 26))
    gradient.setColorAt(1.00, QColor(32, 44, 100, 0))

    painter.setPen(Qt.NoPen)
    painter.setBrush(gradient)
    painter.drawEllipse(QPointF(0, 0), 335, 335)
    painter.restore()


def _body_path():
    path = QPainterPath()
    path.moveTo(918, 548)
    path.cubicTo(918, 430, 858, 338, 744, 306)
    path.cubicTo(650, 280, 548, 300, 468, 344)
    path.cubicTo(398, 383, 344, 440, 300, 482)
    path.cubicTo(266, 514, 236, 526, 204, 523)
    path.cubicTo(232, 558, 274, 584, 330, 608)
    path.cubicTo(428, 650, 540, 692, 654, 702)
    path.cubicTo(770, 712, 857, 667, 892, 606)
    path.cubicTo(902, 588, 912, 568, 918, 548)
    path.closeSubpath()
    return path


def _belly_path():
    path = QPainterPath()
    path.moveTo(918, 538)
    path.cubicTo(910, 634, 855, 696, 760, 718)
    path.cubicTo(640, 748, 504, 706, 382, 651)
    path.cubicTo(338, 632, 298, 610, 256, 580)
    path.cubicTo(330, 605, 420, 626, 526, 635)
    path.cubicTo(650, 656, 770, 646, 836, 607)
    path.cubicTo(876, 586, 904, 560, 918, 538)
    path.closeSubpath()
    return path


def _dorsal_fin_path():
    path = QPainterPath()
    path.moveTo(565, 368)
    path.cubicTo(550, 322, 528, 282, 495, 252)
    path.cubicTo(492, 292, 480, 328, 458, 365)
    path.cubicTo(492, 354, 528, 358, 565, 368)
    path.closeSubpath()
    return path


def _tail_upper_path():
    path = QPainterPath()
    path.moveTo(252, 518)
    path.cubicTo(218, 468, 168, 430, 108, 418)
    path.cubicTo(122, 470, 154, 514, 208, 546)
    path.cubicTo(228, 540, 244, 532, 252, 518)
    path.closeSubpath()
    return path


def _tail_lower_path():
    path = QPainterPath()
    path.moveTo(238, 546)
    path.cubicTo(200, 598, 154, 638, 100, 656)
    path.cubicTo(116, 604, 156, 558, 210, 528)
    path.cubicTo(222, 534, 233, 542, 238, 546)
    path.closeSubpath()
    return path


def _pectoral_fin_path():
    path = QPainterPath()
    path.moveTo(600, 688)
    path.cubicTo(582, 730, 545, 768, 482, 806)
    path.cubicTo(458, 770, 466, 724, 495, 689)
    path.cubicTo(528, 664, 568, 666, 600, 688)
    path.closeSubpath()
    return path


def _draw_eye(painter):
    # 大块白色眼斑
    painter.save()
    painter.translate(810, 458)
    painter.rotate(18)
    painter.setPen(Qt.NoPen)
    painter.setBrush(WHITE)
    painter.drawEllipse(QPointF(0, 0), 60, 78)
    painter.restore()

    # 眼斑下方的小白点（脸颊斑）
    painter.setPen(Qt.NoPen)
    painter.setBrush(WHITE)
    painter.drawEllipse(QPointF(840, 578), 16, 18)

    # 微笑的嘴
    pen = QPen(OUTLINE)
    pen.setWidthF(9.0)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    mouth = QPainterPath()
    mouth.moveTo(752, 625)
    mouth.cubicTo(785, 648, 828, 649, 862, 624)
    painter.drawPath(mouth)


def _draw_tail(painter, angle):
    painter.save()
    painter.translate(245, 530)
    painter.rotate(angle)
    painter.translate(-245, -530)
    _draw_filled(painter, _tail_upper_path(), BLUE)
    _draw_filled(painter, _tail_lower_path(), BLUE)
    painter.restore()


def _draw_pectoral_fin(painter, angle):
    painter.save()
    painter.translate(590, 680)
    painter.rotate(angle)
    painter.translate(-590, -680)
    _draw_filled(painter, _pectoral_fin_path(), BLUE)
    painter.restore()


def paint_whale(painter, target_rect, phase=0.0, mirror=True):
    """把鲸鱼画进 target_rect；phase 用于呼吸/摆尾动画。"""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)

    scale = min(target_rect.width() / DESIGN_W, target_rect.height() / DESIGN_H)
    offset_x = target_rect.x() + (target_rect.width() - DESIGN_W * scale) / 2.0
    offset_y = target_rect.y() + (target_rect.height() - DESIGN_H * scale) / 2.0
    painter.translate(offset_x, offset_y)
    painter.scale(scale, scale)

    # 默认面向左侧（朝向屏幕内部）
    if mirror:
        painter.translate(DESIGN_W, 0)
        painter.scale(-1, 1)

    painter.translate(0, DESIGN_OFFSET_Y)

    # 阴影固定在地面，鲸鱼做轻微上下浮动
    _draw_shadow(painter)

    bob = math.sin(phase * math.tau / 3.6) * 4.0 if IDLE_ANIMATION else 0.0
    tail_angle = math.sin(phase * math.tau / 2.8) * 4.5 if IDLE_ANIMATION else 0.0
    fin_angle = (
        math.sin(phase * math.tau / 3.1 + 0.8) * 3.0 if IDLE_ANIMATION else 0.0
    )

    painter.translate(0, bob)

    # 后面：尾巴、胸鳍
    _draw_tail(painter, tail_angle)
    _draw_pectoral_fin(painter, fin_angle)

    # 身体先在无描边状态下填充，再叠白色肚皮
    body = _body_path()
    painter.setPen(Qt.NoPen)
    painter.setBrush(BLUE)
    painter.drawPath(body)

    painter.save()
    painter.setClipPath(body)
    painter.setPen(Qt.NoPen)
    painter.setBrush(WHITE)
    painter.drawPath(_belly_path())
    painter.restore()

    # 背鳍只画在身体轮廓之外，避免鳍根和身体描边叠出多余的线。
    painter.save()
    outside = QPainterPath()
    outside.setFillRule(Qt.OddEvenFill)
    outside.addRect(QRectF(-2000, -2000, 6000, 6000))
    outside.addPath(body)
    painter.setClipPath(outside)
    _draw_filled(painter, _dorsal_fin_path(), BLUE)
    painter.restore()

    body_pen = QPen(OUTLINE)
    body_pen.setWidthF(15.0)
    body_pen.setCapStyle(Qt.RoundCap)
    body_pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(body_pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(body)

    _draw_eye(painter)

    painter.restore()


# ---------------------------------------------------------------------------
# 桌宠窗口
# ---------------------------------------------------------------------------
class WhalePet(QWidget):
    def __init__(self):
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
        self.setFixedSize(PET_WIDTH, PET_HEIGHT)
        self.setCursor(Qt.OpenHandCursor)

        self._drag_offset = None
        self._clock = QElapsedTimer()
        self._clock.start()

        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30 FPS
        self._timer.timeout.connect(self.update)
        self._timer.start()

        self._place_bottom_right()

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(420)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

    # ---- 位置 ----------------------------------------------------------
    def _place_bottom_right(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = area.right() - self.width() - SCREEN_MARGIN + 1
        y = area.bottom() - self.height() - SCREEN_MARGIN + 1
        self.move(x, y)

    # ---- 绘制 ----------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        phase = self._clock.elapsed() / 1000.0
        paint_whale(
            painter,
            QRectF(0, 0, self.width(), self.height()),
            phase,
            mirror=FACE_LEFT,
        )
        painter.end()

    # ---- 拖动 ----------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)
            self.raise_()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
            self.setCursor(Qt.OpenHandCursor)
            self._ensure_on_screen()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _ensure_on_screen(self):
        """避免把鲸鱼完全拖到屏幕外面。"""
        frame = self.frameGeometry()
        for screen in QApplication.screens():
            if screen.availableGeometry().intersects(frame):
                return
        self._place_bottom_right()

    # ---- 右键菜单 ------------------------------------------------------
    def contextMenuEvent(self, event):
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
                padding: 7px 26px 7px 14px;
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
        back_action = menu.addAction("回到右下角")
        menu.addSeparator()
        quit_action = menu.addAction("退出小鲸鱼")

        chosen = menu.exec_(event.globalPos())
        if chosen == back_action:
            self._place_bottom_right()
        elif chosen == quit_action:
            QApplication.quit()

    def showEvent(self, event):
        super().showEvent(event)
        if self._fade.state() != QPropertyAnimation.Running:
            self._fade.start()


def main():
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
    app.setApplicationName("DeepSeek Whale Pet")
    app.setQuitOnLastWindowClosed(True)

    pet = WhalePet()
    pet.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
