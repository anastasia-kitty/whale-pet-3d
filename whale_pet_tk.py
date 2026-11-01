# -*- coding: utf-8 -*-
"""
DeepSeek 小鲸鱼桌宠（tkinter 版，无第三方依赖）

运行：
    python whale_pet_tk.py

操作：
    - 按住左键拖动小鲸鱼
    - 右键打开菜单（回到右下角 / 退出）

说明：
    - 只使用 Python 标准库 tkinter，不需要安装 PyQt5。
    - 透明背景使用 Windows 的 -transparentcolor 色键实现；
      非 Windows 平台会退化为浅色矩形背景。
"""

import ctypes
import math
import sys
import time
import tkinter as tk

# ---------------------------------------------------------------------------
# 配色（与 PyQt5 版一致）
# ---------------------------------------------------------------------------
OUTLINE = "#59FFFF"   # H180 S65 V100
BLUE = "#5460FF"      # H236 S67 V100
WHITE = "#FFFFFF"     # H0 S0 V100

KEY_COLOR = "#FE01FE"  # 透明色键，鲸鱼身上不会出现这个颜色

# 设计稿坐标：1000 x 720
DESIGN_W = 1000
DESIGN_H = 720
DESIGN_OFFSET_Y = -135

# 桌宠窗口大小（DIP；会按系统缩放换算成实际像素）
PET_WIDTH = 320
PET_HEIGHT = 230
SCREEN_MARGIN = 20
IDLE_ANIMATION = True
FACE_LEFT = True


