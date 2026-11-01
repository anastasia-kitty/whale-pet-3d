# -*- coding: utf-8 -*-
"""
程序化 3D 小鲸鱼模型与软件渲染器。

不依赖 OpenGL、numpy 或外部模型文件：
  1. 用参数曲面生成水滴形身体、白肚皮、眼斑、微笑和鳍；
  2. 自己完成旋转、透视投影、背面剔除、Toon 光照和深度排序；
  3. 用 QPainter 把三角形画到透明 QImage 上。

因此只要装了 PyQt5，就能在普通 Windows 电脑上运行。
"""

from __future__ import annotations

import math
from collections import OrderedDict
from typing import Dict, List, Optional, Sequence, Tuple

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPolygonF, QRadialGradient

# ---------------------------------------------------------------------------
# 配色（严格使用设定图颜色）
# ---------------------------------------------------------------------------
BLUE = (0x54, 0x60, 0xFF)       # H236 S67 V100  填充蓝色
WHITE = (0xFF, 0xFF, 0xFF)      # H0   S0  V100  填充白色
CYAN = (0x59, 0xFF, 0xFF)       # H180 S65 V100  勾线蓝色
BLACK = (0x05, 0x06, 0x0A)      # 眼睛黑色

Vec3 = Tuple[float, float, float]
Vec2 = Tuple[float, float]

# 身体坐标：y 为头尾方向（头在 -y），x 为左右，z 为上。
# 新版比例：头部接近球形并占身体的一半，后半段圆润收窄成水滴形。
HEAD_Y = -1.02
TAIL_Y = 1.04
BODY_LEN = TAIL_Y - HEAD_Y
HEAD_Q = 0.3573            # 保持头部物理长度不变（0.736），缩短的是后半身
BODY_WIDTH = 0.660         # 最宽处半宽
BODY_TOP = 0.680           # 最宽处上半高
BODY_BOTTOM = 0.610        # 最宽处下半高

# 以下偏移量以“鼻尖为 0”的物理长度计。
# 以后调整 BODY_LEN 时，眼斑、嘴巴和鳍会自动换算回相同的位置。
EYE_Q_OFFSET = 0.207
EYE_Q_SIZE = 0.0805
EYE_Q_SHEAR = -0.184
MOUTH_WIDTH = 0.270          # 微笑线半宽
MOUTH_CENTER_Z = -0.125      # 微笑线最低点
MOUTH_LIFT = 0.060           # 嘴角比最低点高多少

PUPIL_CENTER_X = 0.300       # 黑色眼睛中心距面部中线的距离
PUPIL_CENTER_Z = 0.110       # 黑色眼睛高度
PUPIL_RADIUS = 0.045         # 黑色眼睛半径

SNOUT_WIDTH = 0.150          # 吻部青色小弧线半宽
SNOUT_CENTER_Z = 0.060       # 弧线中心高度
SNOUT_DROP = 0.020           # 两端比中心低多少

MUZZLE_WIDTH = 0.285         # 蓝色吻部贴片半宽
MUZZLE_TOP_Z = 0.095         # 贴片上边缘高度
DORSAL_OFFSET = 1.0465
PECTORAL_OFFSET = 0.5865

# 相机 / 投影
CAMERA_POS: Vec3 = (0.0, -5.65, 0.92)
CAMERA_TARGET: Vec3 = (0.0, 0.02, 0.10)
WORLD_UP: Vec3 = (0.0, 0.0, 1.0)
LIGHT_DIR = (-0.48, -0.62, 0.78)
FILL_DIR = (0.55, -0.40, -0.10)

# 平滑法线需要的一点点数值微分
_EPS_Q = 0.0025
_EPS_T = 0.004


# ---------------------------------------------------------------------------
# 三维数学
# ---------------------------------------------------------------------------
def v_add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_mul(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def v_dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def v_len(a: Vec3) -> float:
    return math.sqrt(v_dot(a, a))


def v_norm(a: Vec3) -> Vec3:
    length = v_len(a)
    if length < 1e-12:
        return (0.0, 0.0, 1.0)
    return (a[0] / length, a[1] / length, a[2] / length)


def rot_z(p: Vec3, angle: float) -> Vec3:
    c = math.cos(angle)
    s = math.sin(angle)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2])


def rot_x(p: Vec3, angle: float) -> Vec3:
    c = math.cos(angle)
    s = math.sin(angle)
    return (p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c)


# ---------------------------------------------------------------------------
# 身体参数曲面
# ---------------------------------------------------------------------------
def _radial_profile(q: float) -> float:
    """
    沿头尾方向的半径包络；q=0 是鼻尖，q=1 是尾柄。

    前 34% 用椭圆头盖快速鼓起来，形成一个饱满、接近球形的大头；
    之后用一条前端平滑、尾部渐渐收细的曲线，整体像一颗水滴，
    而不是前后对称的鱼雷。
    """
    q = min(1.0, max(0.0, q))
    if q <= HEAD_Q:
        x = (HEAD_Q - q) / HEAD_Q
        return math.sqrt(max(0.0, 1.0 - x * x))

    u = (q - HEAD_Q) / (1.0 - HEAD_Q)
    return max(0.0, (1.0 - u ** 1.70) ** 0.80)


