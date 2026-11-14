# -*- coding: utf-8 -*-
"""
生成 README 用的聊天界面预览图（开发用，不需要 API Key）。

运行：
    $env:QT_QPA_PLATFORM="offscreen"
    $env:QT_QPA_FONTDIR="C:\\Windows\\Fonts"
    .\\.venv\\Scripts\\python.exe render_chat_preview.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ["WHALE_PET_DATA_DIR"] = tempfile.mkdtemp(prefix="whale-preview-")

from PyQt5.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt5.QtGui import (  # noqa: E402
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from whale3d import get_renderer  # noqa: E402
from whale_chat import ChatWindow, SettingsDialog  # noqa: E402
from whale_config import Settings  # noqa: E402
from whale_store import ConversationStore  # noqa: E402

CODE_ANSWER = """好呀～快速排序的核心是「选基准、分区、递归」。

```python
def quick_sort(items):
    if len(items) <= 1:
        return items
    pivot = items[0]
    left = [x for x in items[1:] if x < pivot]
    right = [x for x in items[1:] if x >= pivot]
    return quick_sort(left) + [pivot] + quick_sort(right)
```

平均时间复杂度是 **O(n log n)**，最坏会退化成 O(n²)。
想更稳的话，可以随机选基准～"""

CODE_REASONING = (
    "用户想要快速排序的实现和思路。先解释基准与分区的直觉，"
    "再给一段容易读的 Python 代码，最后补充复杂度和实用建议。"
)

TRAVEL_ANSWER = """如果不想人挤人，我会推荐这三处～

1. **茅家埠**：西湖西边的小众水域，傍晚散步很舒服
2. **宝石山**：爬二十分钟就能俯瞰西湖，比断桥清净多了
3. **小河直街**：老巷子 + 咖啡店，适合慢慢逛

小鲸鱼提醒：周末景区地铁会比较挤，尽量早点出门呀～"""

JOKE_ANSWER = """为什么小鲸鱼从来不上岸？

……因为它怕自己被晒成「鲸鱼干」呀～ 🐳"""


def seed_conversations() -> None:
    settings = Settings()
    settings.api_key = "sk-demo-1234567890abcdef"
    settings.save()

    store = ConversationStore()
    now = time.time()

    code = store.create()
    code.title = "帮我写一个 Python 快速排序"
    code.add("user", "帮我写个 Python 快速排序，讲讲思路～")
    code.add(
        "assistant",
        CODE_ANSWER,
        reasoning=CODE_REASONING,
    )
    code.updated_at = now
    store.save(code)

    travel = store.create()
    travel.title = "周末去杭州，有不太挤的地方吗"
    travel.add("user", "周末去杭州玩，有什么不太挤的地方推荐吗？")
    travel.add("assistant", TRAVEL_ANSWER)
    travel.updated_at = now - 3600
    store.save(travel)

    joke = store.create()
    joke.title = "讲个冷笑话"
    joke.add("user", "讲个冷笑话")
    joke.add("assistant", JOKE_ANSWER)
    joke.updated_at = now - 86400 - 1800
    store.save(joke)


def desktop_background(width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor("#E8EFFB"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)

    gradient = QLinearGradient(0, 0, width, height)
    gradient.setColorAt(0.0, QColor("#DCE8FB"))
    gradient.setColorAt(0.5, QColor("#EEF3FC"))
    gradient.setColorAt(1.0, QColor("#F8FBFF"))
    painter.fillRect(0, 0, width, height, gradient)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 60))
    painter.drawEllipse(QPointF(width * 0.82, height * 0.16), 250, 190)
    painter.setBrush(QColor(84, 96, 255, 16))
    painter.drawEllipse(QPointF(width * 0.12, height * 0.82), 280, 210)
    painter.setBrush(QColor(89, 255, 255, 26))
    painter.drawEllipse(QPointF(width * 0.55, height * 0.95), 320, 180)
    painter.end()
    return image


def place_pet(canvas: QImage, center_x: int, center_y: int, size: int) -> None:
    image = get_renderer().render(size, 0.0, 1.5, 1.04, dpr=1.0)
    if image.isNull():
        return
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawImage(
        QRectF(
            center_x - size / 2.0,
            center_y - size / 2.0,
            float(size),
            float(size),
        ),
        image,
    )
    painter.end()


def compose(window_image, pet: bool = True) -> QImage:
    width, height = 760, 720
    canvas = desktop_background(width, height)
    if pet:
        place_pet(canvas, 596, 494, 330)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    if isinstance(window_image, QPixmap):
        painter.drawPixmap(60, 48, window_image)
    else:
        painter.drawImage(60, 48, window_image)
    painter.end()
    return canvas


def main() -> None:
    app = QApplication([])
    seed_conversations()

    window = ChatWindow()
    window.open_window()
    QTest.qWait(280)

    chat = compose(window.grab())
    chat.save(str(ROOT / "preview_chat.png"))

    window._drawer.set_data(
        window.store.list_conversations(),
        window._conversation.id if window._conversation else None,
    )
    window._toggle_drawer(True)
    QTest.qWait(320)
    history = compose(window.grab(), pet=False)
    history.save(str(ROOT / "preview_chat_history.png"))
    window._toggle_drawer(False)
    QTest.qWait(260)

    dialog = SettingsDialog(window.settings, window)
    dialog._data_label.setText(
        "数据目录：whale_pet\\data（用户目录不可写，已自动切换）"
    )
    dialog.show()
    QTest.qWait(180)
    settings_image = QImage(600, 760, QImage.Format_ARGB32_Premultiplied)
    settings_image.fill(QColor("#EEF3FC"))
    painter = QPainter(settings_image)
    painter.fillRect(0, 0, 600, 760, QColor("#E8EFFB"))
    painter.drawPixmap(60, 50, dialog.grab())
    painter.end()
    settings_image.save(str(ROOT / "preview_chat_settings.png"))
    dialog.close()

    window.shutdown()
    print("preview_chat.png / preview_chat_history.png / preview_chat_settings.png")


if __name__ == "__main__":
    main()
