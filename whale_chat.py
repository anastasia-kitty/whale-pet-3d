# -*- coding: utf-8 -*-
"""
小鲸鱼的聊天窗口。

结构：
    ChatWindow
    ├─ HeaderBar       标题、历史目录、新对话、设置、收起
    ├─ QStackedWidget  空状态 / 消息滚动区
    ├─ Composer        输入框 + 发送/停止 + 深度思考开关
    ├─ HistoryDrawer   从左侧滑出的对话目录
    └─ SettingsDialog  独立弹窗：API Key、模型、深度思考、人设

只依赖 PyQt5；网络请求在 whale_api.py 的后台线程里完成。
"""

from __future__ import annotations

import math
import sys
import time
from typing import List, Optional

from PyQt5.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtProperty,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QDesktopServices,
    QFont,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPolygonF,
    QTextDocument,
    QTextOption,
)
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from whale_api import ChatWorker, KeyTestWorker, build_messages
from whale_config import (
    DEFAULT_SYSTEM_PROMPT,
    MODEL_CHOICES,
    Settings,
    data_dir,
    data_dir_display,
)
from whale_markdown import plain_excerpt, render_markdown
from whale_store import Conversation, ConversationStore, group_label

# ---------------------------------------------------------------------------
# 配色 / 尺寸
# ---------------------------------------------------------------------------
BLUE = "#5460FF"
BLUE_HOVER = "#4450E8"
CYAN = "#59FFFF"
INK = "#3B4668"
INK_SOFT = "#5A6488"
MUTED = "#8A94B8"
LINE = "#E4EAFF"
PANEL = "#F7F9FF"
WHITE = "#FFFFFF"
DANGER = "#D94F6A"
DANGER_SOFT = "#FFF3F5"

WINDOW_W = 420
WINDOW_H = 600
SHADOW = 10
RADIUS = 20
HEADER_H = 58
COMPOSER_H = 96
DRAWER_W = 268

EFFORT_LABELS = (("low", "低"), ("high", "高"), ("max", "最高"))
MODEL_SHORT = {
    "deepseek-flash": "Flash",
    "deepseek-v4-pro": "V4 Pro",
}
FONT_FAMILY = "Microsoft YaHei UI"
FONT_MONO = "Consolas"


def ui_font(point_size: int, bold: bool = False) -> QFont:
    font = QFont(FONT_FAMILY, point_size)
    font.setStyleStrategy(QFont.PreferAntialias)
    if bold:
        font.setWeight(QFont.DemiBold)
    return font


def _round_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


# ---------------------------------------------------------------------------
# 小鲸鱼头像：纯代码画，不依赖图片
# ---------------------------------------------------------------------------
class WhaleAvatar(QWidget):
    def __init__(self, size: int = 30, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())

        # 尾巴
        tail = QPainterPath()
        tail.moveTo(w * 0.70, h * 0.46)
        tail.lineTo(w * 0.98, h * 0.30)
        tail.lineTo(w * 0.90, h * 0.52)
        tail.lineTo(w * 0.98, h * 0.72)
        tail.lineTo(w * 0.70, h * 0.58)
        tail.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(BLUE))
        painter.drawPath(tail)

        # 身体
        painter.drawEllipse(QRectF(w * 0.08, h * 0.20, w * 0.68, h * 0.60))
        # 肚皮
        painter.setBrush(QColor(WHITE))
        painter.drawEllipse(QRectF(w * 0.22, h * 0.46, w * 0.46, h * 0.28))
        # 眼睛
        painter.setBrush(QColor("#131830"))
        painter.drawEllipse(
            QPointF(w * 0.36, h * 0.40), w * 0.035, h * 0.045
        )
        # 小水花
        painter.setBrush(QColor(CYAN))
        painter.drawEllipse(QPointF(w * 0.34, h * 0.15), w * 0.035, h * 0.035)
        painter.drawEllipse(QPointF(w * 0.46, h * 0.10), w * 0.022, h * 0.022)