def body_center(q: float) -> Vec3:
    q = min(1.0, max(0.0, q))
    y = HEAD_Y + BODY_LEN * q
    z = 0.012 + 0.042 * math.sin(math.pi * q) - 0.034 * q
    return (0.0, y, z)


def body_radii(q: float) -> Tuple[float, float, float]:
    """返回 (半宽, 上半高, 下半高)。"""
    r = _radial_profile(q)
    # 接近圆形的截面：宽度和高度一起放大，头看起来更圆、更呆萌
    width = BODY_WIDTH * r
    top = BODY_TOP * r
    bottom = BODY_BOTTOM * r
    return (max(0.0001, width), max(0.0001, top), max(0.0001, bottom))


def body_point(q: float, theta: float, offset: float = 0.0) -> Vec3:
    """身体表面点。theta: 0=右侧，pi/2=背，-pi/2=腹。"""
    cx, cy, cz = body_center(q)
    w, ht, hb = body_radii(q)
    st = math.sin(theta)
    x = w * math.cos(theta)
    z = cz + (ht if st >= 0.0 else hb) * st
    p = (cx + x, cy, z)
    if abs(offset) > 1e-12:
        p = v_add(p, v_mul(body_normal(q, theta), offset))
    return p


def body_normal(q: float, theta: float) -> Vec3:
    q0 = min(1.0, max(0.0, q - _EPS_Q))
    q1 = min(1.0, max(0.0, q + _EPS_Q))
    p_q0 = body_point_raw(q0, theta)
    p_q1 = body_point_raw(q1, theta)
    p_t0 = body_point_raw(q, theta - _EPS_T)
    p_t1 = body_point_raw(q, theta + _EPS_T)
    dq = v_sub(p_q1, p_q0)
    dt = v_sub(p_t1, p_t0)
    n = v_cross(dq, dt)
    if v_len(n) < 1e-9:
        # 两极退化时用从身体轴指向外的方向
        return v_norm((math.cos(theta), 0.0, math.sin(theta)))
    return v_norm(n)


def body_point_raw(q: float, theta: float) -> Vec3:
    """不做递归的法线计算版本。"""
    cx, cy, cz = body_center(q)
    w, ht, hb = body_radii(q)
    st = math.sin(theta)
    x = w * math.cos(theta)
    z = cz + (ht if st >= 0.0 else hb) * st
    return (cx + x, cy, z)


def body_top_z(q: float) -> float:
    cx, cy, cz = body_center(q)
    w, ht, hb = body_radii(q)
    return cz + ht


# ---------------------------------------------------------------------------
# 网格容器
# ---------------------------------------------------------------------------
class Mesh:
    __slots__ = (
        "name",
        "verts",
        "norms",
        "faces",
        "material",
        "two_sided",
        "outline",
        "front_only",
    )

    def __init__(
        self,
        name: str,
        verts: List[Vec3],
        norms: List[Vec3],
        faces: List[Tuple[int, int, int]],
        material: str,
        two_sided: bool = False,
        outline: bool = False,
        front_only: bool = False,
    ) -> None:
        self.name = name
        self.verts = verts
        self.norms = norms
        self.faces = faces
        self.material = material
        self.two_sided = two_sided
        self.outline = outline
        self.front_only = front_only


def _quad_faces(
    faces: List[Tuple[int, int, int]],
    a: int,
    b: int,
    c: int,
    d: int,
) -> None:
    """四边形四点按环序给出，拆成两个三角形。"""
    faces.append((a, b, c))
    faces.append((a, c, d))


# ---------------------------------------------------------------------------
# 身体
# ---------------------------------------------------------------------------
def _build_body(n_q: int = 42, n_t: int = 32) -> Mesh:
    verts: List[Vec3] = []
    norms: List[Vec3] = []
    faces: List[Tuple[int, int, int]] = []

    for i in range(n_q + 1):
        t = i / float(n_q)
        # 两端稍微加密，轮廓更圆润
        q = 0.5 - 0.5 * math.cos(math.pi * t)
        q = max(0.0004, min(0.9996, q))
        for j in range(n_t):
            theta = math.tau * j / float(n_t)
            verts.append(body_point_raw(q, theta))
            norms.append(body_normal(q, theta))

    for i in range(n_q):
        for j in range(n_t):
            j2 = (j + 1) % n_t
            a = i * n_t + j
            b = i * n_t + j2
            c = (i + 1) * n_t + j2
            d = (i + 1) * n_t + j
            _quad_faces(faces, a, b, c, d)

    # 封住鼻尖和尾尖。否则两个极点会留下针孔，青色描边底板会从
    # 鼻尖透出来，在脸中央形成一个小青点。
    nose_center = len(verts)
    _, nose_y, nose_z = body_center(0.0)
    verts.append((0.0, nose_y, nose_z))
    norms.append((0.0, -1.0, 0.0))
    for j in range(n_t):
        faces.append((nose_center, j, (j + 1) % n_t))

    tail_center = len(verts)
    _, tail_y, tail_z = body_center(1.0)
    verts.append((0.0, tail_y, tail_z))
    norms.append((0.0, 1.0, 0.0))
    last_ring = n_q * n_t
    for j in range(n_t):
        faces.append(
            (
                tail_center,
                last_ring + (j + 1) % n_t,
                last_ring + j,
            )
        )

    return Mesh("body", verts, norms, faces, "blue", False, True)


