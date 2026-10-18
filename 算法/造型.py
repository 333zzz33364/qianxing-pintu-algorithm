"""UI 图元参数化造型库（六版算法的上层封装）。

把此前每次手写坐标的常见部件收敛成参数化函数：花瓣环、暗边亮面、花心、抖动颗粒。
只做几何增减，不涉及身份、平台、编译；产物仍是 几何工具.Drawing 的 elements，
可直接交给 生成图元.build。

用法（相对 算法/10.15-六版算法/几何工具.py）：

    from 造型 import 花瓣环, 立体花瓣环, 花心, 颗粒
    d = geometry.Drawing('示例.1')
    花瓣环(d, '花瓣', 20, 中心=(256, 256), 半径=158, 宽=76, 高=190,
           颜色='#FFD522', 交替色='#FFC60C')
    花心(d, 中心=(256, 256), 直径=186, 外圈='#6E3616', 底面='#974E22')
    颗粒(d, '花心颗粒', 中心=(256, 256), 半径=80, 间距=23, 直径=19, 颜色='#5E2F12', 种子=1)

约定：
  花瓣的 width 是横向宽、height 是径向长；rotation 取该瓣的方位角，
  与既有交付（手机与雏菊.1、太阳花.1）保持一致，便于配方互相参考。
"""

import math
import random

_HALF = 0.5


def _方位(中心, 半径, 角度):
    rad = math.radians(角度)
    return (中心[0] + 半径 * math.sin(rad), 中心[1] - 半径 * math.cos(rad))


def 花瓣环(d, part, count, *, 中心, 半径, 宽, 高, 颜色,
           交替色=None, 起始角=0.0, 收窄=None):
    """均匀环形排布的单层花瓣。

    收窄=(每片递减量, 最小宽) 可做尖端渐窄效果；缺省不递减。
    返回该部件产生的图元列表。
    """
    if count < 3:
        raise ValueError('花瓣数至少 3')
    made = []
    for i in range(count):
        angle = 起始角 + i * 360.0 / count
        w = 宽
        if 收窄:
            step, floor = 收窄
            w = max(floor, 宽 - step * (i % 2))
        x, y = _方位(中心, 半径, angle)
        color = 颜色 if (交替色 is None or i % 2 == 0) else 交替色
        made.append(d.add(part, '第%02d瓣' % (i + 1), 'ellipse', x, y, w, 高,
                          color, angle))
    return made


def 立体花瓣环(d, part, count, *, 中心, 半径, 宽, 高, 暗边色, 亮面色,
               亮面半径差=12, 亮面宽比=0.65, 亮面高比=0.76, 起始角=0.0):
    """两图元近似的立体花瓣：底面暗边 + 外移亮面（亮面偏向外端，模拟尖端受光）。

    亮面半径差为正表示亮面中心比暗边中心更靠外，暗边因此只在瓣根一侧较厚。
    """
    made = []
    for i in range(count):
        angle = 起始角 + i * 360.0 / count
        x, y = _方位(中心, 半径, angle)
        inner = _方位(中心, 半径 + 亮面半径差, angle)
        made.append(d.add(part, '第%02d瓣暗边' % (i + 1), 'ellipse', x, y,
                          宽, 高, 暗边色, angle))
        made.append(d.add(part, '第%02d瓣亮面' % (i + 1), 'ellipse',
                          inner[0], inner[1], 宽 * 亮面宽比, 高 * 亮面高比,
                          亮面色, angle))
    return made


def 花心(d, part, *, 中心, 直径, 外圈, 底面, 逐层=12):
    """同心花心：外圈略小于花瓣内端、底面再小一圈。返回 (外圈, 底面) 两个图元。"""
    return (d.add(part, '花心外圈', 'ellipse', 中心[0], 中心[1], 直径, 直径, 外圈),
            d.add(part, '花心底面', 'ellipse', 中心[0], 中心[1],
                  直径 - 逐层 * 2, 直径 - 逐层 * 2, 底面))


def 颗粒(d, part, *, 中心, 半径, 间距, 直径, 颜色, 种子=0,
         抖动=0.34, 直径浮动=(0.84, 1.08)):
    """抖动三角点阵铺满圆形花心。

    比同心圆环更接近密集颗粒的观感；位置与直径都用固定种子抖动，
    同一种子必然得到同一结果，可安全写进配方。
    """
    rng = random.Random(种子)
    points = []
    rows = int(半径 // (间距 * 0.866)) + 1
    for row in range(-rows, rows + 1):
        base_y = row * 间距 * 0.866
        offset = 间距 * _HALF if row % 2 else 0.0
        cols = int(半径 // 间距) + 1
        for col in range(-cols, cols + 1):
            x = col * 间距 + offset + rng.uniform(-抖动, 抖动) * 间距
            y = base_y + rng.uniform(-抖动, 抖动) * 间距
            dist = math.hypot(x, y)
            if dist <= 半径:
                points.append((dist, x, y, 直径 * rng.uniform(*直径浮动)))
    points.sort()
    made = []
    for i, (_dist, x, y, diameter) in enumerate(points, 1):
        made.append(d.add(part, '%s%02d' % (part, i), 'ellipse',
                          中心[0] + x, 中心[1] + y, diameter, diameter, 颜色))
    return made


def 预算(elements, limit):
    """返回 (图元数, 是否超预算, 各部件占用)。用于生成前确认预算。"""
    parts = {}
    for e in elements:
        parts[e.get('part', '?')] = parts.get(e.get('part', '?'), 0) + 1
    return len(elements), len(elements) > limit, parts


def _自检():
    """结构自检：不写文件，只验证各造型产出的图元字段与数量。"""
    import importlib.util
    from pathlib import Path
    here = Path(__file__).resolve().parent / '10.15-六版算法' / '几何工具.py'
    spec = importlib.util.spec_from_file_location('geo_check', here)
    geometry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(geometry)

    d = geometry.Drawing('自检.1')
    花瓣环(d, '花瓣', 20, 中心=(256, 256), 半径=158, 宽=76, 高=190,
           颜色='#FFD522', 交替色='#FFC60C')
    assert len(d.elements) == 20
    assert d.elements[0]['color'] == [255, 213, 34, 255]
    assert d.elements[1]['color'] == [255, 198, 12, 255]

    d2 = geometry.Drawing('自检.2')
    立体花瓣环(d2, '花瓣', 16, 中心=(256, 256), 半径=155, 宽=96, 高=192,
               暗边色='#DE9A08', 亮面色='#FFDD48')
    花心(d2, '花心', 中心=(256, 256), 直径=196, 外圈='#5C2A11', 底面='#6B3417')
    n = 颗粒(d2, '花心颗粒', 中心=(256, 256), 半径=79, 间距=24.5, 直径=20,
             颜色='#95502A', 种子=20261025)
    total, over, parts = 预算(d2.elements, 70)
    assert len(n) == 34 and total == 68 and not over, (len(n), total, over, parts)
    assert 颗粒(d2, '重复', 中心=(256, 256), 半径=79, 间距=24.5, 直径=20,
                颜色='#95502A', 种子=20261025)[3]['x'] == n[3]['x']
    return '造型自检通过：花瓣环20、立体花瓣环32+花心2+颗粒34=68，颗粒同种子可复现'


if __name__ == '__main__':
    print(_自检())