# ---------------------------------------------------------------------------
# 顶部按钮
# ---------------------------------------------------------------------------
class IconButton(QWidget):
    clicked = pyqtSignal()

    def __init__(
        self,
        glyph: str,
        tooltip: str,
        danger: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._danger = danger
        self._hover = False
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self._hover:
            painter.setPen(Qt.NoPen)
            if self._danger:
                painter.setBrush(QColor("#FFE9ED"))
            else:
                painter.setBrush(QColor("#EEF1FF"))
            painter.drawEllipse(QRectF(1, 1, 28, 28))
        painter.setFont(ui_font(10))
        color = DANGER if (self._hover and self._danger) else INK_SOFT
        painter.setPen(QColor(color))
        painter.drawText(self.rect(), Qt.AlignCenter, self._glyph)


# ---------------------------------------------------------------------------
# 消息气泡
# ---------------------------------------------------------------------------
class MessageBubble(QWidget):
    height_changed = pyqtSignal()

    TAIL = 7.0
    PAD_X = 14.0
    PAD_Y = 11.0
    RADIUS = 14.0

    def __init__(
        self,
        role: str,
        text: str = "",
        reasoning: str = "",
        error: str = "",
        cancelled: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.role = role
        self.text = text
        self.reasoning = reasoning
        self.error = error
        self.cancelled = cancelled
        self.streaming = False
        self._expanded = False
        self._user_toggled = False
        self._max_width = 300.0
        self._inner_width = 240.0
        self._content_h = 0.0
        self._reason_h = 0.0
        self._content_origin = QPointF(0, 0)
        self._reason_header = QRectF()
        self._anchor_pos = QPointF(-1, -1)

        self._content_doc = QTextDocument(self)
        self._content_doc.setDocumentMargin(0)
        self._reason_doc = QTextDocument(self)
        self._reason_doc.setDocumentMargin(0)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self._content_doc.setDefaultTextOption(option)
        self._reason_doc.setDefaultTextOption(option)

        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.ArrowCursor)
        self.setMouseTracking(True)
        self._relayout()

    # ------------------------------------------------------------------
    # 内容
    # ------------------------------------------------------------------
    def set_max_width(self, width: float) -> None:
        width = max(160.0, float(width))
        if abs(width - self._max_width) < 0.5:
            return
        self._max_width = width
        self._relayout()

    def append_text(self, delta: str) -> None:
        if not delta:
            return
        self.text += delta
        self._relayout()

    def append_reasoning(self, delta: str) -> None:
        if not delta:
            return
        self.reasoning += delta
        if not self._user_toggled:
            self._expanded = True
        self._relayout()

    def set_streaming(self, streaming: bool) -> None:
        if self.streaming != streaming:
            self.streaming = streaming
            self._relayout()

    def finish(
        self,
        text: str,
        reasoning: str,
        cancelled: bool = False,
    ) -> None:
        self.text = text
        self.reasoning = reasoning
        self.cancelled = cancelled
        self.streaming = False
        if reasoning and not self._user_toggled:
            self._expanded = False
        self._relayout()

    def set_error(self, message: str) -> None:
        self.error = message
        self.streaming = False
        self._relayout()

    def _display_text(self) -> str:
        if self.role == "user":
            return self.text
        if self.error:
            return "⚠  " + self.error
        text = self.text
        if self.streaming and text:
            text += "▍"
        return text

    # ------------------------------------------------------------------
    # 排版
    # ------------------------------------------------------------------
    def _relayout(self) -> None:
        maxw = self._max_width
        inner_max = max(80.0, maxw - self.TAIL - 2 * self.PAD_X)

        self._content_doc.setDefaultFont(ui_font(10))
        if self.role == "user":
            self._content_doc.setPlainText(self._display_text())
        elif self.error:
            self._content_doc.setPlainText(self._display_text())
        else:
            self._content_doc.setHtml(render_markdown(self._display_text()))
        self._content_doc.setTextWidth(inner_max)
        content_ideal = self._content_doc.idealWidth()

        self._reason_doc.setDefaultFont(ui_font(9))
        self._reason_doc.setPlainText(self.reasoning)
        self._reason_doc.setTextWidth(inner_max)
        reason_ideal = self._reason_doc.idealWidth() if self.reasoning else 0.0

        inner = int(
            math.ceil(
                min(inner_max, max(72.0, content_ideal, reason_ideal))
            )
        )
        self._content_doc.setTextWidth(inner)
        self._inner_width = float(inner)
        self._content_h = self._content_doc.size().height()
        if self._content_h < 20.0:
            self._content_h = 20.0

        self._reason_doc.setTextWidth(inner)
        self._reason_h = (
            self._reason_doc.size().height() if self.reasoning else 0.0
        )

        content_y = self.PAD_Y
        if self.reasoning:
            content_y += 22.0
            if self._expanded:
                content_y += self._reason_h + 10.0
            else:
                content_y += 8.0

        width = inner + 2 * self.PAD_X + self.TAIL
        height = content_y + self._content_h + self.PAD_Y
        self.setFixedSize(int(round(width)), int(round(height)))
        self._reason_header = QRectF()
        self.updateGeometry()
        self.update()
        self.height_changed.emit()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        role = self.role
        w = float(self.width())
        h = float(self.height())
        tail = self.TAIL

        if role == "user":
            rect = QRectF(0.0, 0.0, w - tail, h)
        else:
            rect = QRectF(tail, 0.0, w - tail, h)

        if role == "assistant":
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(60, 70, 120, 12))
            shadow = QRectF(rect)
            shadow.translate(0.0, 2.0)
            painter.drawRoundedRect(shadow, self.RADIUS, self.RADIUS)

        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        if role == "user":
            tri = QPolygonF(
                [
                    QPointF(rect.right() - 1.0, 17.0),
                    QPointF(w, 23.0),
                    QPointF(rect.right() - 1.0, 29.0),
                ]
            )
        else:
            tri = QPolygonF(
                [
                    QPointF(rect.left() + 1.0, 17.0),
                    QPointF(0.0, 23.0),
                    QPointF(rect.left() + 1.0, 29.0),
                ]
            )
        path.addPolygon(tri)

        if role == "user":
            fill = QColor(BLUE)
            border = QColor(BLUE)
            text_color = QColor("#FFFFFF")
        elif self.error:
            fill = QColor(DANGER_SOFT)
            border = QColor("#FFC6D1")
            text_color = QColor(DANGER)
        else:
            fill = QColor(WHITE)
            border = QColor(LINE)
            text_color = QColor(INK)

        painter.setPen(QPen(border, 1.0))
        painter.setBrush(fill)
        painter.drawPath(path)

        if role == "user":
            text_x = self.PAD_X
        else:
            text_x = tail + self.PAD_X
        text_w = self._inner_width
        text_top = self.PAD_Y
        cursor_y = text_top

        if self.reasoning:
            header = QRectF(text_x, cursor_y, text_w, 22.0)
            self._reason_header = header
            font = ui_font(9, bold=True)
            painter.setFont(font)
            painter.setPen(QColor("#7C86A8"))
            label = "正在思考…" if (self.streaming and not self.text) else "思考过程"
            painter.drawText(
                QRectF(header.left(), header.top(), header.width() - 18, header.height()),
                Qt.AlignLeft | Qt.AlignVCenter,
                label,
            )
            painter.setFont(ui_font(9))
            painter.setPen(QColor(MUTED))
            painter.drawText(
                QRectF(header.right() - 16, header.top(), 16, header.height()),
                Qt.AlignCenter,
                "▾" if self._expanded else "▸",
            )
            cursor_y += 22.0
            if self._expanded:
                ctx = QAbstractTextDocumentLayout.PaintContext()
                ctx.palette.setColor(QPalette.Text, QColor("#6F7899"))
                painter.save()
                painter.setClipRect(
                    QRectF(text_x, cursor_y, text_w, self._reason_h + 2.0)
                )
                painter.translate(text_x, cursor_y)
                self._reason_doc.documentLayout().draw(painter, ctx)
                painter.restore()
                cursor_y += self._reason_h + 10.0
                painter.setPen(QPen(QColor("#EDF0FA"), 1.0))
                painter.drawLine(
                    QPointF(text_x, cursor_y - 5.0),
                    QPointF(text_x + text_w, cursor_y - 5.0),
                )
            else:
                cursor_y += 8.0

        self._content_origin = QPointF(text_x, cursor_y)

        if self.streaming and not self.text and not self.reasoning:
            self._draw_waiting_dots(painter, text_x, cursor_y, text_w)
        elif self._content_h > 0:
            ctx = QAbstractTextDocumentLayout.PaintContext()
            ctx.palette.setColor(QPalette.Text, text_color)
            ctx.palette.setColor(QPalette.Highlight, QColor("#C8D0FF"))
            ctx.palette.setColor(QPalette.HighlightedText, QColor("#1E2440"))
            painter.save()
            painter.setClipRect(
                QRectF(text_x, cursor_y, text_w, self._content_h + 2.0)
            )
            painter.translate(text_x, cursor_y)
            self._content_doc.documentLayout().draw(painter, ctx)
            painter.restore()

    def _draw_waiting_dots(
        self, painter: QPainter, x: float, y: float, width: float
    ) -> None:
        painter.setPen(Qt.NoPen)
        phase = time.monotonic() * 3.2
        for index in range(3):
            alpha = 80 + int(120 * (0.5 + 0.5 * math.sin(phase - index * 0.9)))
            painter.setBrush(QColor(124, 134, 168, alpha))
            painter.drawEllipse(
                QPointF(x + 8.0 + index * 11.0, y + 10.0), 3.0, 3.0
            )

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _anchor_at(self, pos: QPointF) -> str:
        if self.role == "user":
            return ""
        local = QPointF(
            pos.x() - self._content_origin.x(),
            pos.y() - self._content_origin.y(),
        )
        if local.y() < 0 or local.y() > self._content_h + 2:
            return ""
        return self._content_doc.documentLayout().anchorAt(local)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self.reasoning and self._reason_header.contains(
                QPointF(event.pos())
            ):
                self._expanded = not self._expanded
                self._user_toggled = True
                self._relayout()
                event.accept()
                return
            anchor = self._anchor_at(QPointF(event.pos()))
            if anchor:
                QDesktopServices.openUrl(QUrl(anchor))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.reasoning and self._reason_header.contains(QPointF(event.pos())):
            self.setCursor(Qt.PointingHandCursor)
        elif self._anchor_at(QPointF(event.pos())):
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu { background:#FFFFFF; color:#3B4668; border:1px solid #DDE6FF;
                    border-radius:8px; padding:4px; font-size:12px; }
            QMenu::item { padding:6px 18px 6px 12px; border-radius:5px; }
            QMenu::item:selected { background:#EEF1FF; color:#5460FF; }
            """
        )
        copy_action = menu.addAction("复制这段回复")
        copy_reasoning = None
        if self.reasoning:
            copy_reasoning = menu.addAction("复制思考过程")
        chosen = menu.exec_(event.globalPos())
        if chosen == copy_action:
            QApplication.clipboard().setText(self.text)
        elif copy_reasoning is not None and chosen == copy_reasoning:
            QApplication.clipboard().setText(self.reasoning)


# ---------------------------------------------------------------------------
# 输入框
# ---------------------------------------------------------------------------
class ChatInput(QPlainTextEdit):
    submit = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFont(ui_font(10))
        self.setPlaceholderText("和小鲸鱼说点什么…")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QPlainTextEdit.NoFrame)
        self.setStyleSheet(
            """
            QPlainTextEdit {
                background: transparent;
                border: none;
                color: #3B4668;
                selection-background-color: #C9D2FF;
                selection-color: #1E2440;
                padding: 0px;
            }
            """
        )
        self.setFixedHeight(42)
        self.setTabChangesFocus(True)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
                return
            event.accept()
            self.submit.emit()
            return
        super().keyPressEvent(event)


class SendButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        self._busy = False
        self._enabled = True

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.setToolTip("停止生成" if busy else "发送")
        self.update()

    def set_enabled_state(self, enabled: bool) -> None:
        self._enabled = enabled
        self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self._busy or self._enabled:
                self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self._busy:
            color = QColor("#FF8FA3") if self._hover else QColor("#F27C93")
        elif not self._enabled:
            color = QColor("#D5DBF0")
        else:
            color = QColor(BLUE_HOVER) if self._hover else QColor(BLUE)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(0, 0, 36, 36))
        if self._busy:
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawRoundedRect(QRectF(12, 12, 12, 12), 3, 3)
        else:
            painter.setPen(QPen(QColor("#FFFFFF"), 2.2))
            painter.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(13.0, 11.5)
            path.lineTo(24.5, 18.0)
            path.lineTo(13.0, 24.5)
            path.lineTo(15.6, 18.0)
            path.closeSubpath()
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(Qt.NoPen)
            painter.drawPath(path)


# ---------------------------------------------------------------------------
# 空状态
# ---------------------------------------------------------------------------
class EmptyState(QWidget):
    prompt_selected = pyqtSignal(str)
    setup_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 30)
        layout.setSpacing(8)
        layout.addStretch(1)

        self._avatar = WhaleAvatar(76, self)
        layout.addWidget(self._avatar, 0, Qt.AlignHCenter)
        layout.addSpacing(6)

        title = QLabel("嗨，我是小鲸鱼～", self)
        title.setFont(ui_font(15, bold=True))
        title.setStyleSheet("color:%s;" % INK)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self._hint = QLabel("今天想聊点什么？我在这儿陪着你。", self)
        self._hint.setFont(ui_font(9))
        self._hint.setStyleSheet("color:%s;" % MUTED)
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)
        layout.addSpacing(10)

        chip_grid = QGridLayout()
        chip_grid.setHorizontalSpacing(8)
        chip_grid.setVerticalSpacing(8)
        for index, text in enumerate(
            ("陪我聊聊天", "帮我写段代码", "讲个冷笑话", "推荐一部电影")
        ):
            chip = QPushButton(text, self)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setFont(ui_font(9))
            chip.setStyleSheet(
                """
                QPushButton {
                    background:#F4F6FF; color:#5460FF; border:1px solid #E1E7FF;
                    border-radius:13px; padding:5px 14px;
                }
                QPushButton:hover { background:#E9EDFF; border-color:#C9D3FF; }
                """
            )
            chip.clicked.connect(
                lambda _checked=False, value=text: self.prompt_selected.emit(value)
            )
            chip_grid.addWidget(
                chip, index // 2, index % 2, 1, 1, Qt.AlignHCenter
            )
        layout.addLayout(chip_grid)

        self._setup_button = QPushButton("去填写 API Key", self)
        self._setup_button.setCursor(Qt.PointingHandCursor)
        self._setup_button.setFont(ui_font(9, bold=True))
        self._setup_button.setStyleSheet(
            """
            QPushButton {
                background:#5460FF; color:#FFFFFF; border:none;
                border-radius:14px; padding:7px 18px;
            }
            QPushButton:hover { background:#4450E8; }
            """
        )
        self._setup_button.clicked.connect(self.setup_requested)
        self._setup_button.hide()
        layout.addSpacing(6)
        layout.addWidget(self._setup_button, 0, Qt.AlignHCenter)
        layout.addStretch(2)

    def set_key_missing(self, missing: bool) -> None:
        self._setup_button.setVisible(missing)
        if missing:
            self._hint.setText("先到设置里填一下 API Key，我们就可以聊天啦～")
        else:
            self._hint.setText("今天想聊点什么？我在这儿陪着你。")


# ---------------------------------------------------------------------------
# 顶部栏
# ---------------------------------------------------------------------------
class HeaderBar(QWidget):
    history_clicked = pyqtSignal()
    new_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    close_clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(HEADER_H)
        self._drag_offset = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 12, 8)
        layout.setSpacing(9)

        layout.addWidget(WhaleAvatar(34, self))

        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        text_box.setContentsMargins(0, 0, 0, 0)
        self._title = QLabel("小鲸鱼", self)
        self._title.setFont(ui_font(11, bold=True))
        self._title.setStyleSheet("color:%s;" % INK)
        self._subtitle = QLabel("DeepSeek 对话", self)
        self._subtitle.setFont(ui_font(8))
        self._subtitle.setStyleSheet("color:%s;" % MUTED)
        text_box.addWidget(self._title)
        text_box.addWidget(self._subtitle)
        layout.addLayout(text_box, 1)

        self.history_button = IconButton("☰", "历史对话", parent=self)
        self.new_button = IconButton("＋", "新对话", parent=self)
        self.settings_button = IconButton("⚙", "设置", parent=self)
        self.close_button = IconButton("✕", "收起聊天窗", danger=True, parent=self)
        for button in (
            self.history_button,
            self.new_button,
            self.settings_button,
            self.close_button,
        ):
            layout.addWidget(button, 0, Qt.AlignVCenter)

        self.history_button.clicked.connect(self.history_clicked)
        self.new_button.clicked.connect(self.new_clicked)
        self.settings_button.clicked.connect(self.settings_clicked)
        self.close_button.clicked.connect(self.close_clicked)

    def set_subtitle(self, text: str) -> None:
        self._subtitle.setText(text)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#EEF2FF"), 1.0))
        painter.drawLine(
            QPointF(18, self.height() - 0.5),
            QPointF(self.width() - 18, self.height() - 0.5),
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            window = self.window()
            self._drag_offset = event.globalPos() - window.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPos() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        event.accept()


# ---------------------------------------------------------------------------
# 底部输入区
# ---------------------------------------------------------------------------
class Composer(QWidget):
    send_clicked = pyqtSignal()
    thinking_clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(COMPOSER_H)

        self.input = ChatInput(self)
        self.input.setToolTip("Enter 发送，Shift + Enter 换行")
        self.send_button = SendButton(self)

        self._think_chip = QPushButton("深度思考 · 高", self)
        self._think_chip.setCursor(Qt.PointingHandCursor)
        self._think_chip.setFont(ui_font(8))
        self._think_chip.setFocusPolicy(Qt.NoFocus)
        self._think_chip.clicked.connect(self.thinking_clicked)

        self._hint = QLabel("Enter 发送", self)
        self._hint.setFont(ui_font(8))
        self._hint.setStyleSheet("color:%s;" % MUTED)
        self._hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.input.submit.connect(self.send_clicked)
        self.send_button.clicked.connect(self.send_clicked)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w = self.width()
        self.input.setGeometry(26, 17, max(80, w - 28 - 26 - 56), 42)
        self.send_button.move(w - 14 - 12 - 36, 22)
        self._think_chip.setGeometry(20, COMPOSER_H - 26, 126, 20)
        self._hint.setGeometry(154, COMPOSER_H - 26, w - 174, 20)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        field = QRectF(14, 8, self.width() - 28, 58)
        painter.setPen(QPen(QColor(LINE), 1.0))
        painter.setBrush(QColor(PANEL))
        painter.drawRoundedRect(field, 18, 18)

    def set_thinking(self, enabled: bool, effort: str) -> None:
        if enabled:
            label = "深度思考 · " + dict(EFFORT_LABELS).get(effort, "高")
            self._think_chip.setText(label)
            self._think_chip.setStyleSheet(
                """
                QPushButton {
                    background:#EEF1FF; color:#5460FF; border:none;
                    border-radius:9px; padding:2px 9px; text-align:left;
                }
                QPushButton:hover { background:#E2E7FF; }
                """
            )
        else:
            self._think_chip.setText("普通对话")
            self._think_chip.setStyleSheet(
                """
                QPushButton {
                    background:#F1F3FA; color:#8A94B8; border:none;
                    border-radius:9px; padding:2px 9px; text-align:left;
                }
                QPushButton:hover { background:#E8EBF6; }
                """
            )

    def set_busy(self, busy: bool) -> None:
        self.send_button.set_busy(busy)
        self._hint.setText("正在回答…" if busy else "Enter 发送")


# ---------------------------------------------------------------------------
# 历史抽屉
# ---------------------------------------------------------------------------
class HistoryDrawer(QWidget):
    conversation_selected = pyqtSignal(str)
    new_requested = pyqtSignal()
    close_requested = pyqtSignal()
    delete_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(DRAWER_W)
        self._query = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title = QLabel("对话目录", self)
        title.setFont(ui_font(11, bold=True))
        title.setStyleSheet("color:%s;" % INK)
        title_row.addWidget(title)
        title_row.addStretch(1)
        close_button = IconButton("✕", "关闭目录", parent=self)
        close_button.clicked.connect(self.close_requested)
        title_row.addWidget(close_button)
        layout.addLayout(title_row)

        self.search = QLineEdit(self)
        self.search.setPlaceholderText("搜索以前的对话…")
        self.search.setFont(ui_font(9))
        self.search.setFixedHeight(32)
        self.search.setStyleSheet(
            """
            QLineEdit {
                background:#F7F9FF; border:1px solid #E4EAFF; border-radius:10px;
                padding:4px 10px; color:#3B4668;
                selection-background-color:#C9D2FF;
            }
            QLineEdit:focus { border-color:#B9C5FF; background:#FFFFFF; }
            """
        )
        self.search.textChanged.connect(self._on_search)
        layout.addWidget(self.search)

        self.list = QListWidget(self)
        self.list.setFont(ui_font(9))
        self.list.setFrameShape(QListWidget.NoFrame)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setStyleSheet(
            """
            QListWidget {
                background: transparent; border: none; outline: 0;
            }
            QListWidget::item {
                color:#3B4668; padding:8px 9px; border-radius:8px;
            }
            QListWidget::item:hover { background:#F4F6FF; }
            QListWidget::item:selected { background:#EAEEFF; color:#3E49D8; }
            QListWidget::item:disabled { color:#A6AEC9; background:transparent; }
            QScrollBar:vertical { background:transparent; width:7px; margin:1px; }
            QScrollBar::handle:vertical {
                background:#D5DDF5; border-radius:3px; min-height:26px;
            }
            QScrollBar::add-line, QScrollBar::sub-line { height:0; }
            """
        )
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list, 1)

        self._footer = QLabel("", self)
        self._footer.setFont(ui_font(8))
        self._footer.setStyleSheet("color:%s;" % MUTED)
        layout.addWidget(self._footer)

        self._conversations = []  # type: List[Conversation]
        self._current_id = None  # type: Optional[str]
        self._group_label = Qt.UserRole + 1
        self._conv_id = Qt.UserRole + 2

    # ------------------------------------------------------------------
    def set_data(
        self, conversations: List[Conversation], current_id: Optional[str]
    ) -> None:
        self._conversations = conversations
        self._current_id = current_id
        self._rebuild()

    def _on_search(self, text: str) -> None:
        self._query = text.strip().lower()
        self._rebuild()

    def _rebuild(self) -> None:
        self.list.clear()
        shown = 0
        current_item = None
        for label, items in _group_conversations(self._conversations):
            filtered = [
                c
                for c in items
                if not self._query or self._query in c.title.lower()
            ]
            if not filtered:
                continue
            header = QListWidgetItem(label)
            header.setFlags(Qt.NoItemFlags)
            header.setData(self._group_label, True)
            header.setSizeHint(QSize(0, 26))
            font = ui_font(8)
            header.setFont(font)
            header.setForeground(QColor("#A6AEC9"))
            self.list.addItem(header)

            for conversation in filtered:
                shown += 1
                item = QListWidgetItem(conversation.title)
                item.setData(self._conv_id, conversation.id)
                item.setToolTip(
                    conversation.preview()[:80]
                    + "\n"
                    + time.strftime(
                        "%Y-%m-%d %H:%M",
                        time.localtime(conversation.updated_at),
                    )
                )
                item.setSizeHint(QSize(0, 36))
                self.list.addItem(item)
                if conversation.id == self._current_id:
                    current_item = item
        if current_item is not None:
            self.list.setCurrentItem(current_item)
        total = len(self._conversations)
        if self._query:
            self._footer.setText("找到 %d 段对话" % shown)
        else:
            self._footer.setText("共 %d 段对话 · 只保存在本机" % total)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        conv_id = item.data(self._conv_id)
        if conv_id:
            self.conversation_selected.emit(str(conv_id))

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        conv_id = item.data(self._conv_id)
        if not conv_id:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu { background:#FFFFFF; color:#3B4668; border:1px solid #DDE6FF;
                    border-radius:8px; padding:4px; font-size:12px; }
            QMenu::item { padding:6px 18px 6px 12px; border-radius:5px; }
            QMenu::item:selected { background:#EEF1FF; color:#5460FF; }
            """
        )
        rename_action = menu.addAction("重命名")
        delete_action = menu.addAction("删除这段对话")
        chosen = menu.exec_(self.list.mapToGlobal(pos))
        if chosen == rename_action:
            self.rename_requested.emit(str(conv_id))
        elif chosen == delete_action:
            self.delete_requested.emit(str(conv_id))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(QPen(QColor("#DCE4FF"), 1.0))
        painter.setBrush(QColor(WHITE))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -1.5, -0.5), 18, 18)


def _group_conversations(conversations: List[Conversation]):
    buckets = {}
    for conversation in conversations:
        label = group_label(conversation.updated_at)
        buckets.setdefault(label, []).append(conversation)
    result = []
    for label in ("今天", "昨天", "本周", "更早"):
        if label in buckets:
            result.append((label, buckets[label]))
    return result


# ---------------------------------------------------------------------------
# 开关
# ---------------------------------------------------------------------------
class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(46, 26)
        self.setCursor(Qt.PointingHandCursor)
        self._checked = checked
        self._knob = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        if checked == self._checked:
            return
        self._checked = checked
        self._anim.stop()
        self._anim.setStartValue(self._knob)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()
        self.toggled.emit(checked)

    def _get_knob(self) -> float:
        return self._knob

    def _set_knob(self, value: float) -> None:
        self._knob = value
        self.update()

    knob = pyqtProperty(float, fget=_get_knob, fset=_set_knob)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        track = QRectF(0, 2, 46, 22)
        if self._checked:
            color = QColor(BLUE)
        else:
            color = QColor("#D8DFF3")
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(track, 11, 11)
        cx = 11.0 + self._knob * 24.0
        painter.setBrush(QColor(WHITE))
        painter.drawEllipse(QPointF(cx, 13.0), 9.0, 9.0)


# ---------------------------------------------------------------------------
# 设置弹窗
# ---------------------------------------------------------------------------
class ComboBox(QComboBox):
    """去掉系统箭头，自己画一个和整体风格一致的「▾」。"""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(INK_SOFT), 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        cx = float(self.width()) - 15.0
        cy = float(self.height()) / 2.0
        painter.drawLine(QPointF(cx - 4.0, cy - 2.0), QPointF(cx, cy + 2.0))
        painter.drawLine(QPointF(cx, cy + 2.0), QPointF(cx + 4.0, cy - 2.0))


class SettingsDialog(QDialog):
    saved = pyqtSignal()

    def __init__(self, settings: Settings, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.result_settings = None  # type: Optional[Settings]
        self._test_worker = None  # type: Optional[KeyTestWorker]
        self._drag_offset = None

        self.setWindowFlags(
            Qt.Dialog
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFixedSize(480, 660)
        self.setWindowModality(Qt.ApplicationModal)
        self._build_ui()
        self._load(settings)
        self._center_on_parent()

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            center = parent.frameGeometry().center()
        else:
            center = QApplication.primaryScreen().availableGeometry().center()
        screen = QApplication.screenAt(center)
        if screen is None:
            screen = QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = center.x() - self.width() // 2
        y = center.y() - self.height() // 2
        x = max(area.left() + 8, min(x, area.right() - self.width() - 8))
        y = max(area.top() + 8, min(y, area.bottom() - self.height() - 8))
        self.move(x, y)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SHADOW + 16, SHADOW + 12, SHADOW + 16, SHADOW + 14)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("小鲸鱼设置", self)
        title.setFont(ui_font(13, bold=True))
        title.setStyleSheet("color:%s;" % INK)
        title_row.addWidget(title)
        title_row.addStretch(1)
        close_button = IconButton("✕", "关闭", danger=True, parent=self)
        close_button.clicked.connect(self.reject)
        title_row.addWidget(close_button)
        layout.addLayout(title_row)
        layout.addSpacing(2)

        self._key_edit = self._make_line_edit("sk-…")
        layout.addWidget(self._field_label("API Key"))
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        key_row.addWidget(self._key_edit, 1)
        self._show_key = QPushButton("显示", self)
        self._show_key.setFixedSize(48, 36)
        self._show_key.setCursor(Qt.PointingHandCursor)
        self._show_key.setFont(ui_font(9))
        self._show_key.setStyleSheet(self._ghost_style())
        self._show_key.clicked.connect(self._toggle_key_visibility)
        key_row.addWidget(self._show_key)
        layout.addLayout(key_row)

        self._key_hint = QLabel(
            '只保存在这台电脑上，不会发给 DeepSeek 以外的服务。'
            '<a href="https://platform.deepseek.com/api_keys" '
            'style="color:#5460FF;text-decoration:none;">去申请 API Key</a>',
            self,
        )
        self._key_hint.setFont(ui_font(8))
        self._key_hint.setStyleSheet("color:%s;" % MUTED)
        self._key_hint.setOpenExternalLinks(True)
        self._key_hint.setWordWrap(True)
        layout.addWidget(self._key_hint)

        self._data_label = QLabel("数据目录：" + data_dir_display(), self)
        self._data_label.setFont(ui_font(8))
        self._data_label.setStyleSheet("color:%s;" % MUTED)
        self._data_label.setWordWrap(True)
        self._data_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._data_label.setToolTip(str(data_dir()))
        layout.addWidget(self._data_label)

        layout.addWidget(self._field_label("模型"))
        self._model_combo = ComboBox(self)
        self._model_combo.setFont(ui_font(9))
        self._model_combo.setFixedHeight(36)
        self._model_combo.setStyleSheet(self._combo_style())
        for value, label in MODEL_CHOICES:
            self._model_combo.addItem(label, value)
        layout.addWidget(self._model_combo)

        layout.addSpacing(2)
        thinking_row = QHBoxLayout()
        thinking_row.setSpacing(10)
        thinking_text = QVBoxLayout()
        thinking_text.setSpacing(1)
        thinking_title = QLabel("深度思考", self)
        thinking_title.setFont(ui_font(10, bold=True))
        thinking_title.setStyleSheet("color:%s;" % INK)
        thinking_hint = QLabel("先想再答，更稳一些，也会慢一点", self)
        thinking_hint.setFont(ui_font(8))
        thinking_hint.setStyleSheet("color:%s;" % MUTED)
        thinking_text.addWidget(thinking_title)
        thinking_text.addWidget(thinking_hint)
        thinking_row.addLayout(thinking_text, 1)
        self._thinking_switch = ToggleSwitch(self.settings.thinking, self)
        self._thinking_switch.toggled.connect(self._on_thinking_toggled)
        thinking_row.addWidget(self._thinking_switch, 0, Qt.AlignVCenter)
        layout.addLayout(thinking_row)

        effort_row = QHBoxLayout()
        effort_row.setSpacing(10)
        effort_label = QLabel("思考强度", self)
        effort_label.setFont(ui_font(9))
        effort_label.setStyleSheet("color:%s;" % INK_SOFT)
        effort_row.addWidget(effort_label, 1)
        self._effort_combo = ComboBox(self)
        self._effort_combo.setFont(ui_font(9))
        self._effort_combo.setFixedSize(150, 32)
        self._effort_combo.setStyleSheet(self._combo_style())
        for value, label in EFFORT_LABELS:
            self._effort_combo.addItem(label, value)
        effort_row.addWidget(self._effort_combo)
        layout.addLayout(effort_row)

        layout.addWidget(self._field_label("API 地址"))
        self._base_edit = self._make_line_edit("https://api.deepseek.com")
        layout.addWidget(self._base_edit)

        layout.addWidget(self._field_label("小鲸鱼的人设"))
        self._persona_edit = QPlainTextEdit(self)
        self._persona_edit.setFont(ui_font(9))
        self._persona_edit.setFixedHeight(130)
        self._persona_edit.setTabChangesFocus(True)
        self._persona_edit.setStyleSheet(
            """
            QPlainTextEdit {
                background:#F7F9FF; border:1px solid #E4EAFF; border-radius:10px;
                padding:6px 8px; color:#3B4668;
                selection-background-color:#C9D2FF;
            }
            QPlainTextEdit:focus { background:#FFFFFF; border-color:#B9C5FF; }
            """
        )
        layout.addWidget(self._persona_edit)

        test_row = QHBoxLayout()
        test_row.setSpacing(10)
        self._test_button = QPushButton("测试连接", self)
        self._test_button.setFixedSize(96, 34)
        self._test_button.setCursor(Qt.PointingHandCursor)
        self._test_button.setFont(ui_font(9))
        self._test_button.setStyleSheet(self._ghost_style())
        self._test_button.clicked.connect(self._test_connection)
        test_row.addWidget(self._test_button)
        self._test_status = QLabel("", self)
        self._test_status.setFont(ui_font(8))
        self._test_status.setStyleSheet("color:%s;" % MUTED)
        self._test_status.setWordWrap(True)
        test_row.addWidget(self._test_status, 1)
        layout.addLayout(test_row)

        layout.addStretch(1)
        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addStretch(1)
        cancel_button = QPushButton("取消", self)
        cancel_button.setFixedSize(84, 36)
        cancel_button.setCursor(Qt.PointingHandCursor)
        cancel_button.setFont(ui_font(9))
        cancel_button.setStyleSheet(self._ghost_style())
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        save_button = QPushButton("保存", self)
        save_button.setFixedSize(96, 36)
        save_button.setCursor(Qt.PointingHandCursor)
        save_button.setFont(ui_font(9, bold=True))
        save_button.setStyleSheet(
            """
            QPushButton {
                background:#5460FF; color:#FFFFFF; border:none;
                border-radius:10px; padding:6px 16px;
            }
            QPushButton:hover { background:#4450E8; }
            """
        )
        save_button.clicked.connect(self._save)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setFont(ui_font(9, bold=True))
        label.setStyleSheet("color:%s;" % INK_SOFT)
        return label

    def _make_line_edit(self, placeholder: str) -> QLineEdit:
        edit = QLineEdit(self)
        edit.setFont(ui_font(9))
        edit.setFixedHeight(36)
        edit.setPlaceholderText(placeholder)
        edit.setStyleSheet(
            """
            QLineEdit {
                background:#F7F9FF; border:1px solid #E4EAFF; border-radius:10px;
                padding:4px 11px; color:#3B4668;
                selection-background-color:#C9D2FF;
            }
            QLineEdit:focus { background:#FFFFFF; border-color:#B9C5FF; }
            """
        )
        return edit

    def _ghost_style(self) -> str:
        return """
            QPushButton {
                background:#F4F6FF; color:#5A6488; border:1px solid #E1E7FF;
                border-radius:10px; padding:5px 12px;
            }
            QPushButton:hover { background:#EAEEFF; color:#5460FF; }
        """

    def _combo_style(self) -> str:
        return """
            QComboBox {
                background:#F7F9FF; border:1px solid #E4EAFF; border-radius:10px;
                padding:2px 10px; color:#3B4668;
            }
            QComboBox:hover { border-color:#C9D3FF; }
            QComboBox:focus { background:#FFFFFF; border-color:#B9C5FF; }
            QComboBox::drop-down {
                border: none; width: 24px; background: transparent;
            }
            QComboBox QAbstractItemView {
                background:#FFFFFF; border:1px solid #DDE6FF;
                selection-background-color:#EEF1FF; selection-color:#5460FF;
                padding:4px; outline:0;
            }
        """

    # ------------------------------------------------------------------
    def _load(self, settings: Settings) -> None:
        self._key_edit.setText(settings.api_key)
        self._key_edit.setEchoMode(QLineEdit.Password)
        index = self._model_combo.findData(settings.model)
        self._model_combo.setCurrentIndex(max(0, index))
        self._thinking_switch.setChecked(settings.thinking)
        effort_index = self._effort_combo.findData(settings.reasoning_effort)
        self._effort_combo.setCurrentIndex(max(0, effort_index))
        self._effort_combo.setEnabled(settings.thinking)
        self._base_edit.setText(settings.base_url)
        self._persona_edit.setPlainText(settings.system_prompt)

    def _toggle_key_visibility(self) -> None:
        if self._key_edit.echoMode() == QLineEdit.Password:
            self._key_edit.setEchoMode(QLineEdit.Normal)
            self._show_key.setText("隐藏")
        else:
            self._key_edit.setEchoMode(QLineEdit.Password)
            self._show_key.setText("显示")

    def _on_thinking_toggled(self, checked: bool) -> None:
        self._effort_combo.setEnabled(checked)

    def _collect(self) -> Settings:
        settings = Settings()
        settings.api_key = self._key_edit.text().strip()
        settings.base_url = (
            self._base_edit.text().strip() or "https://api.deepseek.com"
        )
        settings.model = str(self._model_combo.currentData())
        settings.thinking = self._thinking_switch.isChecked()
        settings.reasoning_effort = str(self._effort_combo.currentData())
        settings.system_prompt = self._persona_edit.toPlainText().strip()
        settings.max_context_chars = self.settings.max_context_chars
        settings.chat_position = self.settings.chat_position
        settings.first_run_done = True
        return settings

    def _save(self) -> None:
        settings = self._collect()
        try:
            settings.save()
        except OSError as exc:
            self._test_status.setText("保存失败：%s" % exc)
            self._test_status.setStyleSheet("color:%s;" % DANGER)
            return
        self.result_settings = settings
        self.saved.emit()
        self.accept()

    def _test_connection(self) -> None:
        settings = self._collect()
        if not settings.has_key():
            self._test_status.setText("先填一下 API Key 再测试吧～")
            self._test_status.setStyleSheet("color:%s;" % DANGER)
            return
        self._stop_test_worker()
        self._test_button.setEnabled(False)
        self._test_button.setText("测试中…")
        self._test_status.setText("正在连接 DeepSeek…")
        self._test_status.setStyleSheet("color:%s;" % MUTED)

        worker = KeyTestWorker(settings)
        worker.done.connect(self._on_test_done)
        worker.finished.connect(worker.deleteLater)
        self._test_worker = worker
        worker.start()

    def _on_test_done(self, ok: bool, message: str) -> None:
        if self.sender() is not self._test_worker:
            return
        self._test_button.setEnabled(True)
        self._test_button.setText("测试连接")
        self._test_status.setText(message)
        self._test_status.setStyleSheet(
            "color:%s;" % ("#2E9E6B" if ok else DANGER)
        )
        self._test_worker = None

    def _stop_test_worker(self) -> None:
        worker = self._test_worker
        if worker is None:
            return
        self._test_worker = None
        try:
            worker.done.disconnect()
        except TypeError:
            pass
        worker.cancel()
        worker.wait(2000)

    def closeEvent(self, event) -> None:
        self._stop_test_worker()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        panel = QRectF(
            SHADOW,
            SHADOW,
            self.width() - 2 * SHADOW,
            self.height() - 2 * SHADOW,
        )
        for spread, alpha in ((8, 10), (5, 16), (2, 24)):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(30, 38, 70, alpha))
            painter.drawRoundedRect(
                panel.adjusted(-spread, -spread + 2, spread, spread + 2),
                RADIUS + spread,
                RADIUS + spread,
            )
        painter.setPen(QPen(QColor("#E1E7FF"), 1.0))
        painter.setBrush(QColor(WHITE))
        painter.drawRoundedRect(panel, RADIUS, RADIUS)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and event.pos().y() < 60:
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
# 聊天主窗口
# ---------------------------------------------------------------------------
class ChatWindow(QWidget):
    def __init__(self, pet=None) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
            | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setWindowTitle("小鲸鱼对话")

        self._pet = pet
        self.settings = Settings.load()
        self.store = ConversationStore()
        self._conversation = None  # type: Optional[Conversation]
        self._worker = None  # type: Optional[ChatWorker]
        self._active_bubble = None  # type: Optional[MessageBubble]
        self._active_conversation = None  # type: Optional[Conversation]
        self._busy = False
        self._delta_content = ""
        self._delta_reasoning = ""
        self._settings_dialog = None  # type: Optional[SettingsDialog]
        self._drag_offset = None
        self._position_timer = QTimer(self)
        self._position_timer.setSingleShot(True)
        self._position_timer.setInterval(500)
        self._position_timer.timeout.connect(self._save_position)

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(60)
        self._flush_timer.timeout.connect(self._flush_stream)

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._hide_toast)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(220)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

        self._build_ui()
        self._load_initial()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self._content = QWidget(self)
        self._content.setStyleSheet("background: transparent;")

        self._header = HeaderBar(self._content)
        self._header.history_clicked.connect(lambda: self._toggle_drawer())
        self._header.new_clicked.connect(self._new_chat)
        self._header.settings_clicked.connect(self._open_settings)
        self._header.close_clicked.connect(self.hide)

        self._empty = EmptyState(self._content)
        self._empty.prompt_selected.connect(self._send_text)
        self._empty.setup_requested.connect(self._open_settings)

        self._scroll = QScrollArea(self._content)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            """
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background:transparent; width:8px; margin:2px; }
            QScrollBar::handle:vertical {
                background:#D5DDF5; border-radius:4px; min-height:30px;
            }
            QScrollBar::handle:vertical:hover { background:#B8C3E8; }
            QScrollBar::add-line, QScrollBar::sub-line { height:0; }
            """
        )
        self._canvas = QWidget(self._scroll)
        self._canvas.setStyleSheet("background: transparent;")
        self._messages_layout = QVBoxLayout(self._canvas)
        self._messages_layout.setContentsMargins(14, 12, 14, 8)
        self._messages_layout.setSpacing(12)
        self._messages_layout.addStretch(1)
        self._scroll.setWidget(self._canvas)

        self._stack = QStackedWidget(self._content)
        self._stack.setStyleSheet("background: transparent;")
        self._stack.addWidget(self._empty)
        self._stack.addWidget(self._scroll)

        self._composer = Composer(self._content)
        self._composer.send_clicked.connect(self._on_send_clicked)
        self._composer.thinking_clicked.connect(self._toggle_thinking)

        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._header)
        content_layout.addWidget(self._stack, 1)
        content_layout.addWidget(self._composer)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(SHADOW, SHADOW, SHADOW, SHADOW)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._content)

        self._overlay = _Overlay(self._content)
        self._overlay.hide()
        self._overlay.clicked.connect(lambda: self._toggle_drawer(False))

        content_h = self.height() - 2 * SHADOW
        self._drawer = HistoryDrawer(self._content)
        self._drawer.setFixedHeight(content_h)
        self._drawer.move(-DRAWER_W, 0)
        self._drawer.hide()
        self._drawer.conversation_selected.connect(self._open_conversation)
        self._drawer.close_requested.connect(lambda: self._toggle_drawer(False))
        self._drawer.delete_requested.connect(self._delete_conversation)
        self._drawer.rename_requested.connect(self._rename_conversation)
        self._drawer_anim = QPropertyAnimation(self._drawer, b"pos", self)
        self._drawer_anim.setDuration(200)
        self._drawer_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._drawer_anim.finished.connect(self._on_drawer_anim_done)

        self._toast = QLabel("", self._content)
        self._toast.setFont(ui_font(9))
        self._toast.setStyleSheet(
            """
            QLabel {
                background: rgba(46, 54, 92, 232);
                color: #FFFFFF;
                border-radius: 12px;
                padding: 7px 14px;
            }
            """
        )
        self._toast.setAlignment(Qt.AlignCenter)
        self._toast.hide()

        self._rows = []  # type: List[QWidget]
        self._bubbles = []  # type: List[MessageBubble]
        self._shortcuts = [
            self._make_shortcut("Ctrl+N", self._new_chat),
            self._make_shortcut("Ctrl+,", self._open_settings),
        ]

    def _make_shortcut(self, key: str, slot) -> QShortcut:
        shortcut = QShortcut(QKeySequence(key), self)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        shortcut.activated.connect(slot)
        return shortcut

    def _load_initial(self) -> None:
        conversations = self.store.list_conversations()
        if conversations:
            self._conversation = conversations[0]
        self._refresh_header()
        self._refresh_history()
        self._render_conversation()
        self._empty.set_key_missing(not self.settings.has_key())

    # ------------------------------------------------------------------
    # 窗口位置
    # ------------------------------------------------------------------
    def open_window(self, show_settings: bool = False) -> None:
        self._refresh_header()
        self._empty.set_key_missing(not self.settings.has_key())
        if not self.isVisible():
            self._place_window()
            self.show()
            if self._fade.state() != QPropertyAnimation.Running:
                self._fade.start()
        self.raise_()
        self.activateWindow()
        self._composer.input.setFocus()
        QTimer.singleShot(0, self._refresh_after_show)
        if show_settings or (
            not self.settings.has_key() and not self.settings.first_run_done
        ):
            self.settings.first_run_done = True
            self._save_settings_quietly()
            QTimer.singleShot(260, self._open_settings)

    def _refresh_after_show(self) -> None:
        self._update_bubble_widths()
        self._scroll_to_bottom(force=True)
        self._position_toast()

    def reset_position(self) -> None:
        self.settings.chat_position = None
        self._save_settings_quietly()
        self._place_window()
        self.raise_()

    def _place_window(self) -> None:
        area = QApplication.primaryScreen().availableGeometry()
        if self._pet is not None:
            anchor = self._pet.frameGeometry()
            screen = QApplication.screenAt(anchor.center())
            if screen is not None:
                area = screen.availableGeometry()

        saved = self.settings.chat_position
        if saved:
            candidate = QPoint(int(saved[0]), int(saved[1]))
            rect = QRect(candidate, self.size())
            for screen in QApplication.screens():
                if screen.availableGeometry().intersects(rect):
                    self.move(candidate)
                    return

        if self._pet is not None:
            anchor = self._pet.frameGeometry()
            x = anchor.left() - WINDOW_W + SHADOW - 12
            if x < area.left():
                x = anchor.right() + 12 - SHADOW
            y = anchor.bottom() - (WINDOW_H - SHADOW)
            x = max(area.left(), min(x, area.right() - WINDOW_W + 1))
            y = max(area.top(), min(y, area.bottom() - WINDOW_H + 1))
            self.move(x, y)
        else:
            self.move(
                area.right() - WINDOW_W - 40,
                area.bottom() - WINDOW_H - 40,
            )

    def _save_position(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        position = [self.x(), self.y()]
        if self.settings.chat_position != position:
            self.settings.chat_position = position
            self._save_settings_quietly()

    def _save_settings_quietly(self) -> None:
        try:
            self.settings.save()
        except OSError:
            pass

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._position_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "_overlay"):
            return
        content_w = self.width() - 2 * SHADOW
        content_h = self.height() - 2 * SHADOW
        self._overlay.setGeometry(0, 0, content_w, content_h)
        self._drawer.setFixedHeight(content_h)
        if self._drawer_anim.state() != QPropertyAnimation.Running:
            self._drawer.move(
                -DRAWER_W if not self._drawer.isVisible() else 0, 0
            )
        self._position_toast()
        self._update_bubble_widths()

    # ------------------------------------------------------------------
    # 顶部 / 历史
    # ------------------------------------------------------------------
    def _refresh_header(self) -> None:
        model_label = MODEL_SHORT.get(self.settings.model, self.settings.model)
        if not self.settings.has_key():
            subtitle = "还没填 API Key · 点 ⚙ 设置"
        elif self.settings.thinking:
            subtitle = model_label + " · 深度思考"
        else:
            subtitle = model_label + " · 普通对话"
        self._header.set_subtitle(subtitle)
        self._composer.set_thinking(
            self.settings.thinking, self.settings.reasoning_effort
        )

    def _refresh_history(self) -> None:
        conversations = self.store.list_conversations()
        self._drawer.set_data(
            conversations,
            self._conversation.id if self._conversation is not None else None,
        )

    def _toggle_drawer(self, opened: Optional[bool] = None) -> None:
        if opened is None:
            opened = self._drawer.x() < 0
        content_w = self.width() - 2 * SHADOW
        content_h = self.height() - 2 * SHADOW
        if opened:
            self._refresh_history()
            self._overlay.setGeometry(0, 0, content_w, content_h)
            self._overlay.show()
            self._overlay.raise_()
            self._drawer.show()
            self._drawer.raise_()
            target = QPoint(0, 0)
        else:
            target = QPoint(-DRAWER_W, 0)
            self._overlay.hide()
        self._drawer_anim.stop()
        self._drawer_anim.setStartValue(self._drawer.pos())
        self._drawer_anim.setEndValue(target)
        self._drawer_anim.start()

    def _on_drawer_anim_done(self) -> None:
        if self._drawer.x() < 0:
            self._drawer.hide()
            self._overlay.hide()

    def _open_conversation(self, conv_id: str) -> None:
        if self._busy:
            self._show_toast("等小鲸鱼说完再切换吧～")
            return
        conversation = self.store.get(conv_id)
        if conversation is None:
            self._refresh_history()
            self._show_toast("这段对话找不到了")
            return
        self._conversation = conversation
        self._render_conversation()
        self._refresh_history()
        self._toggle_drawer(False)

    def _new_chat(self) -> None:
        if self._busy:
            self._show_toast("等小鲸鱼说完再开新对话吧～")
            return
        self._conversation = None
        self._render_conversation()
        self._refresh_history()
        self._toggle_drawer(False)
        self._composer.input.setFocus()

    def _delete_conversation(self, conv_id: str) -> None:
        if self._busy:
            self._show_toast("等小鲸鱼说完再删除吧～")
            return
        conversation = self.store.get(conv_id)
        if conversation is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle("删除对话")
        box.setText('要删除「%s」吗？\n删除后就找不回来了。' % conversation.title)
        box.setIcon(QMessageBox.NoIcon)
        box.setStyleSheet(
            """
            QMessageBox { background:#FFFFFF; }
            QLabel { color:#3B4668; font-size:13px; }
            QPushButton {
                background:#F4F6FF; color:#5A6488; border:1px solid #E1E7FF;
                border-radius:8px; padding:5px 16px; min-width:64px;
            }
            QPushButton:hover { background:#EAEEFF; color:#5460FF; }
            """
        )
        delete_button = box.addButton("删除", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is not delete_button:
            return
        self.store.delete(conv_id)
        if self._conversation is not None and self._conversation.id == conv_id:
            self._conversation = None
            self._render_conversation()
        self._refresh_history()
        self._show_toast("已删除这段对话")

    def _rename_conversation(self, conv_id: str) -> None:
        conversation = self.store.get(conv_id)
        if conversation is None:
            return
        from PyQt5.QtWidgets import QInputDialog

        title, ok = QInputDialog.getText(
            self, "重命名对话", "新标题：", text=conversation.title
        )
        if not ok:
            return
        updated = self.store.rename(conv_id, title)
        if updated is not None:
            if self._conversation is not None and self._conversation.id == conv_id:
                self._conversation = updated
            self._refresh_history()

    # ------------------------------------------------------------------
    # 消息渲染
    # ------------------------------------------------------------------
    def _clear_messages(self) -> None:
        while self._messages_layout.count() > 1:
            item = self._messages_layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._bubbles = []
        self._rows = []
        self._active_bubble = None

    def _render_conversation(self) -> None:
        self._clear_messages()
        conversation = self._conversation
        if conversation is None or not conversation.messages:
            self._stack.setCurrentWidget(self._empty)
            return
        self._stack.setCurrentWidget(self._scroll)
        for message in conversation.messages:
            self._add_bubble(
                message.role if message.role in ("user", "assistant") else "assistant",
                message.content,
                message.reasoning,
                message.error,
                message.cancelled,
            )
        self._update_bubble_widths()
        self._scroll_to_bottom(force=True)

    def _add_bubble(
        self,
        role: str,
        text: str = "",
        reasoning: str = "",
        error: str = "",
        cancelled: bool = False,
        streaming: bool = False,
    ) -> MessageBubble:
        bubble = MessageBubble(
            role, text, reasoning, error, cancelled, parent=self._canvas
        )
        bubble.set_streaming(streaming)
        bubble.height_changed.connect(self._on_bubble_height_changed)

        row = QWidget(self._canvas)
        row.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        if role == "assistant":
            avatar = WhaleAvatar(28, row)
            row_layout.addWidget(avatar, 0, Qt.AlignTop)
            row_layout.addWidget(bubble, 0, Qt.AlignTop)
            row_layout.addStretch(1)
        else:
            row_layout.addStretch(1)
            row_layout.addWidget(bubble, 0, Qt.AlignTop)

        self._messages_layout.addWidget(row)
        self._rows.append(row)
        self._bubbles.append(bubble)
        self._stack.setCurrentWidget(self._scroll)
        self._update_bubble_widths()
        self._scroll_to_bottom(force=True)
        return bubble

    def _update_bubble_widths(self) -> None:
        viewport = self._scroll.viewport().width()
        if viewport < 220:
            viewport = self.width() - 2 * SHADOW - 24
        max_width = max(220.0, min(350.0, viewport * 0.80))
        for bubble in self._bubbles:
            bubble.set_max_width(max_width)

    def _on_bubble_height_changed(self) -> None:
        pass

    def _scroll_to_bottom(self, force: bool = False) -> None:
        bar = self._scroll.verticalScrollBar()
        if force or bar.value() >= bar.maximum() - 60:
            QTimer.singleShot(0, self._do_scroll_to_bottom)

    def _do_scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ------------------------------------------------------------------
    # 发送 / 流式
    # ------------------------------------------------------------------
    def _on_send_clicked(self) -> None:
        if self._busy:
            self._stop_streaming()
            return
        text = self._composer.input.toPlainText().strip()
        if not text:
            return
        self._send_text(text)

    def _send_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text or self._busy:
            return
        if not self.settings.has_key():
            self._show_toast("先填一下 API Key，我们才能聊天呀～")
            self._open_settings()
            return

        self._composer.input.clear()
        self._composer.input.setFocus()
        if self._conversation is None:
            self._conversation = Conversation()
        conversation = self._conversation
        conversation.add("user", text)
        self._store_save(conversation)
        self._stack.setCurrentWidget(self._scroll)
        self._add_bubble("user", text)
        self._refresh_history()

        self._active_conversation = conversation
        self._active_bubble = self._add_bubble("assistant", streaming=True)
        self._delta_content = ""
        self._delta_reasoning = ""
        self._set_busy(True)
        self._pet_thinking(True)

        messages = build_messages(self.settings, conversation)
        snapshot = Settings.from_dict(self.settings.to_dict())
        worker = ChatWorker(snapshot, messages)
        worker.delta.connect(self._on_delta)
        worker.reasoning.connect(self._on_reasoning)
        worker.completed.connect(self._on_completed)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()
        self._flush_timer.start()

    def _store_save(self, conversation: Conversation) -> None:
        try:
            self.store.save(conversation)
        except OSError as exc:
            self._show_toast("保存对话失败：%s" % exc)

    def _on_delta(self, piece: str) -> None:
        if self.sender() is not self._worker:
            return
        self._delta_content += piece

    def _on_reasoning(self, piece: str) -> None:
        if self.sender() is not self._worker:
            return
        self._delta_reasoning += piece

    def _flush_stream(self) -> None:
        bubble = self._active_bubble
        if bubble is None:
            return
        changed = False
        if self._delta_reasoning:
            bubble.append_reasoning(self._delta_reasoning)
            self._delta_reasoning = ""
            changed = True
        if self._delta_content:
            bubble.append_text(self._delta_content)
            self._delta_content = ""
            changed = True
        if changed:
            self._scroll_to_bottom()
        else:
            bubble.update()

    def _on_completed(
        self,
        content: str,
        reasoning: str,
        usage: dict,
        cancelled: bool,
    ) -> None:
        worker = self.sender()
        if worker is not self._worker:
            return
        self._flush_timer.stop()
        self._flush_stream()

        bubble = self._active_bubble
        error_text = ""
        if cancelled and not content and not reasoning:
            error_text = "已经停下了，这次没有收到回答。"
        elif not content and not reasoning:
            error_text = "这次没有收到内容，再试一次吧。"
        if bubble is not None:
            bubble.finish(content, reasoning, cancelled)
            if error_text:
                bubble.set_error(error_text)

        conversation = self._active_conversation
        if conversation is not None:
            conversation.add(
                "assistant",
                content,
                reasoning=reasoning,
                error=error_text,
                cancelled=cancelled,
            )
            self._store_save(conversation)
            self._refresh_history()

        self._active_bubble = None
        self._active_conversation = None
        self._worker = None
        self._set_busy(False)
        self._pet_thinking(False)
        if content:
            self._pet_say(plain_excerpt(content, 40))
            self._pet_celebrate()
        if cancelled:
            self._show_toast("已停止，已经说出来的部分保留下来了")
        self._scroll_to_bottom()

    def _on_failed(self, message: str) -> None:
        worker = self.sender()
        if worker is not self._worker:
            return
        self._flush_timer.stop()
        self._flush_stream()

        bubble = self._active_bubble
        partial = bubble.text if bubble is not None else ""
        partial_reasoning = bubble.reasoning if bubble is not None else ""
        merged = ""
        if partial.strip():
            merged = partial.rstrip() + "\n\n---\n⚠ " + message
            bubble.finish(merged, partial_reasoning, False)
        elif bubble is not None:
            bubble.set_error(message)

        conversation = self._active_conversation
        if conversation is not None:
            if merged:
                conversation.add(
                    "assistant",
                    merged,
                    reasoning=partial_reasoning,
                )
            else:
                conversation.add(
                    "assistant", "", error=message, cancelled=False
                )
            self._store_save(conversation)
            self._refresh_history()

        self._active_bubble = None
        self._active_conversation = None
        self._worker = None
        self._set_busy(False)
        self._pet_thinking(False)
        self._pet_say("呜…好像连不上了")
        self._show_toast("发送失败，看看网络或设置里的 API Key")
        self._scroll_to_bottom()

    def _stop_streaming(self) -> None:
        worker = self._worker
        if worker is None:
            return
        self._composer.set_busy(True)
        self._composer.send_button.setEnabled(False)
        worker.cancel()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._composer.set_busy(busy)
        self._composer.send_button.setEnabled(True)
        self._composer.input.setReadOnly(False)

    # ------------------------------------------------------------------
    # 设置 / 深度思考
    # ------------------------------------------------------------------
    def _open_settings(self) -> None:
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(self.settings, self)
        dialog.saved.connect(self._on_settings_saved)
        self._settings_dialog = dialog
        dialog.exec_()
        self._settings_dialog = None

    def _on_settings_saved(self) -> None:
        dialog = self._settings_dialog
        if dialog is None or dialog.result_settings is None:
            return
        self.settings = dialog.result_settings
        self._refresh_header()
        self._empty.set_key_missing(not self.settings.has_key())
        self._show_toast("设置已保存～")

    def _toggle_thinking(self) -> None:
        self.settings.thinking = not self.settings.thinking
        self._save_settings_quietly()
        self._refresh_header()
        self._show_toast(
            "深度思考已打开，小鲸鱼会先想一想再答"
            if self.settings.thinking
            else "已切到普通对话，回答会更快"
        )

    # ------------------------------------------------------------------
    # 桌宠联动
    # ------------------------------------------------------------------
    def _pet_thinking(self, on: bool) -> None:
        pet = self._pet
        if pet is not None and hasattr(pet, "set_thinking"):
            try:
                pet.set_thinking(on)
            except Exception:
                pass

    def _pet_say(self, text: str) -> None:
        pet = self._pet
        if pet is not None and hasattr(pet, "say"):
            try:
                pet.say(text, 3.4)
            except Exception:
                pass

    def _pet_celebrate(self) -> None:
        pet = self._pet
        if pet is not None and hasattr(pet, "celebrate"):
            try:
                pet.celebrate()
            except Exception:
                pass

    def notify_pet_closed(self) -> None:
        self._pet_thinking(False)

    # ------------------------------------------------------------------
    # 提示条
    # ------------------------------------------------------------------
    def _show_toast(self, text: str) -> None:
        self._toast.setText(text)
        self._toast.adjustSize()
        self._position_toast()
        self._toast.show()
        self._toast.raise_()
        self._toast_timer.start(2800)

    def _hide_toast(self) -> None:
        self._toast.hide()

    def _position_toast(self) -> None:
        width = self.width() - 2 * SHADOW
        height = self.height() - 2 * SHADOW
        hint = self._toast.sizeHint()
        toast_w = min(width - 50, max(150, hint.width() + 36))
        self._toast.setFixedWidth(toast_w)
        self._toast.adjustSize()
        toast_h = max(28, self._toast.height())
        x = (width - toast_w) // 2
        y = height - COMPOSER_H - toast_h - 12
        self._toast.move(x, y)

    # ------------------------------------------------------------------
    # 窗口事件
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        panel = QRectF(
            SHADOW,
            SHADOW,
            self.width() - 2 * SHADOW,
            self.height() - 2 * SHADOW,
        )
        for spread, alpha in ((8, 10), (5, 16), (2, 24)):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(30, 38, 70, alpha))
            painter.drawRoundedRect(
                panel.adjusted(-spread, -spread + 2, spread, spread + 2),
                RADIUS + spread,
                RADIUS + spread,
            )
        painter.setPen(QPen(QColor("#E1E7FF"), 1.0))
        painter.setBrush(QColor(WHITE))
        painter.drawRoundedRect(panel, RADIUS, RADIUS)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            if self._drawer.isVisible():
                self._toggle_drawer(False)
            else:
                self.hide()
            event.accept()
            return
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_N:
                self._new_chat()
                event.accept()
                return
            if event.key() == Qt.Key_Comma:
                self._open_settings()
                event.accept()
                return
        super().keyPressEvent(event)

    def hideEvent(self, event) -> None:
        self._drawer_anim.stop()
        self._drawer.hide()
        self._overlay.hide()
        self._save_position()
        self.notify_pet_closed()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()

    def shutdown(self) -> None:
        self._flush_timer.stop()
        worker = self._worker
        if worker is not None:
            try:
                worker.delta.disconnect()
                worker.reasoning.disconnect()
                worker.completed.disconnect()
                worker.failed.disconnect()
            except TypeError:
                pass
            worker.cancel()
            worker.wait(2000)
            self._worker = None
        if self._settings_dialog is not None:
            self._settings_dialog.close()
        self._save_position()


class _Overlay(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.ArrowCursor)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        event.accept()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 24, 48, 52))
        painter.drawRoundedRect(
            QRectF(0, 0, self.width(), self.height()), RADIUS, RADIUS
        )


__all__ = ["ChatWindow", "MessageBubble", "SettingsDialog"]


def main() -> None:
    """单独调试聊天窗（正式使用还是从桌宠打开）。"""
    if hasattr(QApplication, "setAttribute"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("DeepSeek Whale Pet Chat")
    window = ChatWindow()
    window.open_window()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