def _build_belly(n_q: int = 40, n_t: int = 30) -> Mesh:
    verts: List[Vec3] = []
    norms: List[Vec3] = []
    faces: List[Tuple[int, int, int]] = []

    # 从下巴一直包到尾巴下方；头部略宽，尾部收窄
    q_min, q_max = 0.004, 0.965
    for i in range(n_q + 1):
        u = i / float(n_q)
        q = q_min + (q_max - q_min) * u
        span = 1.30 - 0.32 * q + 0.08 * math.sin(math.pi * q)
        for j in range(n_t + 1):
            theta = -math.pi / 2.0 - span + (2.0 * span) * j / float(n_t)
            verts.append(body_point(q, theta, 0.021))
            norms.append(body_normal(q, theta))

    step = n_t + 1
    for i in range(n_q):
        for j in range(n_t):
            a = i * step + j
            b = i * step + j + 1
            c = (i + 1) * step + j + 1
            d = (i + 1) * step + j
            _quad_faces(faces, a, b, c, d)

    return Mesh("belly", verts, norms, faces, "white", False, False)


# ---------------------------------------------------------------------------
# 眼斑 / 嘴
# ---------------------------------------------------------------------------
def _build_eye_patch(side: int) -> Mesh:
    """side=+1 右眼，side=-1 左眼。白色八字眼斑。"""
    # 眼斑放在头部前侧，让正面能看到一对完整的白色眼斑
    q0 = EYE_Q_OFFSET / BODY_LEN
    theta0 = 0.550
    a_theta = 0.380
    b_q = EYE_Q_SIZE / BODY_LEN
    shear = EYE_Q_SHEAR / BODY_LEN

    rings = 5
    segments = 28
    center_theta = theta0 if side > 0 else math.pi - theta0
    verts: List[Vec3] = []
    norms: List[Vec3] = []
    faces: List[Tuple[int, int, int]] = []

    verts.append(body_point(q0, center_theta, 0.020))
    norms.append(body_normal(q0, center_theta))

    for r_i in range(1, rings + 1):
        r = r_i / float(rings)
        for j in range(segments):
            a = math.tau * j / float(segments)
            d_theta = a_theta * r * math.cos(a)
            d_q = b_q * r * math.sin(a) + shear * d_theta
            # 先在右脸生成完整形状，再整体镜像到左脸。
            # 不能把 d_theta 取反两次，否则左眼会变成上下翻转，
            # 正面看就会和右眼不对称。
            theta = theta0 + d_theta
            q = min(0.36, max(0.015, q0 + d_q))
            if side < 0:
                theta = math.pi - theta
            verts.append(body_point(q, theta, 0.020))
            norms.append(body_normal(q, theta))

    # 中心到第一圈
    for j in range(segments):
        a = 1 + j
        b = 1 + (j + 1) % segments
        faces.append((0, a, b))

    for r_i in range(1, rings):
        base = 1 + (r_i - 1) * segments
        nxt = 1 + r_i * segments
        for j in range(segments):
            a = base + j
            b = base + (j + 1) % segments
            c = nxt + (j + 1) % segments
            d = nxt + j
            _quad_faces(faces, a, b, c, d)

    return Mesh("eye_%d" % side, verts, norms, faces, "white", False, False)


def _front_surface_point(x: float, z: float) -> Tuple[float, float]:
    """
    已知正面的 (x, z)，求身体前表面上的 (q, theta)。

    嘴巴不再沿着鼻尖附近的 (q, theta) 参数绕圈——那里有一个半径趋近 0
    的奇点，会让微笑线在正中间折出一个尖角。这里改为先在正面的 x-z
    平面画出平滑曲线，再反求它在头部表面上的位置。
    """
    ax = abs(x)

    def residual(q: float) -> float:
        _, _, cz = body_center(q)
        w, ht, hb = body_radii(q)
        h = ht if z >= cz else hb
        return (ax / w) ** 2 + ((z - cz) / h) ** 2 - 1.0

    prev_q = 0.0002
    q_hit = 0.08
    for i in range(1, 241):
        q = 0.0002 + (0.80 - 0.0002) * i / 240.0
        if residual(q) <= 0.0:
            lo, hi = prev_q, q
            for _ in range(28):
                mid = (lo + hi) * 0.5
                if residual(mid) > 0.0:
                    lo = mid
                else:
                    hi = mid
            q_hit = (lo + hi) * 0.5
            break
        prev_q = q

    _, _, cz = body_center(q_hit)
    w, ht, hb = body_radii(q_hit)
    h = ht if z >= cz else hb
    # 先求右脸角度，再按 X 轴镜像到左脸
    theta_right = math.atan2(
        (z - cz) / h,
        ax / w if ax > 1e-9 else 0.0,
    )
    theta = theta_right if x >= 0.0 else math.pi - theta_right
    return q_hit, theta


