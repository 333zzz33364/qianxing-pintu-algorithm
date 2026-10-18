"""太阳花：读取可编辑配方，调用 UI 通用六版生成素材库控件（平面／立体两张）。"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import math
import random
import sys

import cv2
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
ALGORITHM = PROJECT / '算法/10.15-六版算法'
TEMPLATE = ALGORITHM / '模板/QQ.gia'
RECIPE = HERE / '配方.json'
SOURCES = {
    '平面太阳花': HERE / '参考素材' / '平面太阳花.jpg',
    '立体太阳花': HERE / '参考素材' / '立体太阳花.jpg',
}


def load(name):
    spec = importlib.util.spec_from_file_location('sunflower_' + name, ALGORITHM / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core, geometry, pack = (load(name) for name in ('生成图元', '几何工具', '合包工具'))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def grains(d, part, cx, cy, radius, spacing, size, color, seed):
    """抖动点阵铺满花心：位置与直径都带确定性随机偏移，避免看出规则圆环。"""
    rng = random.Random(seed)
    points = []
    rows = int(radius // (spacing * 0.866)) + 1
    for row in range(-rows, rows + 1):
        base_y = row * spacing * 0.866
        offset = spacing / 2 if row % 2 else 0.0
        cols = int(radius // spacing) + 1
        for col in range(-cols, cols + 1):
            x = col * spacing + offset + rng.uniform(-0.34, 0.34) * spacing
            y = base_y + rng.uniform(-0.34, 0.34) * spacing
            r = math.hypot(x, y)
            if r <= radius:
                points.append((r, x, y, size * rng.uniform(0.84, 1.08)))
    points.sort()
    for i, (dist, x, y, diameter) in enumerate(points, 1):
        d.add(part, '%s%02d' % (part, i), 'ellipse', cx + x, cy + y,
              diameter, diameter, color)
    return len(points)


def flat_flower():
    """平面版：参考图第一张，20 瓣单色圆端花瓣＋深棕点纹花心。"""
    d = geometry.Drawing('平面太阳花.1')
    center = 256
    # 花瓣两色交替，模拟参考图中相邻花瓣的明暗差异，形成可辨认的花瓣分隔。
    for i in range(20):
        angle = i * 18.0
        rad = math.radians(angle)
        color = '#FFD522' if i % 2 == 0 else '#FFC60C'
        d.add('花瓣', f'第{i + 1}瓣', 'ellipse',
              center + 158 * math.sin(rad), center - 158 * math.cos(rad),
              76, 190, color, angle)
    d.add('花喉', '花瓣根部暖色带', 'ellipse', center, center, 206, 206, '#F9C516')
    d.add('花心', '花心外圈', 'ellipse', center, center, 186, 186, '#6E3616')
    d.add('花心', '花心底面', 'ellipse', center, center, 176, 176, '#974E22')
    grains(d, '花心颗粒', center, center, 80, 23, 19, '#5E2F12', 20261024)
    return d


def gloss_flower():
    """立体版：参考图第二张，错位后排暗瓣＋前排亮瓣，双层花心与分环明暗凸点。"""
    d = geometry.Drawing('立体太阳花.1')
    center = 256
    for i in range(16):
        angle = i * 22.5
        rad = math.radians(angle)
        d.add('花瓣', f'第{i + 1}瓣暗边', 'ellipse',
              center + 155 * math.sin(rad), center - 155 * math.cos(rad),
              96, 192, '#DE9A08', angle)
        d.add('花瓣', f'第{i + 1}瓣亮面', 'ellipse',
              center + 167 * math.sin(rad), center - 167 * math.cos(rad),
              60, 142, '#FFDD48', angle)
    d.add('花心', '花心外圈阴影', 'ellipse', center, center, 196, 196, '#5C2A11')
    d.add('花心', '花心圆顶', 'ellipse', center, center, 180, 180, '#6B3417')
    grains(d, '花心颗粒', center, center, 79, 24.5, 20, '#95502A', 20261025)
    return d


def initial_recipe():
    reference = core.extract(TEMPLATE)
    profiles = reference['image_profiles']
    groups = []
    for i, (key, drawing, canvas, crop) in enumerate([
        ('平面太阳花', flat_flower(), (512, 512), [135, 97, 805, 767]),
        ('立体太阳花', gloss_flower(), (512, 512), [143, 102, 807, 785]),
    ]):
        for e in drawing.elements:
            e['image_profile'] = next(k for k, v in profiles.items()
                                      if v['asset_id'] == core.ASSETS[e['shape']])
        source = SOURCES[key]
        source_name = key + source.suffix.lower()
        groups.append(dict(key=key, guid_base=1075500000 + i * 4096,
            index_base=790000 + i * 4096, reference_image='参考素材/' + source_name,
            reference_image_sha256=sha(source.read_bytes()), reference_crop=crop,
            recipe=dict(algorithm_version=core.VERSION, algorithm_name=core.ALGORITHM_NAME,
                name=drawing.name, canvas=dict(zip(('width', 'height'), canvas)),
                max_elements=70, element_budget_mode='extended', reference_sha256=sha(TEMPLATE.read_bytes()),
                image_profiles=profiles, elements=drawing.elements, adjustments={})))
    preserved = sorted(set((PROJECT / '交付物').rglob('*.gia')) |
                       set(p for p in ALGORITHM.rglob('*') if p.is_file()))
    preserved = {str(p.relative_to(PROJECT)): sha(p.read_bytes()) for p in preserved
                 if not p.is_relative_to(HERE)}
    return dict(schema_version=1, delivery_name='太阳花.1',
        algorithm='UI通用六版 Drawing/build/verify/render/bundle',
        visual_policy='平面与立体两版语义重绘；保留黄色圆端花瓣环、深棕点纹花心与整体比例；物体外部透明，省略背景与细碎反光',
        groups=groups, preserved_inputs=preserved)


def read_image(path):
    image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError('图片读取失败：' + str(path))
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
    elif image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    return image


def png(image):
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise ValueError('PNG编码失败')
    return encoded.tobytes()


def composite(image, bg, cell=512):
    h, w = image.shape[:2]
    factor = min((cell - 28) / w, (cell - 28) / h)
    image = cv2.resize(image, (round(w * factor), round(h * factor)), interpolation=cv2.INTER_AREA)
    result = np.full((cell, cell, 3), bg, np.uint8)
    h, w = image.shape[:2]
    x, y = (cell - w) // 2, (cell - h) // 2
    alpha = image[:, :, 3:4].astype(np.float32) / 255
    result[y:y+h, x:x+w] = np.round(image[:, :, :3] * alpha + result[y:y+h, x:x+w] * (1-alpha))
    return result


def compile_all(data):
    if data['schema_version'] != 1 or len(data['groups']) != 2:
        raise ValueError('必须是双图配方格式1')
    outputs, singles, scenes, pictures, reports = {}, [], [], [], []
    for definition in data['groups']:
        recipe = definition['recipe']
        guid, index = definition['guid_base'], definition['index_base']
        if recipe.get('max_elements') != 70 or recipe.get('element_budget_mode') != 'extended':
            raise ValueError('本交付已按用户确认扩展到每组70图元，须显式声明扩展预算')
        raw, elements = core.build(recipe, TEMPLATE, guid, index)
        scene = core.verify(raw, recipe, elements,
            [guid + i + 1 for i in range(len(elements))], guid, index)
        if core.build(recipe, TEMPLATE, guid, index)[0] != raw:
            raise ValueError('重复生成不一致')
        classic = core.convert_gia_bytes_to_classic(raw)
        if core.convert_gia_bytes_to_overlimit(classic) != raw:
            raise ValueError('单组模式往返失败')
        # 每个组均逐根、逐图元检查四平台，不仅检查默认场景。
        group = pack.split_bundle(raw)[0]
        for record in [group['root_record'], *group['unit_records'].values()]:
            rows = core.platform_rows(record)
            if any(row != rows['0'] for row in rows.values()):
                raise ValueError('四平台布局不一致')
        for e in elements:
            for x, y in geometry.element_boundary(e):
                if not 0 <= x <= recipe['canvas']['width'] or not 0 <= y <= recipe['canvas']['height']:
                    raise ValueError('图元越出画布：' + e['name'])
        rendered = cv2.imdecode(np.frombuffer(core.render(scene), np.uint8), cv2.IMREAD_UNCHANGED)
        size = (recipe['canvas']['width'], recipe['canvas']['height'])
        rendered = cv2.resize(rendered, size, interpolation=cv2.INTER_AREA)
        if rendered[0, 0, 3] != 0 or not np.any(rendered[:, :, 3] == 255):
            raise ValueError('预览透明背景或不透明主体不正确')
        source = HERE / definition['reference_image']
        if sha(source.read_bytes()) != definition['reference_image_sha256']:
            raise ValueError('参考素材哈希变化')
        name = recipe['name']
        outputs['单组/' + name + '.超限.gia'] = raw
        outputs['单组/' + name + '.经典.gia'] = classic
        outputs['预览/' + name + '.png'] = png(rendered)
        singles.append(raw)
        scenes.append(scene)
        pictures.append(rendered)
        reports.append(dict(name=name, element_count=len(elements), max_elements=recipe['max_elements'],
            canvas=recipe['canvas'], guid_base=guid, index_base=index,
            gia_sha256=sha(raw), classic_sha256=sha(classic), reference_sha256=sha(source.read_bytes()),
            primitive_counts={s: sum(e['shape'] == s for e in elements) for s in core.ASSETS},
            local_checks='预算、名称双写、GUID/索引、owner/locator/父子、四平台几何RGBA层序、原生参数、边界及模式往返通过'))
    bundle, readback = pack.bundle(singles)
    if [g['scene'] for g in readback] != scenes:
        raise ValueError('合包改变单组场景')
    classic = core.convert_gia_bytes_to_classic(bundle)
    if core.convert_gia_bytes_to_overlimit(classic) != bundle:
        raise ValueError('合集模式往返失败')
    outputs[data['delivery_name'] + '.超限.gia'] = bundle
    outputs[data['delivery_name'] + '.经典.gia'] = classic
    for key, digest in data['preserved_inputs'].items():
        if sha((PROJECT / key).read_bytes()) != digest:
            raise ValueError('既有资产或算法改变：' + key)
    overview = np.vstack([np.hstack([composite(p, bg) for p in pictures])
                          for bg in [(248, 248, 248), (49, 42, 36)]])
    outputs['预览总览.png'] = png(overview)
    comparisons = []
    for definition, picture in zip(data['groups'], pictures):
        source = read_image(HERE / definition['reference_image'])
        x1, y1, x2, y2 = definition['reference_crop']
        comparisons.append(np.hstack([composite(source[y1:y2, x1:x2], (248, 248, 248)),
                                      composite(picture, (248, 248, 248))]))
    outputs['参考对照.png'] = png(np.vstack(comparisons))
    report = dict(delivery=data['delivery_name'], groups=reports,
        group_count=2, element_count=sum(r['element_count'] for r in reports),
        identity_count=sum(r['element_count'] + 1 for r in reports),
        platform_rows=sum((r['element_count'] + 1) * 4 for r in reports),
        algorithm=core.ALGORITHM_NAME, template_sha256=sha(TEMPLATE.read_bytes()),
        source_hashes={p.name: sha(p.read_bytes()) for p in [Path(__file__), RECIPE,
            ALGORITHM / '生成图元.py', ALGORITHM / '几何工具.py', ALGORITHM / '合包工具.py']},
        preserved_file_count=len(data['preserved_inputs']), preserved_inputs=data['preserved_inputs'],
        checks=['每组不超过70图元（用户确认的扩展预算）', '两组独立身份与合包无冲突', '四平台变换完整且相同',
            '配方与回读几何颜色名称和层序一致', '原生样式附属参数保持', '重复生成及两模式往返',
            '合包前后根记录、图元记录及场景保持', '画布边界及透明背景', '既有交付和公共算法哈希保持'],
        bundle_sha256=sha(bundle), local_status='passed',
        editor_status='未验证：编辑器实际导入、显示及容量；未启动编辑器、服务或试玩')
    report['output_sha256'] = {name: sha(raw) for name, raw in outputs.items()}
    return outputs, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--init', action='store_true', help='首次保存配方及原始参考，不覆盖已有配方')
    mode.add_argument('--draft', action='store_true', help='生成至过程预览目录，可反复调整')
    mode.add_argument('--finalize', action='store_true', help='冻结本版，已交付内容不同则拒绝覆盖')
    mode.add_argument('--check', action='store_true', help='只读重建并检查最终GIA及预览')
    args = parser.parse_args()
    if args.init:
        if RECIPE.exists():
            raise FileExistsError('配方已存在，请直接编辑配方；拒绝重新初始化')
        data = initial_recipe()
        copies = {d['reference_image']: SOURCES[d['key']].read_bytes() for d in data['groups']}
        if any((HERE / name).exists() for name in copies):
            raise FileExistsError('参考副本已经存在，拒绝覆盖')
        for name, raw in copies.items():
            target = HERE / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        RECIPE.write_bytes(json_bytes(data))
        print(json.dumps({d['key']: len(d['recipe']['elements']) for d in data['groups']}, ensure_ascii=False))
        return
    data = json.loads(RECIPE.read_text(encoding='utf-8'))
    outputs, report = compile_all(data)
    report['check_only'] = args.check
    target_root = HERE / '过程预览' if args.draft else HERE
    if args.check:
        for name, raw in outputs.items():
            if (target_root / name).read_bytes() != raw:
                raise ValueError('最终交付与重建内容不一致：' + name)
        saved = json.loads((HERE / '验证记录.json').read_text(encoding='utf-8'))
        for key in ('source_hashes', 'output_sha256', 'bundle_sha256'):
            if saved[key] != report[key]:
                raise ValueError('冻结验证记录与当前来源不一致：' + key)
    else:
        if args.finalize:
            # 所有受保护目标先检查完，再写输出，避免冲突后留下部分新版文件。
            for name, raw in outputs.items():
                target = target_root / name
                if target.exists() and target.read_bytes() != raw:
                    raise FileExistsError('同版产物已存在且不同，须新建下一版：' + str(target))
        outputs['验证记录.json'] = json_bytes(report)
        for name, raw in outputs.items():
            target = target_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    print(json.dumps(dict(groups=[dict(name=g['name'], count=g['element_count']) for g in report['groups']],
        total=report['element_count'], identities=report['identity_count'],
        platform_rows=report['platform_rows'], check_only=args.check,
        bundle_sha256=report['bundle_sha256']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
