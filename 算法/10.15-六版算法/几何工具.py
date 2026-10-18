"""UI 六版算法的独立二维几何工具，不依赖任何旧版模块。"""

import math
import numbers
import sys


_EPS = sys.float_info.epsilon
_TURN_EPS = 64 * _EPS


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise TypeError(f"{label}必须是有限实数")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是有限实数") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label}必须是有限实数")
    return result


def _positive(value, label):
    value = _number(value, label)
    if value <= 0:
        raise ValueError(f"{label}必须大于0")
    return value


def _nonnegative(value, label):
    value = _number(value, label)
    if value < 0:
        raise ValueError(f"{label}不能小于0")
    return value


def _text(value, label):
    if not isinstance(value, str) or not value:
        raise TypeError(f"{label}必须是非空字符串")
    return value


def _pair(value, label):
    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{label}必须包含两个有限实数")
    try:
        pair = tuple(value)
    except TypeError as exc:
        raise TypeError(f"{label}必须包含两个有限实数") from exc
    if len(pair) != 2:
        raise ValueError(f"{label}必须恰好包含两个数")
    return (_number(pair[0], f"{label}[0]"),
            _number(pair[1], f"{label}[1]"))


def _rgba(color, alpha):
    if isinstance(alpha, bool) or not isinstance(alpha, numbers.Integral):
        raise TypeError("alpha必须是0到255的整数")
    alpha = int(alpha)
    if not 0 <= alpha <= 255:
        raise ValueError("alpha必须是0到255的整数")
    if isinstance(color, str):
        value = color[1:] if color.startswith("#") else color
        if len(value) != 6 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("颜色字符串必须是RRGGBB或#RRGGBB")
        try:
            rgb = [int(value[i:i + 2], 16) for i in (0, 2, 4)]
        except ValueError as exc:
            raise ValueError("颜色字符串必须是RRGGBB或#RRGGBB") from exc
    else:
        if isinstance(color, (str, bytes, bytearray)):
            raise TypeError("颜色必须是RGB十六进制字符串或三个整数通道")
        try:
            channels = tuple(color)
        except TypeError as exc:
            raise TypeError("颜色必须是RGB十六进制字符串或三个整数通道") from exc
        if len(channels) != 3:
            raise ValueError("RGB颜色必须恰好包含三个通道")
        rgb = []
        for index, channel in enumerate(channels):
            if isinstance(channel, bool) or not isinstance(channel, numbers.Integral):
                raise TypeError(f"颜色通道{index}必须是0到255的整数")
            channel = int(channel)
            if not 0 <= channel <= 255:
                raise ValueError(f"颜色通道{index}必须是0到255的整数")
            rgb.append(channel)
    return rgb + [alpha]


def _finite_result(value, label):
    if not math.isfinite(value):
        raise ValueError(f"{label}超出有限数值范围")
    return value


def _midpoint(a, b):
    return (_finite_result(a[0] / 2 + b[0] / 2, "中点x"),
            _finite_result(a[1] / 2 + b[1] / 2, "中点y"))


def _distance(a, b):
    dx = _finite_result(b[0] - a[0], "距离x")
    dy = _finite_result(b[1] - a[1], "距离y")
    return _finite_result(math.hypot(dx, dy), "距离")


def _cross(a, b, c):
    """缩放后的有向叉积，避免大坐标乘法溢出。"""
    ux, uy = b[0] - a[0], b[1] - a[1]
    vx, vy = c[0] - a[0], c[1] - a[1]
    for value in (ux, uy, vx, vy):
        if not math.isfinite(value):
            raise ValueError("多边形坐标跨度超出有限数值范围")
    scale = max(abs(ux), abs(uy), abs(vx), abs(vy))
    if scale == 0:
        return 0.0
    return (ux / scale) * (vy / scale) - (uy / scale) * (vx / scale)


def _orientation(a, b, c):
    value = _cross(a, b, c)
    if abs(value) <= _TURN_EPS:
        return 0
    return 1 if value > 0 else -1


def _same_direction(a, b, c):
    """判断a-b-c是否沿同一直线前进，而不是折返重叠。"""
    ux, uy = b[0] - a[0], b[1] - a[1]
    vx, vy = c[0] - b[0], c[1] - b[1]
    scale = max(abs(ux), abs(uy), abs(vx), abs(vy))
    if scale == 0:
        return False
    dot = (ux / scale) * (vx / scale) + (uy / scale) * (vy / scale)
    return dot > 0