def _make_face_ribbon(
    name: str,
    curve: List[Vec3],
    normals: List[Vec3],
    half_width: float,
    material: str,
    cap_ends: bool = False,
) -> Mesh:
    """把一条贴着面部表面的中心线变成有宽度的曲面细带。"""
    verts: List[Vec3] = []
    sides: List[Vec3] = []
    for i, p in enumerate(curve):
        p_prev = curve[max(0, i - 1)]
        p_next = curve[min(len(curve) - 1, i + 1)]
        tangent = v_norm(v_sub(p_next, p_prev))
        n = normals[i]
        side = v_norm(v_cross(n, tangent))
        if side[2] < 0:
            side = v_mul(side, -1.0)
        sides.append(side)
        verts.append(v_add(p, v_mul(side, -half_width)))
        verts.append(v_add(p, v_mul(side, half_width)))

    faces: List[Tuple[int, int, int]] = []
    for i in range(len(curve) - 1):
        a = i * 2
        b = i * 2 + 1
        c = (i + 1) * 2 + 1
        d = (i + 1) * 2
        _quad_faces(faces, a, b, c, d)

    norms_out: List[Vec3] = []
    for i in range(len(curve)):
        norms_out.append(normals[i])
        norms_out.append(normals[i])

    if cap_ends and len(curve) >= 2:
        # 圆角端帽：盖住嘴角处细带端面和蓝色吻部之间的白缝
        cap_segments = 6
        for end in (0, -1):
            p = curve[end]
            n = normals[end]
            side = sides[end]
            if end == 0:
                outward = v_norm(v_sub(curve[0], curve[1]))
            else:
                outward = v_norm(v_sub(curve[-1], curve[-2]))
            center = len(verts)
            verts.append(p)
            norms_out.append(n)
            arc_start = len(verts)
            for k in range(cap_segments + 1):
                angle = -math.pi / 2.0 + math.pi * k / cap_segments
                cap_point = v_add(
                    p,
                    v_add(
                        v_mul(outward, half_width * math.cos(angle)),
                        v_mul(side, half_width * math.sin(angle)),
                    ),
                )
                verts.append(cap_point)
                norms_out.append(n)
            for k in range(cap_segments):
                faces.append((center, arc_start + k, arc_start + k + 1))

    return Mesh(name, verts, norms_out, faces, material, False, False)


def _build_mouth(samples: int = 44, half_width: float = 0.022) -> Mesh:
    """
    一条平滑、左右对称的青色微笑线。

    在正面 x-z 平面中：
        x = width * u
        z = center_z + lift * u²
    中间低、两边高，是一条真正连续的微笑弧线；再用
    _front_surface_point 把它贴到头部表面。
    """
    curve: List[Vec3] = []
    normals: List[Vec3] = []
    for i in range(samples + 1):
        u = -1.0 + 2.0 * i / float(samples)
        x = MOUTH_WIDTH * u
        z = MOUTH_CENTER_Z + MOUTH_LIFT * u * u
        q, theta = _front_surface_point(x, z)
        curve.append(body_point(q, theta, 0.030))
        normals.append(body_normal(q, theta))

    return _make_face_ribbon(
        "mouth",
        curve,
        normals,
        half_width,
        "cyan",
        cap_ends=True,
    )


def _build_muzzle_patch(u_samples: int = 34, v_samples: int = 7) -> Mesh:
    """
    用一块贴合面部的蓝色贴片，填掉微笑线和吻部弧线之间的白色缝隙。

    贴片下边缘几乎与微笑线重合（被青色嘴巴压住），上边缘延伸到
    蓝色面部内部，因此在正面看起来就是连续的蓝色吻部；两侧在嘴角
    处收尖，不会在外侧留下一条蓝边。
    """
    verts: List[Vec3] = []
    norms: List[Vec3] = []
    faces: List[Tuple[int, int, int]] = []

    for i in range(u_samples + 1):
        u = -1.0 + 2.0 * i / float(u_samples)
        au = abs(u)
        x = MUZZLE_WIDTH * u
        z_bottom = MOUTH_CENTER_Z + MOUTH_LIFT * u * u + 0.004
        z_top = MUZZLE_TOP_Z - 0.015 * u * u

        # 只在最外侧 6% 收尖，避免蓝色贴片越过嘴角
        taper = min(1.0, max(0.0, (1.0 - au) / 0.06))
        z_top = z_bottom + (z_top - z_bottom) * taper

        for j in range(v_samples + 1):
            v = j / float(v_samples)
            z = z_bottom + (z_top - z_bottom) * v
            q, theta = _front_surface_point(x, z)
            verts.append(body_point(q, theta, 0.024))
            norms.append(body_normal(q, theta))

    row = v_samples + 1
    for i in range(u_samples):
        for j in range(v_samples):
            a = i * row + j
            b = a + 1
            c = (i + 1) * row + j + 1
            d = (i + 1) * row + j
            _quad_faces(faces, a, b, c, d)

    return Mesh("muzzle", verts, norms, faces, "blue", False, False)


