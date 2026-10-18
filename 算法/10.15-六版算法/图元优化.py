"""可选的闭合轮廓分解与静态基础图元清理；不修改输入或写入资产。"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import math
from pathlib import Path


_spec = importlib.util.spec_from_file_location(
    'ui6_optimization_geometry', Path(__file__).with_name('几何工具.py'))
geo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(geo)


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _area(points):
    return math.fsum(a[0] * b[1] - a[1] * b[0]
                     for a, b in zip(points, points[1:] + points[:1])) / 2


def _inside(point, polygon):
    """严格内部的绕数判断；边界另行处理。坐标已归一化。"""
    winding = 0
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        turn = geo._orientation(a, b, point)
        if turn == 0 and geo._on_segment(a, b, point):
            return False
        if a[1] <= point[1] < b[1] and turn > 0:
            winding += 1
        elif b[1] <= point[1] < a[1] and turn < 0:
            winding -= 1
    return winding != 0


def _read_polygon(points):
    if isinstance(points, (str, bytes, bytearray)):
        raise TypeError('轮廓必须为单环点序列')
    raw = [geo._pair(p, '轮廓点') for p in points]
    if len(raw) > 1 and raw[0] == raw[-1]:
        raw.pop()
    if not 3 <= len(raw) <= 128:
        raise ValueError('轮廓需要3至128个点；孔洞须另行建模')
    if len(set(raw)) != len(raw):
        raise ValueError('轮廓含有重复点')
    start = min(range(len(raw)), key=lambda i: raw[i])
    raw = raw[start:] + raw[:start]
    pts, origin, scale = geo._normalise(raw)
    # 先拒绝相邻折返与非相邻边相交，不能通过删点掩盖非法轮廓。
    n = len(pts)
    for i in range(n):
        if geo._orientation(pts[i - 1], pts[i], pts[(i + 1) % n]) == 0:
            if not geo._same_direction(pts[i - 1], pts[i], pts[(i + 1) % n]):
                raise ValueError('轮廓含有折返或退化边')
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if geo._segments_intersect(pts[i], pts[(i + 1) % n],
                                       pts[j], pts[(j + 1) % n]):
                raise ValueError('轮廓自交或非相邻边接触')
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i in range(len(pts)):
            if geo._orientation(pts[i - 1], pts[i], pts[(i + 1) % len(pts)]) == 0:
                del pts[i]
                changed = True
                break
    area = _area(pts)
    if abs(area) <= geo._TURN_EPS:
        raise ValueError('轮廓退化或过于接近共线')
    if area < 0:
        pts.reverse()
    start = min(range(len(pts)), key=lambda i: pts[i])
    pts = pts[start:] + pts[:start]
    return pts, origin, scale


def _least_triangle_ops(a, b, c):
    base = geo._triangle_ops(a, b, c)
    if len(base) <= 3:
        return base
    # 局部坐标计算外心，避免大绝对坐标的平方抵消。
    bx, by = b[0] - a[0], b[1] - a[1]
    cx, cy = c[0] - a[0], c[1] - a[1]
    determinant = 2 * (bx * cy - by * cx)
    if abs(determinant) <= geo._TURN_EPS:
        return base
    bb, cc = bx * bx + by * by, cx * cx + cy * cy
    center = (a[0] + (bb * cy - cc * by) / determinant,
              a[1] + (bx * cc - cx * bb) / determinant)
    orientation = geo._orientation(a, b, c)
    edges = ((a, b), (b, c), (c, a))
    if any(geo._orientation(p, q, center) != orientation for p, q in edges):
        return base
    result = []
    for p, q in edges:
        mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
        dx, dy = center[0] - mx, center[1] - my
        result.append(((center[0] + mx) / 2, (center[1] + my) / 2,
                       math.hypot(q[0] - p[0], q[1] - p[1]), math.hypot(dx, dy),
                       math.degrees(math.atan2(dx, -dy))))
    if not math.isclose(sum(w * h / 2 for _, _, w, h, _ in result),
                        abs(_cross(a, b, c)) / 2, rel_tol=1e-9, abs_tol=1e-14):
        return base
    return result


def _restore(operations, origin, scale):
    result = []
    for x, y, w, h, angle in operations:
        row = (origin[0] + x * scale, origin[1] + y * scale,
               w * scale, h * scale, angle)
        if not all(math.isfinite(v) for v in row) or min(row[2:4]) <= 0:
            raise ValueError('分解结果超出有限数值范围')
        result.append(row)
    return result


def triangle_ops(a, b, c):
    """等腰/直角特例及锐角外心三片分解；其余回退六版四片分解。"""
    pts, origin, scale = _read_polygon([a, b, c])
    return _restore(_least_triangle_ops(*pts), origin, scale)


def contour_ops(points):
    """简单单环凹/凸多边形：在当前分片规则和输入顶点剖分中选最少图元。"""
    pts, origin, scale = _read_polygon(points)
    n = len(pts)
    valid = {}

    def diagonal(i, j):
        if j == i + 1 or (i == 0 and j == n - 1):
            return True
        if (i, j) in valid:
            return valid[i, j]
        a, b = pts[i], pts[j]
        ok = _inside(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), pts)
        for k, c in enumerate(pts):
            if k not in (i, j) and geo._orientation(a, b, c) == 0 and geo._on_segment(a, b, c):
                ok = False
            z = (k + 1) % n
            if k not in (i, j) and z not in (i, j):
                if geo._segments_intersect(a, b, c, pts[z]):
                    ok = False
        valid[i, j] = ok
        return ok

    costs = {(i, i + 1): 0 for i in range(n - 1)}
    choices = {}
    for span in range(2, n):
        for i in range(n - span):
            j = i + span
            if not diagonal(i, j):
                continue
            candidates = []
            for k in range(i + 1, j):
                if (i, k) not in costs or (k, j) not in costs:
                    continue
                if geo._orientation(pts[i], pts[k], pts[j]) <= 0:
                    continue
                center = tuple((pts[i][d] + pts[k][d] + pts[j][d]) / 3 for d in (0, 1))
                if not _inside(center, pts):
                    continue
                count = len(_least_triangle_ops(pts[i], pts[k], pts[j]))
                candidates.append((costs[i, k] + costs[k, j] + count, k))
            if candidates:
                costs[i, j], choices[i, j] = min(candidates)
    if (0, n - 1) not in choices:
        raise ValueError('轮廓无法稳定无交叉剖分')
    result = []

    def collect(i, j):
        if j - i < 2:
            return
        k = choices[i, j]
        # 仅重建获选三角，避免缓存O(n³)组最终不会使用的分片参数。
        result.extend(_least_triangle_ops(pts[i], pts[k], pts[j]))
        collect(i, k)
        collect(k, j)

    collect(0, n - 1)
    if not math.isclose(math.fsum(w * h / 2 for _, _, w, h, _ in result),
                        _area(pts), rel_tol=1e-9, abs_tol=1e-14):
        raise ValueError('轮廓分解面积未保持')
    return _restore(result, origin, scale)


def expand_ops(operations, factor=1.001):
    """以各片矩形中心等比例放大宽高；显式调用，不能替代透明或异色边界裁切。"""
    factor = geo._number(factor, '微重叠比例')
    if factor < 1:
        raise ValueError('微重叠比例不能小于1')
    result = []
    for row in operations:
        if len(row) != 5:
            raise ValueError('三角操作需要x、y、宽、高、旋转五项')
        x, y, w, h, angle = [geo._number(v, '三角参数') for v in row]
        if min(w, h) <= 0:
            raise ValueError('三角宽高必须为正')
        result.append((x, y, geo._positive(w * factor, '扩片宽'),
                       geo._positive(h * factor, '扩片高'), angle))
    return result


def cleanup_candidates(scene, *, render, margin=2, max_pixels=16_000_000):
    """实际GIA回读scene的清理建议。render须是同一基础几何渲染器，如core.render。

    只对当前画布/布局作4倍采样的保守候选判断，最终渲染不同则整批撤回建议。
    返回原始记录索引，不改变scene、配方或GIA；原生图/遮罩直接拒绝。
    """
    import cv2
    import numpy as np

    if not callable(render):
        raise TypeError('render必须是只读PNG渲染函数')
    for value, label, minimum in ((margin, 'margin', 1), (max_pixels, 'max_pixels', 1)):
        if type(value) is not int or value < minimum:
            raise ValueError(f'{label}必须是不小于{minimum}的整数')
    if scene.get('native_mask') or scene.get('ignored_mask'):
        raise ValueError('原生遮罩不能作为基础几何清理依据')
    if scene.get('missing_refs'):
        raise ValueError('存在悬空子引用，不能分析不完整场景')
    root = scene['root_transform']
    if len(root) != 13:
        raise ValueError('根变换必须为已回读的二维13项，不支持X/Y倾斜')
    for value in root:
        geo._number(value, '根变换')
    if root[10] == 0 or root[11] == 0:
        raise ValueError('根缩放不能为零')
    width, height = [geo._positive(v, '画布尺寸') for v in root[2:4]]
    width4, height4 = round(width * 4), round(height * 4)
    if min(width4, height4) < 1 or width4 * height4 > max_pixels:
        raise ValueError('采样画布为空或超出max_pixels限制')
    if margin > min(64, max(width4, height4)):
        raise ValueError('margin不能超过64或采样画布的最长边')
    rows = scene['records']
    for row in rows:
        if len(row) != 18 or row[0] not in (100001, 100002, 100003):
            raise ValueError('仅支持二维18项的矩形、椭圆和等腰三角形，不支持X/Y倾斜')
        if row[7:11] != [.5] * 4:
            raise ValueError('仅支持居中锚点的回读控件')
        for i in (1, 2, 3, 4, 5, 6, 11, 12, 13):
            geo._number(row[i], '回读几何')
        if min(row[3:5]) <= 0 or row[11] == 0 or row[12] == 0:
            raise ValueError('回读宽高必须为正，缩放不能为零')
        if any(isinstance(v, bool) or not isinstance(v, (int, np.integer)) or not 0 <= v <= 255
               for v in row[14:18]):
            raise ValueError('回读颜色必须是0至255整数RGBA')
        if max(abs(float(row[i])) for i in (1, 2, 3, 4)) * max(1, abs(row[11]), abs(row[12])) * 4 > 1e8:
            raise ValueError('回读图元超出安全采样坐标范围')

    def mask(row):
        asset, x, y, w, h, px, py = row[:7]
        sx, sy, angle = row[11:14]
        cx, cy = (x + width / 2) * 4, (height / 2 - y) * 4
        left, right = cx - px * w * 4 * sx, cx + (1 - px) * w * 4 * sx
        top, bottom = cy - (1 - py) * h * 4 * sy, cy + py * h * 4 * sy
        sine, cosine = math.sin(math.radians(angle)), math.cos(math.radians(angle))

        def rotate(p):
            dx, dy = p[0] - cx, p[1] - cy
            return (cx + dx * cosine + dy * sine, cy - dx * sine + dy * cosine)

        corners = [rotate(p) for p in [(left, top), (right, top), (right, bottom), (left, bottom)]]
        if any(not math.isfinite(v) or abs(v) > 2 ** 30 for p in corners for v in p):
            raise ValueError('变换后坐标超出安全采样范围')
        out = np.zeros((height4, width4), np.uint8)
        if asset == 100002:
            center = rotate(((left + right) / 2, (top + bottom) / 2))
            cv2.ellipse(out, tuple(round(v) for v in center),
                        (max(1, round(abs(w * 4 * sx) / 2)), max(1, round(abs(h * 4 * sy) / 2))),
                        -angle, 0, 360, 1, -1)
        else:
            points = ([(cx + (.5 - px) * w * 4 * sx, top), (left, bottom), (right, bottom)]
                      if asset == 100003 else [(left, top), (right, top), (right, bottom), (left, bottom)])
            points = np.round([rotate(p) for p in points])
            if not np.isfinite(points).all() or np.abs(points).max() > 2 ** 30:
                raise ValueError('变换后坐标超出安全采样范围')
            cv2.fillPoly(out, [points.astype(np.int32)], 1)
        bounded = all(margin + 1 <= p[0] <= width4 - margin - 2
                      and margin + 1 <= p[1] <= height4 - margin - 2 for p in corners)
        return out, bounded

    kernel = np.ones((margin * 2 + 1, margin * 2 + 1), np.uint8)
    covered = np.zeros((height4, width4), np.uint8)
    removed = {}
    for i in range(len(rows) - 1, -1, -1):
        row = rows[i]
        support, bounded = mask(row)
        if not support.any():
            continue
        guarded = cv2.dilate(support, kernel).astype(bool)
        safe = cv2.erode(covered, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)
        if bounded and np.all(safe[guarded]):
            removed[i] = 'fully_occluded'
        elif row[17] == 255:
            covered |= support
    # 前向保留同色底层，避免互相作为删除理由。
    solid = np.zeros((height4, width4), np.uint32)
    for i, row in enumerate(rows):
        if i in removed:
            continue
        support, bounded = mask(row)
        support = support.astype(bool)
        if not support.any() or row[17] == 0:
            continue
        packed = 1 + (int(row[14]) << 16) + (int(row[15]) << 8) + int(row[16])
        guarded = cv2.dilate(support.astype(np.uint8), kernel).astype(bool)
        if bounded and row[17] == 255 and np.all(solid[guarded] == packed):
            removed[i] = 'same_opaque_color'
        else:
            solid[support] = packed if row[17] == 255 else 0
    if rows and len(removed) == len(rows):
        removed.pop(0)  # 保留有效组的至少一个控件。
    keep = [i for i in range(len(rows)) if i not in removed]

    def pixels(source):
        png = render(copy.deepcopy(source))
        decoded = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
        if decoded is None:
            raise ValueError('渲染函数没有返回有效PNG')
        return decoded

    before = pixels(scene)
    after_scene = copy.deepcopy(scene)
    after_scene['records'] = [after_scene['records'][i] for i in keep]
    after = pixels(after_scene)
    equal = before.shape == after.shape and before.dtype == after.dtype and np.array_equal(before, after)
    proposed = [{'index': i, 'reason': removed[i]} for i in sorted(removed)]
    return {'keep_indices': keep if equal else list(range(len(rows))),
            'candidates': proposed if equal else [],
            'rejected_candidates': [] if equal else proposed,
            'pixel_equal': equal, 'sampling_zoom': 4, 'margin': margin,
            'before_pixels_sha256': hashlib.sha256(before.tobytes()).hexdigest(),
            'after_pixels_sha256': hashlib.sha256(after.tobytes()).hexdigest(),
            'boundary': '仅当前基础几何本地布局；应用配方后须重建GIA并复核四平台和预览，变化后重新分析。'}