def _on_segment(a, b, p):
    tolerance = 8 * _TURN_EPS
    return (min(a[0], b[0]) - tolerance <= p[0] <= max(a[0], b[0]) + tolerance
            and min(a[1], b[1]) - tolerance <= p[1] <= max(a[1], b[1]) + tolerance)


def _segments_intersect(a, b, c, d):
    o1, o2 = _orientation(a, b, c), _orientation(a, b, d)
    o3, o4 = _orientation(c, d, a), _orientation(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    return ((o1 == 0 and _on_segment(a, b, c))
            or (o2 == 0 and _on_segment(a, b, d))
            or (o3 == 0 and _on_segment(c, d, a))
            or (o4 == 0 and _on_segment(c, d, b)))


def _normalise(points):
    origin = points[0]
    offsets = []
    for point in points:
        dx = _finite_result(point[0] - origin[0], "多边形x跨度")
        dy = _finite_result(point[1] - origin[1], "多边形y跨度")
        offsets.append((dx, dy))
    scale = max(max(abs(x), abs(y)) for x, y in offsets)
    if scale == 0:
        raise ValueError("多边形退化")
    return [(x / scale, y / scale) for x, y in offsets], origin, scale


def _read_convex_polygon(points, label="多边形"):
    if isinstance(points, (str, bytes, bytearray)):
        raise TypeError(f"{label}必须是点序列")
    try:
        raw_points = list(points)
    except TypeError as exc:
        raise TypeError(f"{label}必须是点序列") from exc
    if len(raw_points) < 3:
        raise ValueError(f"{label}至少需要三个点")
    result = [_pair(point, f"{label}点{i + 1}") for i, point in enumerate(raw_points)]
    if len(set(result)) != len(result):
        raise ValueError(f"{label}含有重复点")

    # 共线且同向的中间点不改变轮廓；折返边会造成重叠，直接拒绝。
    changed = True
    while changed:
        changed = False
        if len(result) <= 3:
            break
        for i in range(len(result)):
            previous = result[i - 1]
            current = result[i]
            following = result[(i + 1) % len(result)]
            if _orientation(previous, current, following) == 0:
                if not _same_direction(previous, current, following):
                    raise ValueError(f"{label}含有折返或退化边")
                del result[i]
                changed = True
                break
    if len(result) < 3:
        raise ValueError(f"{label}退化")

    normalized, _, _ = _normalise(result)
    size = len(normalized)
    for i in range(size):
        a, b = normalized[i], normalized[(i + 1) % size]
        for j in range(i + 1, size):
            if j == i or j == (i + 1) % size or i == (j + 1) % size:
                continue
            c, d = normalized[j], normalized[(j + 1) % size]
            if _segments_intersect(a, b, c, d):
                raise ValueError(f"{label}自交或自触")

    turns = [_orientation(result[i - 1], result[i], result[(i + 1) % size])
             for i in range(size)]
    if 0 in turns or any(turn != turns[0] for turn in turns):
        raise ValueError(f"{label}必须是非退化凸多边形")

    # 以首点为原点扇形求面积，凸轮廓的各项同号，不发生大数相消。
    area_terms = []
    for i in range(1, size - 1):
        area_terms.append(normalized[i][0] * normalized[i + 1][1]
                          - normalized[i][1] * normalized[i + 1][0])
    if not area_terms or math.fsum(area_terms) == 0:
        raise ValueError(f"{label}退化")
    return result


def _triangle_ops(a, b, c):
    if _orientation(a, b, c) == 0:
        raise ValueError("多边形剖分产生退化三角形")

    def dot_is_zero(ax, ay, bx, by):
        scale_a = max(abs(ax), abs(ay))
        scale_b = max(abs(bx), abs(by))
        if scale_a == 0 or scale_b == 0:
            return False
        nax, nay = ax / scale_a, ay / scale_a
        nbx, nby = bx / scale_b, by / scale_b
        dot = nax * nbx + nay * nby
        size = math.hypot(nax, nay) * math.hypot(nbx, nby)
        return abs(dot) <= 128 * _EPS * size

    def emit(isosceles_apex, p, q):
        midpoint = _midpoint(p, q)
        bx = _finite_result(q[0] - p[0], "等腰底边x")
        by = _finite_result(q[1] - p[1], "等腰底边y")
        width = _finite_result(math.hypot(bx, by), "等腰底边长度")
        if width <= 0:
            raise ValueError("多边形剖分产生退化等腰底边")
        ax = _finite_result(isosceles_apex[0] - midpoint[0], "等腰高x")
        ay = _finite_result(isosceles_apex[1] - midpoint[1], "等腰高y")
        ux, uy = bx / width, by / width
        signed_height = _finite_result(math.fsum((ux * ay, -uy * ax)), "等腰高")
        height = abs(signed_height)
        if height <= 0:
            raise ValueError("多边形剖分产生退化等腰三角形")
        sign = 1 if signed_height > 0 else -1
        normal = (-uy * sign, ux * sign)
        center = (_finite_result(midpoint[0] + normal[0] * height / 2, "三角中心x"),
                  _finite_result(midpoint[1] + normal[1] * height / 2, "三角中心y"))
        angle = math.degrees(math.atan2(normal[0], -normal[1]))
        return (center[0], center[1], width, height,
                _finite_result(angle, "三角旋转角"))

    # 先保留旧二版的低成本特例：单个等腰三角形，或直角三角形拆成两个。
    for apex, p, q in ((a, b, c), (b, a, c), (c, a, b)):
        midpoint = _midpoint(p, q)
        base_x, base_y = q[0] - p[0], q[1] - p[1]
        altitude_x = apex[0] - midpoint[0]
        altitude_y = apex[1] - midpoint[1]
        if dot_is_zero(base_x, base_y, altitude_x, altitude_y):
            return [emit(apex, p, q)]

    for right, p, q in ((a, b, c), (b, a, c), (c, a, b)):
        first_x = _finite_result(p[0] - right[0], "直角边x")
        first_y = _finite_result(p[1] - right[1], "直角边y")
        second_x = _finite_result(q[0] - right[0], "直角边x")
        second_y = _finite_result(q[1] - right[1], "直角边y")
        if dot_is_zero(first_x, first_y, second_x, second_y):
            hypotenuse_midpoint = _midpoint(p, q)
            return [emit(hypotenuse_midpoint, right, p),
                    emit(hypotenuse_midpoint, right, q)]

    sides = [( _distance(b, c), a, b, c),
             ( _distance(a, c), b, a, c),
             ( _distance(a, b), c, a, b)]
    _, apex, base_a, base_b = max(sides, key=lambda item: item[0])
    dx = _finite_result(base_b[0] - base_a[0], "底边x")
    dy = _finite_result(base_b[1] - base_a[1], "底边y")
    length = _finite_result(math.hypot(dx, dy), "底边长度")
    if length <= 0:
        raise ValueError("多边形剖分产生退化底边")
    ux, uy = dx / length, dy / length
    rx = _finite_result(apex[0] - base_a[0], "投影x")
    ry = _finite_result(apex[1] - base_a[1], "投影y")
    projection = math.fsum((rx * ux, ry * uy))
    projection = _finite_result(projection, "投影距离")
    ratio = projection / length
    tolerance = 128 * _EPS
    if ratio < -tolerance or ratio > 1 + tolerance:
        raise ValueError("最长边投影越界，无法作无损等腰三角分解")
    ratio = min(1.0, max(0.0, ratio))
    foot = (_finite_result(base_a[0] + ratio * dx, "垂足x"),
            _finite_result(base_a[1] + ratio * dy, "垂足y"))

    operations = []
    for end in (base_a, base_b):
        hypotenuse_midpoint = _midpoint(apex, end)
        operations.append(emit(hypotenuse_midpoint, apex, foot))
        operations.append(emit(hypotenuse_midpoint, foot, end))
    return operations


def _minimum_triangulation_ops(points):
    """用区间DP选择总等腰图元数最少的凸多边形剖分。"""
    size = len(points)
    costs, choices, triangle_cache = {}, {}, {}
    for index in range(size - 1):
        costs[index, index + 1] = 0

    def triangle_ops(left, middle, right):
        key = (left, middle, right)
        if key not in triangle_cache:
            triangle_cache[key] = _triangle_ops(points[left], points[middle],
                                                points[right])
        return triangle_cache[key]

    for span in range(2, size):
        for left in range(size - span):
            right = left + span
            candidates = []
            for middle in range(left + 1, right):
                triangle = triangle_ops(left, middle, right)
                total = (costs[left, middle] + costs[middle, right]
                         + len(triangle))
                candidates.append((total, middle))
            costs[left, right], choices[left, right] = min(candidates)

    result = []

    def collect(left, right):
        if right - left < 2:
            return
        middle = choices[left, right]
        result.extend(triangle_ops(left, middle, right))
        collect(left, middle)
        collect(middle, right)

    collect(0, size - 1)
    return result


class Drawing:
    """收集带稳定局部ID的绘图图元。"""

    def __init__(self, name):
        self.name = _text(name, "name")
        self.elements = []
        self._counter = 0

    def _append(self, part, role, shape, x, y, width, height, rotation, rgba):
        self._counter += 1
        index = self._counter
        element = {
            "id": f"{self.name}:{index:04d}",
            "name": f"{self.name}_{index:02d}_{part}_{role}",
            "part": part,
            "role": role,
            "shape": shape,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "rotation": rotation,
            "color": list(rgba),
            "pivot": [0.5, 0.5],
            "scale": [1, 1],
        }
        self.elements.append(element)
        return element

    def add(self, part, role, shape, x, y, width, height, color,
            rotation=0, alpha=255):
        part, role, shape = (_text(part, "part"), _text(role, "role"),
                             _text(shape, "shape"))
        x, y = _number(x, "x"), _number(y, "y")
        width, height = _positive(width, "width"), _positive(height, "height")
        rotation = _number(rotation, "rotation")
        rgba = _rgba(color, alpha)
        return self._append(part, role, shape, x, y, width, height, rotation, rgba)

    def capsule(self, part, role, x, y, width, height, color, rotation=0,
                alpha=255):
        part, role = _text(part, "part"), _text(role, "role")
        x, y = _number(x, "x"), _number(y, "y")
        width, height = _positive(width, "width"), _positive(height, "height")
        rotation = _number(rotation, "rotation")
        rgba = _rgba(color, alpha)
        if height < width:
            raise ValueError("竖向capsule要求height不小于width")
        operations = []
        if height > width:
            operations.append((role + "中段", "rect", x, y, width, height - width))
        if height == width:
            operations.append((role + "圆端", "ellipse", x, y, width, width))
        else:
            angle = math.radians(rotation)
            sine, cosine = math.sin(angle), math.cos(angle)
            distance = (height - width) / 2
            for label, sign in (("上端", -1), ("下端", 1)):
                cx = _finite_result(x - sign * distance * sine, "capsule端点x")
                cy = _finite_result(y + sign * distance * cosine, "capsule端点y")
                operations.append((role + label, "ellipse", cx, cy, width, width))
        result = []
        for item_role, shape, cx, cy, w, h in operations:
            result.append(self._append(part, item_role, shape, cx, cy, w, h,
                                       rotation, rgba))
        return result

    def rounded_box(self, part, role, x, y, width, height, radius, color,
                    rotation=0, alpha=255):
        part, role = _text(part, "part"), _text(role, "role")
        x, y = _number(x, "x"), _number(y, "y")
        width, height = _positive(width, "width"), _positive(height, "height")
        radius = _nonnegative(radius, "radius")
        rotation = _number(rotation, "rotation")
        rgba = _rgba(color, alpha)
        if radius > min(width, height) / 2:
            raise ValueError("radius不能超过短边的一半")
        if radius == 0:
            return [self._append(part, role, "rect", x, y, width, height,
                                 rotation, rgba)]

        operations = []
        horizontal_height = height - 2 * radius
        vertical_width = width - 2 * radius
        if horizontal_height > 0:
            operations.append((role + "横条", "rect", 0.0, 0.0,
                               width, horizontal_height))
        if vertical_width > 0:
            operations.append((role + "纵条", "rect", 0.0, 0.0,
                               vertical_width, height))

        x_offset, y_offset = width / 2 - radius, height / 2 - radius
        corners = (("左上圆角", -x_offset, -y_offset),
                   ("右上圆角", x_offset, -y_offset),
                   ("左下圆角", -x_offset, y_offset),
                   ("右下圆角", x_offset, y_offset))
        seen = set()
        diameter = 2 * radius
        for label, dx, dy in corners:
            if (dx, dy) in seen:
                continue
            seen.add((dx, dy))
            operations.append((role + label, "ellipse", dx, dy,
                               diameter, diameter))

        angle = math.radians(rotation)
        sine, cosine = math.sin(angle), math.cos(angle)
        result = []
        for item_role, shape, dx, dy, w, h in operations:
            cx = _finite_result(x + dx * cosine - dy * sine, "圆角框图元x")
            cy = _finite_result(y + dx * sine + dy * cosine, "圆角框图元y")
            result.append(self._append(part, item_role, shape, cx, cy, w, h,
                                       rotation, rgba))
        return result

    def polygon(self, part, role, points, color, alpha=255):
        part, role = _text(part, "part"), _text(role, "role")
        rgba = _rgba(color, alpha)
        points = _read_convex_polygon(points)
        operations = _minimum_triangulation_ops(points)
        result = []
        for index, (x, y, width, height, rotation) in enumerate(operations, 1):
            result.append(self._append(part, f"{role}三角{index:02d}", "triangle",
                                       x, y, width, height, rotation, rgba))
        return result


def _rotation_radians(value):
    return math.radians(_number(value, "rotation"))


def element_boundary(element):
    """返回元素真实形状的旋转后边界；椭圆按四版采样360点。"""
    if not hasattr(element, "get"):
        raise TypeError("element必须是映射对象")
    x, y = _number(element.get("x"), "element.x"), _number(element.get("y"), "element.y")
    width, height = _positive(element.get("width"), "element.width"), \
                    _positive(element.get("height"), "element.height")
    scale = _pair(element.get("scale", (1, 1)), "element.scale")
    pivot = _pair(element.get("pivot", (0.5, 0.5)), "element.pivot")
    if scale[0] <= 0 or scale[1] <= 0:
        raise ValueError("element.scale必须为正数")
    scaled_width = _positive(width * scale[0], "缩放后宽度")
    scaled_height = _positive(height * scale[1], "缩放后高度")
    rotation = _rotation_radians(element.get("rotation", 0))
    shape = element.get("shape", "rect")
    if not isinstance(shape, str):
        raise TypeError("element.shape必须是字符串")

    left = -pivot[0] * scaled_width
    top = -(1 - pivot[1]) * scaled_height
    if shape == "ellipse":
        local = [(left + scaled_width / 2 + scaled_width / 2 * math.cos(i * math.pi / 180),
                  top + scaled_height / 2 + scaled_height / 2 * math.sin(i * math.pi / 180))
                 for i in range(360)]
    elif shape == "triangle":
        local = [(left + scaled_width / 2, top),
                 (left, top + scaled_height),
                 (left + scaled_width, top + scaled_height)]
    else:
        local = [(left, top), (left + scaled_width, top),
                 (left + scaled_width, top + scaled_height),
                 (left, top + scaled_height)]
    cosine, sine = math.cos(rotation), math.sin(rotation)
    boundary = []
    for local_x, local_y in local:
        px = _finite_result(x + local_x * cosine - local_y * sine, "边界x")
        py = _finite_result(y + local_x * sine + local_y * cosine, "边界y")
        boundary.append((px, py))
    return boundary


def clip_convex(subject, boundary):
    """Sutherland-Hodgman裁切；主体和裁切边界均须为凸多边形。"""
    if isinstance(subject, (str, bytes, bytearray)):
        raise TypeError("subject必须是点序列")
    try:
        subject_points = list(subject)
    except TypeError as exc:
        raise TypeError("subject必须是点序列") from exc
    if not subject_points:
        return []
    subject_points = _read_convex_polygon(subject_points, "subject")
    boundary_points = _read_convex_polygon(boundary, "boundary")

    all_points = subject_points + boundary_points
    normalized, origin, scale = _normalise(all_points)
    subject_local = normalized[:len(subject_points)]
    boundary_local = normalized[len(subject_points):]
    boundary_area = math.fsum(
        boundary_local[i][0] * boundary_local[(i + 1) % len(boundary_local)][1]
        - boundary_local[i][1] * boundary_local[(i + 1) % len(boundary_local)][0]
        for i in range(len(boundary_local)))
    orientation = 1 if boundary_area > 0 else -1

    result = subject_local
    for i, a in enumerate(boundary_local):
        b = boundary_local[(i + 1) % len(boundary_local)]
        source, result = result, []
        if not source:
            break

        def signed_distance(point):
            return orientation * ((b[0] - a[0]) * (point[1] - a[1])
                                  - (b[1] - a[1]) * (point[0] - a[0]))

        previous = source[-1]
        previous_distance = signed_distance(previous)
        for current in source:
            current_distance = signed_distance(current)
            previous_inside = previous_distance >= 0
            current_inside = current_distance >= 0
            if previous_inside != current_inside:
                denominator = previous_distance - current_distance
                if denominator == 0:
                    raise ValueError("裁切交点数值退化")
                t = previous_distance / denominator
                point = (previous[0] + t * (current[0] - previous[0]),
                         previous[1] + t * (current[1] - previous[1]))
                result.append(point)
            if current_inside:
                result.append(current)
            previous, previous_distance = current, current_distance

        cleaned = []
        for point in result:
            if not cleaned or math.hypot(point[0] - cleaned[-1][0],
                                         point[1] - cleaned[-1][1]) > 32 * _EPS:
                cleaned.append(point)
        if len(cleaned) > 1 and math.hypot(cleaned[0][0] - cleaned[-1][0],
                                           cleaned[0][1] - cleaned[-1][1]) <= 32 * _EPS:
            cleaned.pop()
        result = cleaned

    if len(result) < 3:
        return []
    points = [(_finite_result(origin[0] + point[0] * scale, "裁切结果x"),
               _finite_result(origin[1] + point[1] * scale, "裁切结果y"))
              for point in result]
    try:
        return _read_convex_polygon(points, "裁切结果")
    except ValueError:
        # 相切或浮点舍入造成的零面积结果没有可绘制的多边形。
        return []


def rounding_patch(origin, u, v, radius):
    """生成电话扣角使用的三块等腰三角形。

    只支持两方向的较小夹角满足 2*atan(1/2) < theta < pi；
    即约 53.1301° 到 180°（不含端点）。反角、平行方向及范围外角度拒绝。
    """
    origin = _pair(origin, "origin")
    u, v = _pair(u, "u"), _pair(v, "v")
    radius = _positive(radius, "radius")
    u_length, v_length = math.hypot(*u), math.hypot(*v)
    if not math.isfinite(u_length) or not math.isfinite(v_length):
        raise ValueError("方向向量超出有限数值范围")
    if u_length == 0 or v_length == 0:
        raise ValueError("方向向量不能为零")
    u = (u[0] / u_length, u[1] / u_length)
    v = (v[0] / v_length, v[1] / v_length)
    dot = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))
    cross = u[0] * v[1] - u[1] * v[0]
    theta = math.atan2(abs(cross), dot)
    minimum = 2 * math.atan(0.5)
    if not minimum < theta < math.pi:
        raise ValueError("扣角仅支持夹角大于约53.1301°且小于180°")

    tangent = math.tan(theta / 2)
    distance = _finite_result(radius / tangent, "扣角切点距离")
    half_distance = distance / 2
    ratio = half_distance / radius
    if not 0 < ratio < 1:
        raise ValueError("扣角在当前角度和半径下退化")
    root = math.sqrt(max(0.0, 1 - ratio * ratio))
    height = _finite_result(half_distance * ratio / (1 + root), "扣角弓高")
    if height <= 0:
        raise ValueError("扣角在当前数值精度下退化")

    bisector_raw = (u[0] + v[0], u[1] + v[1])
    bisector_length = math.hypot(*bisector_raw)
    if bisector_length == 0 or not math.isfinite(bisector_length):
        raise ValueError("扣角平分方向退化")
    bisector = (bisector_raw[0] / bisector_length,
                bisector_raw[1] / bisector_length)
    sign = 1 if cross > 0 else -1
    normal = (-u[1] * sign, u[0] * sign)
    q_local = (half_distance * u[0] + height * normal[0],
               half_distance * u[1] + height * normal[1])
    projection = math.fsum((q_local[0] * bisector[0],
                            q_local[1] * bisector[1]))
    s_local = (2 * projection * bisector[0] - q_local[0],
               2 * projection * bisector[1] - q_local[1])

    def translate(point):
        return (_finite_result(origin[0] + point[0], "扣角点x"),
                _finite_result(origin[1] + point[1], "扣角点y"))

    p = translate((distance * u[0], distance * u[1]))
    q = translate(q_local)
    s = translate(s_local)
    t = translate((distance * v[0], distance * v[1]))
    triangles = [(q, origin, p), (origin, q, s), (s, origin, t)]
    for triangle in triangles:
        if _orientation(*triangle) == 0:
            raise ValueError("扣角三角形退化")
    return triangles


def inside_rounded_rect(x, y, cx, cy, width, height, radius):
    """解析判断点是否位于中心为(cx,cy)的轴对齐圆角矩形内。"""
    x, y = _number(x, "x"), _number(y, "y")
    cx, cy = _number(cx, "cx"), _number(cy, "cy")
    width, height = _positive(width, "width"), _positive(height, "height")
    radius = _nonnegative(radius, "radius")
    if radius > min(width, height) / 2:
        raise ValueError("radius不能超过短边的一半")
    dx = max(abs(x - cx) - (width / 2 - radius), 0.0)
    dy = max(abs(y - cy) - (height / 2 - radius), 0.0)
    return math.hypot(dx, dy) <= radius