def _build_snout(samples: int = 36, half_width: float = 0.009) -> Mesh:
    """
    吻部中央的青色小弧线：中间略高、两端略低，像一个很浅的拱形。

    这条线用一个小椭圆截面的细管生成，而不是平面缎带。
    拱形最高点处如果直接摊平缎带，宽度方向容易退化成一个尖点；
    细管在最高点仍然是圆的，因此整条弧线保持平滑。
    """
    curve: List[Vec3] = []
    normals: List[Vec3] = []
    for i in range(samples + 1):
        u = -1.0 + 2.0 * i / float(samples)
        x = SNOUT_WIDTH * u
        z = SNOUT_CENTER_Z - SNOUT_DROP * u * u
        q, theta = _front_surface_point(x, z)
        curve.append(body_point(q, theta, 0.032))
        normals.append(body_normal(q, theta))

    thickness = 0.0055
    ring_n = 10
    verts: List[Vec3] = []
    norms: List[Vec3] = []
    faces: List[Tuple[int, int, int]] = []

    for i, p in enumerate(curve):
        p_prev = curve[max(0, i - 1)]
        p_next = curve[min(len(curve) - 1, i + 1)]
        tangent = v_norm(v_sub(p_next, p_prev))
        n = normals[i]
        side = v_norm(v_cross(n, tangent))
        if side[2] < 0:
            side = v_mul(side, -1.0)
        for k in range(ring_n):
            a = math.tau * k / float(ring_n)
            offset = v_add(
                v_mul(side, half_width * math.cos(a)),
                v_mul(n, thickness * math.sin(a)),
            )
            verts.append(v_add(p, offset))
            norms.append(
                v_norm(
                    v_add(
                        v_mul(side, math.cos(a)),
                        v_mul(n, math.sin(a)),
                    )
                )
            )

    for i in range(samples):
        base = i * ring_n
        nxt = (i + 1) * ring_n
        for k in range(ring_n):
            a = base + k
            b = base + (k + 1) % ring_n
            c = nxt + (k + 1) % ring_n
            d = nxt + k
            _quad_faces(faces, a, b, c, d)

    # 两端封口，避免从侧面看到空心管口。
    start_center = len(verts)
    verts.append(curve[0])
    norms.append(v_norm(v_sub(curve[0], curve[1])))
    for k in range(ring_n):
        faces.append(
            (start_center, (k + 1) % ring_n, k)
        )

    end_center = len(verts)
    verts.append(curve[-1])
    norms.append(v_norm(v_sub(curve[-1], curve[-2])))
    last = samples * ring_n
    for k in range(ring_n):
        faces.append(
            (end_center, last + k, last + (k + 1) % ring_n)
        )

    return Mesh(
        "snout", verts, norms, faces, "cyan", False, False, front_only=True
    )


def _build_pupil(side: int) -> Mesh:
    """贴在蓝色面部、位于白色眼斑下方的黑色圆形眼睛。"""
    center_x = PUPIL_CENTER_X * side
    center_z = PUPIL_CENTER_Z
    radius = PUPIL_RADIUS
    rings = 3
    segments = 28

    verts: List[Vec3] = []
    norms: List[Vec3] = []
    faces: List[Tuple[int, int, int]] = []

    q, theta = _front_surface_point(center_x, center_z)
    verts.append(body_point(q, theta, 0.025))
    norms.append(body_normal(q, theta))

    for r_i in range(1, rings + 1):
        r = r_i / float(rings)
        for j in range(segments):
            a = math.tau * j / float(segments)
            x = center_x + radius * r * math.cos(a)
            z = center_z + radius * r * math.sin(a)
            q, theta = _front_surface_point(x, z)
            verts.append(body_point(q, theta, 0.025))
            norms.append(body_normal(q, theta))

    for j in range(segments):
        faces.append((0, 1 + j, 1 + (j + 1) % segments))

    for r_i in range(1, rings):
        base = 1 + (r_i - 1) * segments
        nxt = 1 + r_i * segments
        for j in range(segments):
            a = base + j
            b = base + (j + 1) % segments
            c = nxt + (j + 1) % segments
            d = nxt + j
            _quad_faces(faces, a, b, c, d)

    return Mesh("pupil_%d" % side, verts, norms, faces, "black", False, False)


# ---------------------------------------------------------------------------
# 叶片形鳍
# ---------------------------------------------------------------------------
def _leaf_width(s: float) -> float:
    s = min(1.0, max(0.0, s))
    body = 0.62 + 0.38 * (math.sin(math.pi * s) ** 0.55)
    return body * (1.0 - s ** 2.15)