# ---------------------------------------------------------------------------
# Windows 辅助：DPI、工作区、屏幕判断
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    from ctypes import wintypes

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class _POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def _enable_dpi_awareness():
    """让 tkinter 按物理像素工作，避免高分屏下整窗被拉伸变糊。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _dpi_scale():
    if sys.platform == "win32":
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
            if dpi:
                return max(1.0, dpi / 96.0)
        except Exception:
            pass
        try:
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            ctypes.windll.user32.ReleaseDC(0, hdc)
            if dpi:
                return max(1.0, dpi / 96.0)
        except Exception:
            pass
    return 1.0


def _work_area():
    """返回主屏工作区（不含任务栏），单位是当前进程的屏幕像素。"""
    if sys.platform == "win32":
        rect = _RECT()
        try:
            ok = ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(rect), 0  # SPI_GETWORKAREA
            )
            if ok:
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
    return 0, 0, None, None


def _point_on_monitor(x, y):
    if sys.platform != "win32":
        return True
    try:
        hmon = ctypes.windll.user32.MonitorFromPoint(
            _POINT(int(x), int(y)), 0  # MONITOR_DEFAULTTONULL
        )
        return bool(hmon)
    except Exception:
        return True


# ---------------------------------------------------------------------------
# 鲸鱼几何：贝塞尔曲线路径
# ---------------------------------------------------------------------------
BODY = (
    ("M", 918, 548),
    ("C", 918, 430, 858, 338, 744, 306),
    ("C", 650, 280, 548, 300, 468, 344),
    ("C", 398, 383, 344, 440, 300, 482),
    ("C", 266, 514, 236, 526, 204, 523),
    ("C", 232, 558, 274, 584, 330, 608),
    ("C", 428, 650, 540, 692, 654, 702),
    ("C", 770, 712, 857, 667, 892, 606),
    ("C", 902, 588, 912, 568, 918, 548),
    ("Z",),
)

# 专门给 tkinter 的白肚皮：外缘略往身体内部收，避免没有裁剪时露到身体外。
BELLY = (
    ("M", 915, 545),
    ("C", 905, 620, 858, 678, 775, 700),
    ("C", 665, 698, 540, 686, 420, 650),
    ("C", 365, 632, 315, 607, 265, 582),
    ("C", 335, 604, 425, 625, 530, 635),
    ("C", 655, 655, 775, 645, 840, 606),
    ("C", 878, 585, 905, 560, 915, 545),
    ("Z",),
)

DORSAL_FIN = (
    ("M", 565, 368),
    ("C", 550, 322, 528, 282, 495, 252),
    ("C", 492, 292, 480, 328, 458, 365),
    ("C", 492, 354, 528, 358, 565, 368),
    ("Z",),
)

TAIL_UPPER = (
    ("M", 252, 518),
    ("C", 218, 468, 168, 430, 108, 418),
    ("C", 122, 470, 154, 514, 208, 546),
    ("C", 228, 540, 244, 532, 252, 518),
    ("Z",),
)

TAIL_LOWER = (
    ("M", 238, 546),
    ("C", 200, 598, 154, 638, 100, 656),
    ("C", 116, 604, 156, 558, 210, 528),
    ("C", 222, 534, 233, 542, 238, 546),
    ("Z",),
)

PECTORAL_FIN = (
    ("M", 600, 688),
    ("C", 582, 730, 545, 768, 482, 806),
    ("C", 458, 770, 466, 724, 495, 689),
    ("C", 528, 664, 568, 666, 600, 688),
    ("Z",),
)

MOUTH = (
    ("M", 752, 625),
    ("C", 785, 648, 828, 649, 862, 624),
)

EYE_CENTER = (810, 458)
EYE_RADII = (60, 78)
EYE_ANGLE = 18.0

CHEEK_CENTER = (840, 578)
CHEEK_RADII = (16, 18)


def sample_path(commands, steps=20):
    """把 M/C/Z 路径采样成折线点列表。"""
    points = []
    current = (0.0, 0.0)
    start = None

    for command in commands:
        op = command[0]
        if op == "M":
            current = (float(command[1]), float(command[2]))
            start = current
            points.append(current)
        elif op == "C":
            p0 = current
            p1 = (float(command[1]), float(command[2]))
            p2 = (float(command[3]), float(command[4]))
            p3 = (float(command[5]), float(command[6]))
            for i in range(1, steps + 1):
                t = i / float(steps)
                mt = 1.0 - t
                x = (
                    mt * mt * mt * p0[0]
                    + 3.0 * mt * mt * t * p1[0]
                    + 3.0 * mt * t * t * p2[0]
                    + t * t * t * p3[0]
                )
                y = (
                    mt * mt * mt * p0[1]
                    + 3.0 * mt * mt * t * p1[1]
                    + 3.0 * mt * t * t * p2[1]
                    + t * t * t * p3[1]
                )
                points.append((x, y))
            current = p3
        elif op == "Z":
            if start is not None and (not points or points[-1] != start):
                points.append(start)

    return points


def ellipse_points(center, radii, angle=0.0, steps=56):
    cx, cy = center
    rx, ry = radii
    a = math.radians(angle)
    ca, sa = math.cos(a), math.sin(a)
    result = []
    for i in range(steps):
        t = math.tau * i / steps
        x = rx * math.cos(t)
        y = ry * math.sin(t)
        result.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    result.append(result[0])
    return result


def rotate_points(points, cx, cy, angle_deg):
    if not angle_deg:
        return points
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    result = []
    for x, y in points:
        dx, dy = x - cx, y - cy
        result.append((cx + dx * ca - dy * sa, cy + dx * sa + dy * ca))
    return result


# ---------------------------------------------------------------------------
# 桌宠
# ---------------------------------------------------------------------------
class WhalePet:
    def __init__(self):
        _enable_dpi_awareness()

        self.dpi_scale = _dpi_scale()
        self.width = int(math.ceil(PET_WIDTH * self.dpi_scale))
        self.height = int(math.ceil(PET_HEIGHT * self.dpi_scale))
        self.margin = int(round(SCREEN_MARGIN * self.dpi_scale))
        self.alive = True
        self._drag_dx = 0
        self._drag_dy = 0
        self._last_bob = 0.0
        self._start_time = time.perf_counter()
        self._tick_id = None
        self._fade_id = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("DeepSeek 小鲸鱼桌宠")
        self.root.overrideredirect(True)
        try:
            self.root.attributes("-topmost", True)
            self.root.attributes("-toolwindow", True)
        except tk.TclError:
            pass

        self.canvas = tk.Canvas(
            self.root,
            width=self.width,
            height=self.height,
            bg=KEY_COLOR,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.canvas.pack()

        self.transparent = True
        try:
            self.root.attributes("-transparentcolor", KEY_COLOR)
        except tk.TclError:
            # 非 Windows 或 Tk 不支持色键透明时的降级方案
            self.transparent = False
            self.canvas.configure(bg="#EEF3FF")
            self.root.configure(bg="#EEF3FF")

        self.draw_scale = min(self.width / DESIGN_W, self.height / DESIGN_H)
        self.offset_x = (self.width - DESIGN_W * self.draw_scale) / 2.0
        self.offset_y = (self.height - DESIGN_H * self.draw_scale) / 2.0
        self.outline_width = max(1, int(round(15.0 * self.draw_scale)))
        self.mouth_width = max(1, int(round(9.0 * self.draw_scale)))

        self.body_points = sample_path(BODY, 20)
        self.belly_points = sample_path(BELLY, 20)
        self.dorsal_points = sample_path(DORSAL_FIN, 18)
        self.tail_upper_points = sample_path(TAIL_UPPER, 18)
        self.tail_lower_points = sample_path(TAIL_LOWER, 18)
        self.pectoral_points = sample_path(PECTORAL_FIN, 18)
        self.mouth_points = sample_path(MOUTH, 22)
        self.eye_points = ellipse_points(
            EYE_CENTER, EYE_RADII, EYE_ANGLE, 56
        )

        self._build_items()
        self._build_menu()
        self._bind_events()
        self._place_bottom_right()

        try:
            self.root.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self.root.deiconify()
        self._fade_id = self.root.after(20, self._fade_in, 0)
        self._tick_id = self.root.after(0, self._tick)

    # ---- 坐标换算 ------------------------------------------------------
    def _screen(self, points, bob=0.0):
        result = []
        s = self.draw_scale
        ox = self.offset_x
        oy = self.offset_y
        for x, y in points:
            if FACE_LEFT:
                x = DESIGN_W - x
            result.append(ox + x * s)
            result.append(oy + (y + DESIGN_OFFSET_Y + bob) * s)
        return result

    def _oval_coords(self, center, radii, bob=0.0):
        cx, cy = center
        rx, ry = radii
        x0, y0 = self._screen([(cx - rx, cy - ry)], bob)
        x1, y1 = self._screen([(cx + rx, cy + ry)], bob)
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]

    def _coords(self, item, points, bob=0.0):
        self.canvas.coords(item, *self._screen(points, bob))

    # ---- 创建画布元素 --------------------------------------------------
    def _build_items(self):
        c = self.canvas
        ow = self.outline_width
        tag = ("bob",)

        theme = dict(fill=BLUE, outline=OUTLINE, width=ow)
        self.tail_upper_item = c.create_polygon(0, 0, 1, 1, 2, 2, **theme)
        self.tail_lower_item = c.create_polygon(0, 0, 1, 1, 2, 2, **theme)

        self.dorsal_item = c.create_polygon(
            0, 0, 1, 1, 2, 2, **theme, tags=tag
        )

        self.pectoral_item = c.create_polygon(0, 0, 1, 1, 2, 2, **theme)

        self.body_item = c.create_polygon(
            0, 0, 1, 1, 2, 2, fill=BLUE, outline="", tags=tag
        )
        self.belly_item = c.create_polygon(
            0, 0, 1, 1, 2, 2, fill=WHITE, outline="", tags=tag
        )
        self.body_outline_item = c.create_line(
            0,
            0,
            1,
            1,
            fill=OUTLINE,
            width=ow,
            capstyle=tk.ROUND,
            joinstyle=tk.ROUND,
            tags=tag,
        )

        self.eye_item = c.create_polygon(
            0, 0, 1, 1, 2, 2, fill=WHITE, outline="", tags=tag
        )
        self.cheek_item = c.create_oval(
            0, 0, 1, 1, fill=WHITE, outline="", tags=tag
        )
        self.mouth_item = c.create_line(
            0,
            0,
            1,
            1,
            fill=OUTLINE,
            width=self.mouth_width,
            capstyle=tk.ROUND,
            tags=tag,
        )

        # 初始化静态元素
        self._coords(self.dorsal_item, self.dorsal_points)
        self._coords(self.body_item, self.body_points)
        self._coords(self.belly_item, self.belly_points)
        self._coords(self.body_outline_item, self.body_points)
        self._coords(self.eye_item, self.eye_points)
        self.canvas.coords(
            self.cheek_item, *self._oval_coords(CHEEK_CENTER, CHEEK_RADII)
        )
        self._coords(self.mouth_item, self.mouth_points)

    # ---- 动画 ----------------------------------------------------------
    def _tick(self):
        if not self.alive:
            return
        phase = time.perf_counter() - self._start_time

        if IDLE_ANIMATION:
            bob = math.sin(phase * math.tau / 3.6) * 4.0
            tail_angle = math.sin(phase * math.tau / 2.8) * 4.5
            fin_angle = math.sin(phase * math.tau / 3.1 + 0.8) * 3.0
        else:
            bob = 0.0
            tail_angle = 0.0
            fin_angle = 0.0

        # 身体组整体上下平移，比每帧重算全部坐标省 CPU
        dy = (bob - self._last_bob) * self.draw_scale
        if abs(dy) > 0.001:
            self.canvas.move("bob", 0, dy)
            self._last_bob = bob

        tail_up = rotate_points(self.tail_upper_points, 245, 530, tail_angle)
        tail_low = rotate_points(self.tail_lower_points, 245, 530, tail_angle)
        self._coords(self.tail_upper_item, tail_up, bob)
        self._coords(self.tail_lower_item, tail_low, bob)

        pectoral = rotate_points(self.pectoral_points, 590, 680, fin_angle)
        self._coords(self.pectoral_item, pectoral, bob)

        self._tick_id = self.root.after(33, self._tick)

    # ---- 窗口位置/拖动 ------------------------------------------------
    def _place_bottom_right(self):
        left, top, right, bottom = _work_area()
        if right is None:
            right = self.root.winfo_screenwidth()
            bottom = self.root.winfo_screenheight()
        x = int(right - self.width - self.margin)
        y = int(bottom - self.height - self.margin)
        self.root.geometry(
            "%dx%d+%d+%d" % (self.width, self.height, x, y)
        )

    def _bind_events(self):
        c = self.canvas
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Button-3>", self._on_menu)

    def _on_press(self, event):
        self._drag_dx = event.x_root - self.root.winfo_x()
        self._drag_dy = event.y_root - self.root.winfo_y()
        self.canvas.configure(cursor="fleur")
        self.root.lift()
        return "break"

    def _on_drag(self, event):
        x = event.x_root - self._drag_dx
        y = event.y_root - self._drag_dy
        self.root.geometry("+%d+%d" % (x, y))
        return "break"

    def _on_release(self, event):
        self.canvas.configure(cursor="hand2")
        self._ensure_on_screen()
        return "break"

    def _ensure_on_screen(self):
        x = self.root.winfo_x() + self.width // 2
        y = self.root.winfo_y() + self.height // 2
        if not _point_on_monitor(x, y):
            self._place_bottom_right()

    # ---- 右键菜单 ------------------------------------------------------
    def _build_menu(self):
        self.menu = tk.Menu(
            self.root,
            tearoff=0,
            bg="#FFFFFF",
            fg="#3B4668",
            activebackground="#EEF1FF",
            activeforeground="#5460FF",
            bd=1,
            relief="solid",
        )
        self.menu.add_command(
            label="回到右下角", command=self._place_bottom_right
        )
        self.menu.add_separator()
        self.menu.add_command(label="退出小鲸鱼", command=self._quit)

    def _on_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)
        return "break"

    # ---- 淡入/退出 -----------------------------------------------------
    def _fade_in(self, step):
        if not self.alive:
            return
        try:
            self.root.attributes("-alpha", min(1.0, step / 18.0))
        except tk.TclError:
            return
        if step < 18:
            self._fade_id = self.root.after(16, self._fade_in, step + 1)

    def _quit(self):
        self.alive = False
        for attr in ("_tick_id", "_fade_id"):
            after_id = getattr(self, attr, None)
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self):
        self.root.mainloop()


def main():
    pet = WhalePet()
    pet.run()


if __name__ == "__main__":
    main()