def _make_leaf(
    name: str,
    origin: Vec3,
    v_dir: Vec3,
    n_hint: Vec3,
    length: float,
    half_width: float,
    thickness: float,
    bend: float = 0.0,
    n_s: int = 10,
    n_t: int = 8,
    outline: bool = True,
) -> Mesh:
    """
    生成一片有厚度的小叶子。

    v_dir: 从鳍根指向叶尖的方向
    n_hint: 叶面法线的大致方向（会自动正交化）
    """
    v = v_norm(v_dir)
    n = v_norm(v_sub(n_hint, v_mul(v, v_dot(n_hint, v))))
    u = v_norm(v_cross(v, n))

    verts: List[Vec3] = []
    indices_top: List[List[int]] = []
    indices_bottom: List[List[int]] = []

    for i in range(n_s + 1):
        s = i / float(n_s)
        w = half_width * _leaf_width(s)
        center = v_add(
            origin,
            v_add(v_mul(v, length * s), v_mul(n, bend * math.sin(math.pi * s))),
        )
        top_row: List[int] = []
        bottom_row: List[int] = []
        for j in range(n_t + 1):
            t = -1.0 + 2.0 * j / float(n_t)
            edge = math.sqrt(max(0.0, 1.0 - t * t))
            thick = thickness * edge * (math.sin(math.pi * s) ** 0.42)
            base = v_add(center, v_mul(u, w * t))
            top_row.append(len(verts))
            verts.append(v_add(base, v_mul(n, thick)))
            bottom_row.append(len(verts))
            verts.append(v_add(base, v_mul(n, -thick)))
        indices_top.append(top_row)
        indices_bottom.append(bottom_row)

    faces: List[Tuple[int, int, int]] = []
    for i in range(n_s):
        for j in range(n_t):
            a = indices_top[i][j]
            b = indices_top[i][j + 1]
            c = indices_top[i + 1][j + 1]
            d = indices_top[i + 1][j]
            _quad_faces(faces, a, b, c, d)

            a = indices_bottom[i][j]
            b = indices_bottom[i][j + 1]
            c = indices_bottom[i + 1][j + 1]
            d = indices_bottom[i + 1][j]
            _quad_faces(faces, a, d, c, b)

    return Mesh(name, verts, [], faces, "blue", True, outline)


def _build_dorsal_fin() -> Mesh:
    q = DORSAL_OFFSET / BODY_LEN
    y = HEAD_Y + BODY_LEN * q
    origin = (0.0, y, body_top_z(q) - 0.035)
    return _make_leaf(
        "dorsal",
        origin,
        (0.0, 0.26, 0.966),
        (1.0, 0.0, 0.0),
        length=0.380,
        half_width=0.265,
        thickness=0.055,
        bend=0.012,
        outline=True,
    )


def _build_pectoral(side: int) -> Mesh:
    q = PECTORAL_OFFSET / BODY_LEN
    origin = (0.515 * side, HEAD_Y + BODY_LEN * q, -0.235)
    v_dir = (0.58 * side, 0.20, -0.79)
    n_hint = (0.46 * side, -0.84, 0.28)
    return _make_leaf(
        "pectoral_%d" % side,
        origin,
        v_dir,
        n_hint,
        length=0.505,
        half_width=0.228,
        thickness=0.038,
        bend=0.035 * side,
        outline=True,
    )


def _build_flukes() -> List[Mesh]:
    meshes = []
    origin = (0.0, TAIL_Y - 0.020, -0.010)
    for side, v_dir, label in (
        (1, (0.10, 0.62, 0.78), "fluke_up"),
        (-1, (0.10, 0.66, -0.74), "fluke_down"),
    ):
        meshes.append(
            _make_leaf(
                label,
                origin,
                v_dir,
                (1.0, 0.0, 0.0),
                length=0.480,
                half_width=0.205,
                thickness=0.043,
                bend=0.015 * side,
                outline=True,
            )
        )
    return meshes


# ---------------------------------------------------------------------------
# 场景
# ---------------------------------------------------------------------------
class WhaleModel:
    __slots__ = ("meshes",)

    def __init__(self) -> None:
        self.meshes: List[Mesh] = [
            _build_body(),
            _build_belly(),
            _build_eye_patch(1),
            _build_eye_patch(-1),
            _build_pupil(1),
            _build_pupil(-1),
            _build_muzzle_patch(),
            _build_mouth(),
            _build_snout(),
            _build_dorsal_fin(),
            _build_pectoral(1),
            _build_pectoral(-1),
        ]
        self.meshes.extend(_build_flukes())


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def _make_camera() -> Tuple[Vec3, Vec3, Vec3, Vec3]:
    eye = CAMERA_POS
    forward = v_norm(v_sub(CAMERA_TARGET, eye))
    right = v_norm(v_cross(forward, WORLD_UP))
    up = v_norm(v_cross(right, forward))
    return eye, forward, right, up


_CAM_EYE, _CAM_FWD, _CAM_RIGHT, _CAM_UP = _make_camera()
_LIGHT = v_norm(LIGHT_DIR)
_FILL = v_norm(FILL_DIR)


def _shade(
    material: str,
    normal: Vec3,
    two_sided: bool,
    to_camera: Vec3,
) -> Tuple[int, int, int]:
    if material == "cyan":
        return CYAN
    if material == "white":
        # 设定图里的肚皮和眼斑是纯白；平面白也能避免三角面接缝产生噪点
        return WHITE
    if material == "black":
        return BLACK

    n = normal
    if two_sided:
        if v_dot(n, to_camera) < 0.0:
            n = v_mul(n, -1.0)
    if material == "white":
        ambient, diffuse, max_tone = 0.935, 0.095, 1.0
    else:
        ambient, diffuse, max_tone = 0.705, 0.300, 1.055

    key = max(0.0, v_dot(n, _LIGHT))
    fill = max(0.0, v_dot(n, _FILL))
    front = max(0.0, v_dot(n, to_camera))

    tone = ambient + diffuse * key + 0.045 * fill + 0.035 * front
    if two_sided:
        # 薄鳍两面都要受光，避免翻过去突然变黑
        tone = max(tone, 0.79)
    tone = min(max_tone, max(0.62, tone))
    # 量化一点点，颜色缓存更有效，也让明暗过渡更像赛璐璐
    tone = round(tone * 40.0) / 40.0

    r = int(min(255.0, BLUE[0] * tone))
    g = int(min(255.0, BLUE[1] * tone))
    b = int(min(255.0, BLUE[2] * min(1.0, tone + 0.025)))
    return (r, g, b)


class _RenderCache:
    def __init__(self, capacity: int = 96) -> None:
        self.capacity = capacity
        self.data: "OrderedDict[Tuple[int, int, int, int], QImage]" = OrderedDict()

    def get(self, key: Tuple[int, int, int, int]) -> Optional[QImage]:
        img = self.data.get(key)
        if img is not None:
            self.data.move_to_end(key)
        return img

    def put(self, key: Tuple[int, int, int, int], image: QImage) -> None:
        self.data[key] = image
        self.data.move_to_end(key)
        while len(self.data) > self.capacity:
            self.data.popitem(last=False)


def _convex_hull(points: Sequence[Vec2]) -> List[Vec2]:
    """Andrew monotone chain，用来做外轮廓描边。"""
    if len(points) < 3:
        return list(points)
    pts = sorted(set((round(p[0], 2), round(p[1], 2)) for p in points))
    if len(pts) < 3:
        return list(pts)

    def cross(o: Vec2, a: Vec2, b: Vec2) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: List[Vec2] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0.0:
            lower.pop()
        lower.append(p)
    upper: List[Vec2] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0.0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


class WhaleRenderer:
    """把 WhaleModel 渲染到透明 QImage。"""

    _cache = _RenderCache(120)
    _color_cache: Dict[Tuple[int, int, int], QColor] = {}
    _pen_cache: Dict[Tuple[int, int, int], QPen] = {}

    def __init__(self, model: Optional[WhaleModel] = None) -> None:
        self.model = model or WhaleModel()

    # 供窗口调用：角度使用度数
    def render(
        self,
        size: int,
        yaw_deg: float,
        pitch_deg: float,
        zoom: float = 1.0,
        dpr: float = 1.0,
    ) -> QImage:
        yaw_key = int(round(yaw_deg * 4.0))
        pitch_key = int(round(pitch_deg * 4.0))
        zoom_key = int(round(zoom * 100.0))
        dpr_key = int(round(dpr * 100.0))
        key = (yaw_key, pitch_key, zoom_key, dpr_key)
        cached = self._cache.get(key)
        if cached is not None and cached.width() == int(size * dpr):
            return cached

        image = self._render_uncached(size, yaw_deg, pitch_deg, zoom, dpr)
        self._cache.put(key, image)
        return image

    def _render_uncached(
        self,
        size: int,
        yaw_deg: float,
        pitch_deg: float,
        zoom: float,
        dpr: float,
    ) -> QImage:
        px_size = max(2, int(round(size * dpr)))
        image = QImage(px_size, px_size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        image.setDevicePixelRatio(dpr)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.NoBrush)

        yaw = math.radians(yaw_deg)
        pitch = math.radians(pitch_deg)
        focal = size * 1.92 * zoom
        cx = size * 0.5
        cy = size * 0.485

        projected: Dict[str, List[Vec2]] = {}
        draw_tris: List[Tuple[float, QPolygonF, Tuple[int, int, int]]] = []

        front_dir = rot_x(rot_z((0.0, -1.0, 0.0), yaw), pitch)
        to_cam_dir = v_norm(v_sub(_CAM_EYE, (0.0, 0.0, 0.10)))
        face_visible = v_dot(front_dir, to_cam_dir) > 0.12

        for mesh in self.model.meshes:
            if mesh.front_only and not face_visible:
                continue
            verts_screen: List[Vec2] = []
            verts_depth: List[float] = []
            verts_world: List[Vec3] = []
            valid: List[bool] = []
            for p in mesh.verts:
                p = rot_x(rot_z(p, yaw), pitch)
                rel = v_sub(p, _CAM_EYE)
                depth = v_dot(rel, _CAM_FWD)
                if depth <= 0.12:
                    verts_screen.append((0.0, 0.0))
                    verts_depth.append(depth)
                    verts_world.append(p)
                    valid.append(False)
                    continue
                sx = cx + focal * v_dot(rel, _CAM_RIGHT) / depth
                sy = cy - focal * v_dot(rel, _CAM_UP) / depth
                verts_screen.append((sx, sy))
                verts_depth.append(depth)
                verts_world.append(p)
                valid.append(True)

            if mesh.outline:
                projected[mesh.name] = [p for p, ok in zip(verts_screen, valid) if ok]

            for i0, i1, i2 in mesh.faces:
                if not (valid[i0] and valid[i1] and valid[i2]):
                    continue
                p0, p1, p2 = verts_world[i0], verts_world[i1], verts_world[i2]
                centroid = v_mul(v_add(v_add(p0, p1), p2), 1.0 / 3.0)
                to_cam = v_sub(_CAM_EYE, centroid)
                if v_len(to_cam) < 1e-9:
                    continue

                if mesh.norms:
                    n = v_norm(
                        v_add(
                            v_add(mesh.norms[i0], mesh.norms[i1]),
                            mesh.norms[i2],
                        )
                    )
                    # 法线也跟着模型旋转
                    n = rot_x(rot_z(n, yaw), pitch)
                else:
                    n = v_norm(v_cross(v_sub(p1, p0), v_sub(p2, p0)))

                if not mesh.two_sided and v_dot(n, to_cam) <= 0.0:
                    continue
                color = _shade(mesh.material, n, mesh.two_sided, v_norm(to_cam))

                depth = (verts_depth[i0] + verts_depth[i1] + verts_depth[i2]) / 3.0
                if mesh.name == "belly":
                    # 贴花只比本体高几毫米，深度排序容易打架，给它一点“提前量”
                    depth -= 0.95
                elif mesh.name.startswith("eye_"):
                    depth -= 1.15
                elif mesh.name.startswith("pupil_"):
                    depth -= 1.24
                elif mesh.name == "muzzle":
                    depth -= 1.04
                elif mesh.name == "snout":
                    depth -= 1.31
                elif mesh.name == "mouth":
                    depth -= 1.35
                poly = QPolygonF(
                    [
                        QPointF(verts_screen[i0][0], verts_screen[i0][1]),
                        QPointF(verts_screen[i1][0], verts_screen[i1][1]),
                        QPointF(verts_screen[i2][0], verts_screen[i2][1]),
                    ]
                )
                draw_tris.append((depth, poly, color))

        # 先画青色外轮廓。用凸包扩大约 1 像素，再让本体覆盖中间。
        pen = QPen(_color(CYAN))
        pen.setWidthF(max(2.5, size * 0.0073))
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(_color(CYAN))
        for pts in projected.values():
            hull = _convex_hull(pts)
            if len(hull) >= 3:
                painter.drawPolygon(
                    QPolygonF([QPointF(x, y) for x, y in hull])
                )

        # 远到近
        draw_tris.sort(key=lambda item: item[0], reverse=True)
        for _depth, poly, color in draw_tris:
            painter.setPen(_pen(color))
            painter.setBrush(_color(color))
            painter.drawPolygon(poly)

        painter.end()
        return image


def _color(rgb: Tuple[int, int, int]) -> QColor:
    c = WhaleRenderer._color_cache.get(rgb)
    if c is None:
        c = QColor(rgb[0], rgb[1], rgb[2])
        WhaleRenderer._color_cache[rgb] = c
    return c


def _pen(rgb: Tuple[int, int, int]) -> QPen:
    p = WhaleRenderer._pen_cache.get(rgb)
    if p is None:
        color = _color(rgb)
        p = QPen(color)
        p.setWidthF(1.15)
        p.setJoinStyle(Qt.RoundJoin)
        WhaleRenderer._pen_cache[rgb] = p
    return p


def draw_shadow(painter: QPainter, size: int) -> None:
    """脚下一团很淡的接触阴影。"""
    painter.save()
    center = QPointF(size * 0.5, size * 0.815)
    radius = size * 0.185
    gradient = QRadialGradient(center, radius)
    gradient.setColorAt(0.0, QColor(32, 48, 105, 24))
    gradient.setColorAt(0.55, QColor(32, 48, 105, 8))
    gradient.setColorAt(1.0, QColor(32, 48, 105, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(gradient)
    painter.drawEllipse(center, radius, radius * 0.27)
    painter.restore()


# 单例渲染器，窗口和预览脚本共用
_default_renderer: Optional[WhaleRenderer] = None


def get_renderer() -> WhaleRenderer:
    global _default_renderer
    if _default_renderer is None:
        _default_renderer = WhaleRenderer()
    return _default_renderer
