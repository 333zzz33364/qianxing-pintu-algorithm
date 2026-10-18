"""通用图元核心：配方编译、四平台、原生样式及保真重建。"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True

PROJECT = Path(__file__).resolve().parents[2]
ALGORITHM_DIR = Path(__file__).resolve().parent
DEFAULT_REFERENCE = ALGORITHM_DIR/'模板/微信.gia'
TOOL = Path(os.environ.get('UI_TOOLBOX_ROOT',
    str(PROJECT.parents[1] / '工具与依赖' / 'Miliastra-toolbox-primitive-shape'))).resolve()
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(TOOL / 'gia'))
import gia_lua as reader
from convert_to_classic import convert_gia_bytes_to_classic
from convert_to_overlimit import convert_gia_bytes_to_overlimit

VERSION = 1  # 配方格式号保持兼容；算法名称独立于格式号和交付号。
ALGORITHM_NAME = '10.15-六版算法'
ASSETS = {'rect': 100001, 'ellipse': 100002, 'triangle': 100003}
DEFAULT_GUID_BASE = 1073760000


def check_guid_scope(guid, locator_type):
    """保守沿用已能显示的 QQ 标识号段，避免移入其他类型的高位区域。"""
    if not isinstance(guid,int) or isinstance(guid,bool) or guid <= 0 or guid >> 27 != locator_type:
        raise ValueError(f'GUID {guid} 与参考引用类型 {locator_type} 的号段不匹配')


def vi(value):
    out = bytearray()
    while value > 127:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def fields(data):
    """保留字段次序；未改动的叶字段保留原始字节。"""
    result, pos = [], 0
    while pos < len(data):
        start = pos
        key, pos = reader._varint(data, pos)
        tag, wire = key >> 3, key & 7
        if not tag:
            raise ValueError('无效字段编号')
        if wire == 0:
            value, pos = reader._varint(data, pos)
        elif wire in (1, 2, 5):
            size = 8 if wire == 1 else 4
            if wire == 2:
                size, pos = reader._varint(data, pos)
            value, pos = data[pos:pos + size], pos + size
            if pos > len(data):
                raise ValueError('字段截断')
        else:
            raise ValueError('不支持的字段类型')
        result.append([tag, wire, value, data[start:pos]])
    return result


def encode(items):
    out = bytearray()
    for tag, wire, value, raw in items:
        if raw is not None:
            out.extend(raw)
            continue
        out.extend(vi(tag * 8 + wire))
        if wire == 0:
            out.extend(vi(value))
        elif wire == 2:
            out.extend(vi(len(value)))
            out.extend(value)
        else:
            out.extend(value)
    return bytes(out)


def get(items, tag, default=b''):
    return next((v for t, w, v, raw in items if t == tag), default)


def put(items, tag, value, wire=2):
    replacement = [tag, wire, value, None]
    indices = [i for i, item in enumerate(items) if item[0] == tag]
    if indices:
        items[indices[0]] = replacement
        for i in reversed(indices[1:]):
            del items[i]
    else:
        items.append(replacement)


def patch(data, path, value, wire=2):
    items = fields(data)
    if len(path) == 1:
        put(items, path[0], value, wire)
    else:
        put(items, path[0], patch(get(items, path[0]), path[1:], value, wire))
    return encode(items)


def content(unit):
    return fields(get(fields(get(fields(unit), 19)), 1))


def component_name(c):
    for tag, wire, raw, original in c:
        if tag == 505:
            comp = fields(raw)
            if get(comp, 502, 0) == 15:
                return get(fields(get(comp, 12)), 501).decode('utf-8')
    raise ValueError('缺少名称组件')


def registration_index(c):
    """控件注册索引独立于 GUID；克隆时必须重新分配，不能沿用模板值。"""
    values=[]
    for tag,wire,payload,raw in c:
        if tag==502:
            info=fields(payload)
            if get(info,502,0)==6:
                values.append(get(fields(get(info,12)),501,0))
    if len(values)!=1 or isinstance(values[0],bool) or not isinstance(values[0],int) or not 1<=values[0]<=2**31-1:
        raise ValueError('控件必须有一个有效注册索引')
    return values[0]


def parse_scene(raw):
    """仅解析几何；原生遮罩仍在 GIA 中保留，预览时必须单独检查。"""
    scene = reader.parse_material_gia(raw, ignore_mask=True)
    scene['native_mask'] = scene['ignored_mask']
    scene['unsupported_assets'] = sorted({r[0] for r in scene['records']} - set(ASSETS.values()))
    return scene


def platform_rows(unit):
    components = reader._components(reader._fields(encode(content(unit))))
    transform = reader._message(reader._message(components[12], 503), 13)
    result = {}
    platforms = list(reader._messages(reader._message(transform, 12), 501))
    if len(platforms) != 4:
        raise ValueError('平台布局必须恰有四条，不能缺失或重复')
    for pf in platforms:
        rect = reader._message(pf, 502)
        key = str(reader._get(pf, 501))
        if key in result:
            raise ValueError('平台布局ID重复')
        result[key] = (reader._vector(rect, 504) + reader._vector(rect, 505)
            + reader._vector(rect, 506) + reader._vector(rect, 501, (1,2,3), (1,1,1))[:2]
            + [reader._vector(rect, 508, (1,2,3), (0,0,0))[2]])
        for value in result[key]:
            number(value, '模板平台变换')
        if min(result[key][2:4]) <= 0 or 0 in result[key][6:8]:
            raise ValueError('模板平台尺寸或缩放无效')
    if set(result) != {'0','1','2','3'}:
        raise ValueError('平台布局不完整')
    return result


def element_rows(e, canvas):
    default = [e['x']-canvas['width']/2, canvas['height']/2-e['y'],
               e['width'],e['height']] + e['pivot'] + e['scale'] + [-e['rotation']]
    source = e.get('platforms')
    if source is None:
        return {str(i):default[:] for i in range(4)}
    if not isinstance(source,dict) or set(source) != {'0','1','2','3'}:
        raise ValueError('platforms 必须包含四个平台')
    for values in source.values():
        if not isinstance(values,list) or len(values)!=9:
            raise ValueError('平台变换需要九个数值')
        for value in values:number(value,'平台变换')
        if min(values[2:4])<=0 or 0 in values[6:8]:
            raise ValueError('平台尺寸和缩放无效')
    base=source['0']; result={}
    for key,values in source.items():
        result[key]=[values[i]*(default[i]/base[i]) if i in (2,3,6,7)
                     else values[i]+default[i]-base[i] for i in range(9)]
    return result


def mask_payload(unit):
    return [get(fields(get(fields(v),503)),47) for t,w,v,r in content(unit)
            if t==505 and get(fields(v),502,0)==56]


def image_payload(unit):
    """仅定位已查证的静态图片载荷，不解释未知参数语义。"""
    images = [get(fields(get(fields(v), 503)), 31) for t, w, v, r in content(unit)
              if t == 505 and get(fields(v), 502, 0) == 38]
    if len(images) != 1:
        raise ValueError('控件必须有一个静态图片组件')
    return images[0]


def image_parameters(payload):
    """资源号和颜色可编辑，其余图片参数保留次序与原始字节。"""
    return encode([item for item in fields(payload) if item[0] not in (2, 4)])


def profile_for_element(recipe, element):
    key = element.get('image_profile')
    if key is None:
        return None
    profiles = recipe.get('image_profiles', {})
    if not isinstance(key, str) or not isinstance(profiles, dict) or key not in profiles:
        raise ValueError('图片样式不存在')
    profile = profiles[key]
    if not isinstance(profile, dict) or type(profile.get('asset_id')) is not int or profile['asset_id'] <= 0:
        raise ValueError('图片样式资源 ID 无效')
    if type(profile.get('source_guid')) is not int or profile['source_guid'] <= 0:
        raise ValueError('图片样式参考控件无效')
    asset = ASSETS.get(element.get('shape'), element.get('asset_id'))
    if asset != profile['asset_id']:
        raise ValueError('图元资源与图片样式不匹配，请同时调整 shape/asset_id 与 image_profile')
    return profile


def validate_profiles(recipe, units):
    profiles = recipe.get('image_profiles', {})
    if not isinstance(profiles, dict):
        raise ValueError('image_profiles 必须为对象')
    result = {}
    for key, profile in profiles.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(profile, dict):
            raise ValueError('图片样式名称与定义无效')
        source = profile.get('source_guid')
        if type(source) is not int or source not in units:
            raise ValueError('图片样式参考控件不在当前参考中')
        payload = image_payload(units[source])
        if type(profile.get('asset_id')) is not int or profile['asset_id'] != get(fields(payload), 2, 0):
            raise ValueError('图片样式资源与参考不一致')
        if profile.get('parameters_hex') != image_parameters(payload).hex():
            raise ValueError('图片样式参数与参考不一致，请重新提取后核对')
        result[key] = payload
    return result


def load_reference(path):
    original = path.read_bytes()
    raw = convert_gia_bytes_to_overlimit(original)
    scene = parse_scene(raw)
    if scene['missing_refs']:
        raise ValueError('参考存在悬空子引用')
    top = fields(raw[20:-4])
    primary = get(top, 1)
    root_content = content(primary)
    root_guid = get(root_content, 501, 0)
    units = {get(content(v), 501, 0): v for t, w, v, r in top if t == 2}
    order = list(reversed(reader._children(reader._fields(encode(root_content)))))
    if set(order) != set(units):
        raise ValueError('存在未关联图元')
    for guid in order:
        if get(fields(units[guid]), 3).decode('utf-8') != component_name(content(units[guid])):
            raise ValueError('参考图元两处名称不一致')
    return original, top, primary, root_guid, units, order, scene


def extract(path):
    original, top, primary, root_guid, units, order, scene = load_reference(path)
    width, height = scene['root_transform'][2:4]
    elements, profiles, profile_keys = [], {}, {}
    for guid, row in zip(order, scene['records']):
        name = component_name(content(units[guid]))
        if row[7:11] != [.5] * 4 or len(row) != 18:
            raise ValueError('当前配方不支持非居中锚点或 X/Y 轴旋转')
        shape = next((s for s, a in ASSETS.items() if a == row[0]), None)
        if shape is None:
            shape = 'native_image'
        pieces = name.split('_')
        payload = image_payload(units[guid])
        parameters = image_parameters(payload).hex()
        signature = (row[0], parameters)
        if signature not in profile_keys:
            key = f'image_{row[0]}_{len(profiles)+1}'
            profiles[key] = dict(asset_id=row[0], source_guid=guid, parameters_hex=parameters)
            profile_keys[signature] = key
        elements.append(dict(id=f'g{guid}', name=name, image_profile=profile_keys[signature],
                             part=pieces[-2] if len(pieces)>2 else '图片',
                             role=pieces[-1] if len(pieces)>2 else '原生资源',
                             source_guid=guid, guid=guid, index=registration_index(content(units[guid])),
                             shape=shape, x=row[1] + width/2, y=height/2 - row[2],
                             width=row[3], height=row[4], pivot=row[5:7],
                             scale=row[11:13], rotation=-row[13], color=row[14:18],
                             asset_id=row[0], platforms=platform_rows(units[guid])))
    return dict(algorithm_version=VERSION, algorithm_name=ALGORITHM_NAME,
                name=component_name(content(primary)), canvas=dict(width=width, height=height),
                max_elements=49, reference_sha256=hashlib.sha256(original).hexdigest(),
                root_guid=root_guid, root_index=registration_index(content(primary)),
                root_platforms=platform_rows(primary),
                image_profiles=profiles, elements=elements, adjustments={})


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e7:
        raise ValueError(f'{label} 必须是范围内的有限数值')
    return value


def compile_recipe(recipe):
    if not isinstance(recipe,dict):
        raise ValueError('配方必须是对象')
    if not isinstance(recipe.get('canvas'),dict):
        raise ValueError('canvas 必须是对象')
    if not isinstance(recipe.get('elements'),list) or any(not isinstance(e,dict) for e in recipe['elements']):
        raise ValueError('elements 必须是图元对象数组')
    if type(recipe.get('algorithm_version')) is not int or recipe['algorithm_version'] != VERSION:
        raise ValueError('不支持的算法配方版本')
    width = number(recipe['canvas']['width'], '画布宽')
    height = number(recipe['canvas']['height'], '画布高')
    if width <= 0 or height <= 0:
        raise ValueError('画布尺寸必须为正')
    if not isinstance(recipe.get('name'), str) or not recipe['name'].strip():
        raise ValueError('素材组名称不能为空')
    limit = recipe.get('max_elements', 49)
    ceiling = 2048 if recipe.get('element_budget_mode') == 'extended' else 49
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= ceiling:
        raise ValueError(f'图元上限必须为 1～{ceiling}；扩展预算需显式声明')
    adjustments = recipe.get('adjustments', {})
    if not isinstance(adjustments,dict):
        raise ValueError('adjustments 必须是对象')
    if set(adjustments) - {'parts', 'elements'}:
        raise ValueError('未知调整范围')
    allowed = {'dx', 'dy', 'scale', 'rotation', 'color', 'enabled'}
    for group in adjustments.values():
        if not isinstance(group, dict):
            raise ValueError('调整项必须为对象')
        for settings in group.values():
            if not isinstance(settings,dict):
                raise ValueError('图元调整参数必须是对象')
            if set(settings) - allowed:
                raise ValueError('未知调整参数')
    parts = {e.get('part') for e in recipe['elements']}
    names = {e.get('id', e.get('name')) for e in recipe['elements']}
    if set(adjustments.get('parts', {})) - parts or set(adjustments.get('elements', {})) - names:
        raise ValueError('调整目标不存在')
    result, seen = [], set()
    for original in recipe['elements']:
        e = copy.deepcopy(original)
        profile = profile_for_element(recipe, e)
        if profile is not None:
            e.setdefault('source_guid', profile['source_guid'])
        name = e.get('name')
        identity=e.get('id',name)
        if not isinstance(name,str) or not name.strip():
            raise ValueError('图元显示名称不能为空')
        if not isinstance(identity,str) or not identity.strip() or identity in seen:
            raise ValueError('图元独立 ID 必须非空且唯一')
        seen.add(identity)
        for key in ('part', 'role'):
            if not isinstance(e.get(key), str) or not e[key].strip() or e[key].isdigit():
                raise ValueError('图元必须注明部件与作用')
        # 在算术运算前检查原值，防止布尔值经加法变成整数后逃过校验。
        for key in ('x', 'y', 'width', 'height', 'rotation'):
            number(e[key], key)
        enabled = True
        for settings in (adjustments.get('parts', {}).get(e['part'], {}),
                         adjustments.get('elements', {}).get(identity, {})):
            if 'enabled' in settings:
                if not isinstance(settings['enabled'], bool):
                    raise ValueError('enabled 必须是布尔值')
                enabled = enabled and settings['enabled']
            e['x'] += number(settings.get('dx', 0), 'dx')
            e['y'] += number(settings.get('dy', 0), 'dy')
            factor = number(settings.get('scale', 1), '部件缩放')
            if factor <= 0:
                raise ValueError('部件缩放必须为正')
            e['width'] *= factor
            e['height'] *= factor
            e['rotation'] += number(settings.get('rotation', 0), '旋转')
            if 'color' in settings:
                e['color'] = settings['color']
        if not enabled:
            continue
        if e['shape'] not in ASSETS and e['shape']!='native_image':
            raise ValueError('仅支持基础图元或带参考的原生图片')
        if e['shape']=='native_image' and (type(e.get('asset_id')) is not int or e['asset_id']<=0 or not e.get('source_guid')):
            raise ValueError('原生图片必须有有效资源 ID 和参考控件')
        for key in ('x', 'y', 'width', 'height', 'rotation'):
            number(e[key], key)
        if min(e['width'], e['height']) <= 0:
            raise ValueError('图元尺寸必须为正')
        for key in ('pivot', 'scale'):
            if len(e.get(key, [])) != 2:
                raise ValueError(f'{key} 需要两个数值')
            for value in e[key]:
                number(value, key)
        if 0 in e['scale']:
            raise ValueError('图元缩放不能为零')
        if len(e.get('color', [])) != 4 or any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in e['color']):
            raise ValueError('颜色必须是四个 0～255 整数 RGBA')
        element_rows(e,recipe['canvas'])
        result.append(e)
    if not 1 <= len(result) <= limit:
        raise ValueError(f'有效图元数量必须为 1～{limit}')
    return result


def vec(values, tags=(501, 502)):
    return encode([[t, 5, struct.pack('<f', v), None] for t, v in zip(tags, values)])


def update_content(c, guid, name, row=None, parent=None, children=None, index=None):
    put(c, 501, guid, 0)
    if parent is not None:
        put(c, 504, parent, 0)
    if children is not None:
        put(c, 503, b''.join(vi(x) for x in children))
    for item in c:
        tag, wire, data, raw = item
        if tag not in (502, 505):
            continue
        comp = fields(data)
        kind = get(comp, 502, 0)
        if tag == 502 and kind == 5:
            data = patch(data, [11, 501], guid, 0)
        if tag == 502 and kind == 6 and index is not None:
            data = patch(data, [12, 501], index, 0)
        if tag == 505 and kind == 15:
            data = patch(data, [12, 501], name.encode('utf-8'))
        if get(comp, 503, None) is not None:
            body = fields(get(fields(data), 503))
            if get(body, 504, None) is not None:
                data = patch(data, [503, 504, 4], guid, 0)
        if tag == 505 and kind == 12 and row is not None:
            component = fields(data)
            body = fields(get(component, 503))
            transform = fields(get(body, 13))
            layouts = fields(get(transform, 12))
            for platform in layouts:
                if platform[0] != 501:
                    continue
                pf = fields(platform[2])
                rect = fields(get(pf, 502))
                values_row = row[str(get(pf,501,0))] if isinstance(row,dict) else row
                for key, values, tags in ((504, values_row[0:2], (501, 502)), (505, values_row[2:4], (501, 502)),
                                           (506, values_row[4:6], (501, 502)), (501, values_row[6:8], (1, 2)),
                                           (508, [values_row[8]], (3,))):
                    # 保留向量内未知字段，只覆盖已知坐标分量。
                    vv = fields(get(rect, key))
                    for t, v in zip(tags, values):
                        put(vv, t, struct.pack('<f', v), 5)
                    put(rect, key, encode(vv))
                put(pf, 502, encode(rect))
                platform[2], platform[3] = encode(pf), None
            put(transform, 12, encode(layouts))
            data = patch(data, [503, 13], encode(transform))
        item[2], item[3] = data, None
    return encode(c)


def unit_from(template, guid, name, row, parent=None, children=None, image=None, index=None):
    u = fields(template)
    put(u, 1, patch(get(u, 1), [4], guid, 0))
    put(u, 3, name.encode('utf-8'))
    c = fields(update_content(content(template), guid, name, row, parent, children, index))
    if image is not None:
        asset, rgba = image
        r, g, b, a = rgba
        color = a << 24 | r << 16 | g << 8 | b
        for item in c:
            if item[0] == 505 and get(fields(item[2]), 502, 0) == 38:
                data = patch(item[2], [503, 31, 2], asset, 0)
                item[2], item[3] = patch(data, [503, 31, 4], color, 0), None
    put(u, 19, patch(get(u, 19), [1], encode(c)))
    if children is not None:
        locator = get(u, 1)
        replacements = [[2, 2, patch(locator, [4], child, 0), None] for child in children]
        u = [item for item in u if item[0] != 2] + replacements
    return encode(u)


def build(recipe, reference, guid_base=DEFAULT_GUID_BASE, index_base=None):
    elements = compile_recipe(recipe)
    original, top, primary, root_guid, units, order, scene = load_reference(reference)
    profiles = validate_profiles(recipe, units)
    reference_indices={registration_index(content(unit))for unit in [primary]+list(units.values())}
    if index_base is None:index_base=max(reference_indices)+1
    if (isinstance(index_base,bool) or not isinstance(index_base,int)
            or not 1<=index_base<=2**31-1-len(elements)):
        raise ValueError('控件注册索引起点超出范围')
    if set(range(index_base,index_base+len(elements)+1))&reference_indices:
        raise ValueError('生成控件注册索引与参考冲突')
    if recipe.get('reference_sha256') != hashlib.sha256(original).hexdigest():
        raise ValueError('参考文件哈希改变，请重新提取配方后核对')
    if isinstance(guid_base, bool) or not isinstance(guid_base, int) or not 1 <= guid_base <= 2**31 - len(elements) - 1:
        raise ValueError('GUID 起点超出范围')
    guids = [guid_base + i + 1 for i in range(len(elements))]
    reference_type = get(fields(get(fields(primary),1)),3,0)
    check_guid_scope(guid_base,reference_type)
    check_guid_scope(guids[-1],reference_type)
    if set([guid_base] + guids) & set([root_guid] + list(units)):
        raise ValueError('生成 GUID 与参考资产冲突')
    generated = []
    for ordinal,(e, guid) in enumerate(zip(elements, guids)):
        source = e.get('source_guid')
        if source is not None and source not in units:
            raise ValueError('source_guid 不在当前参考中')
        template = units[source] if source is not None else units[order[0]]
        profile_key = e.get('image_profile')
        if profile_key is not None:
            # 只替换图片载荷，其余组件继续沿用图元自己的模板。
            c = content(template)
            for item in c:
                if item[0] == 505 and get(fields(item[2]), 502, 0) == 38:
                    item[2] = patch(item[2], [503, 31], profiles[profile_key])
                    item[3] = None
            template = patch(template, [19, 1], encode(c))
        elif (e['shape'] == 'native_image' or get(fields(image_payload(template)), 2, 0) not in ASSETS.values()) and (
                ASSETS.get(e['shape'], e.get('asset_id')) != get(fields(image_payload(template)), 2, 0)):
            raise ValueError('更换原生资源需选择已核对的图片样式')
        row = element_rows(e, recipe['canvas'])
        asset = ASSETS[e['shape']] if e['shape'] in ASSETS else e['asset_id']
        generated.append(unit_from(template, guid, e['name'], row, parent=guid_base,
                                   image=(asset, e['color']),index=index_base+ordinal+1))
    children = list(reversed(guids))
    root_row = [0, 0, recipe['canvas']['width'], recipe['canvas']['height'], .5, .5, 1, 1, 0]
    root = unit_from(primary, guid_base, recipe['name'], root_row, children=children,index=index_base)
    # 不猜测未知组件中的数值含义；参考的未知字段继续保留。
    output = []
    for item in top:
        if item[0] == 1:
            output.append([1, 2, root, None])
        elif item[0] == 2:
            continue
        else:
            output.append(item)
    output += [[2, 2, unit, None] for unit in reversed(generated)]
    body = encode(output)
    result = struct.pack('>5I', len(body)+20, 1, 0x326, 3, len(body)) + body + b'\0\0\x06\x79'
    verify(result, recipe, elements, guids, guid_base,index_base)
    generated_units = {get(content(v), 501, 0): v for t, w, v, r in fields(result[20:-4]) if t == 2}
    for e, guid in zip(elements, guids):
        expected = profiles[e['image_profile']] if e.get('image_profile') is not None else image_payload(
            units[e['source_guid']] if e.get('source_guid') is not None else units[order[0]])
        if image_parameters(image_payload(generated_units[guid])) != image_parameters(expected):
            raise ValueError('图片原生参数回读不一致')
    if mask_payload(primary)!=mask_payload(root):
        raise ValueError('生成改变了原生遮罩配置')
    return result, elements


def verify(raw, recipe, elements, guids, root_guid,index_base=None):
    scene = parse_scene(raw)
    if scene['missing_refs'] or len(scene['records']) != len(elements):
        raise ValueError('回读图元数或引用错误')
    top = fields(raw[20:-4])
    root = get(top, 1)
    rc = content(root)
    if get(rc, 501, 0) != root_guid or component_name(rc) != recipe['name']:
        raise ValueError('根身份或名称回读错误')
    root_index=registration_index(rc)
    if index_base is not None and root_index!=index_base:raise ValueError('根注册索引不一致')
    used_indices={root_index}
    if get(fields(get(fields(root), 1)), 4, 0) != root_guid:
        raise ValueError('根 locator 身份错误')
    root_expected = [0, 0, recipe['canvas']['width'], recipe['canvas']['height'], .5, .5, .5, .5, .5, .5, 1, 1, 0]
    if any(not math.isclose(a,b,abs_tol=1e-4,rel_tol=1e-6)for a,b in zip(scene['root_transform'],root_expected)):
        raise ValueError('根画布回读错误')
    if reader._children(reader._fields(encode(rc))) != list(reversed(guids)):
        raise ValueError('绘制层序回读错误')
    rootloc = [get(fields(v), 4, 0) for t, w, v, r in fields(root) if t == 2]
    if rootloc != list(reversed(guids)):
        raise ValueError('根 locator 回读错误')
    units = {get(content(v), 501, 0): v for t, w, v, r in top if t == 2}
    if set(units) != set(guids):
        raise ValueError('图元 GUID 不唯一或有孤立实体')
    for ordinal,(e, guid, row) in enumerate(zip(elements, guids, scene['records'])):
        u = units[guid]
        c = content(u)
        index=registration_index(c)
        if index in used_indices:raise ValueError('控件注册索引重复')
        used_indices.add(index)
        if index_base is not None and index!=index_base+ordinal+1:raise ValueError('图元注册索引不一致')
        if get(c, 504, 0) != root_guid or component_name(c) != e['name'] or get(fields(u), 3).decode('utf-8') != e['name']:
            raise ValueError('图元名称或父引用错误')
        if get(fields(get(fields(u), 1)), 4, 0) != guid:
            raise ValueError('图元 locator 错误')
        for tag, w, v, rawfield in c:
            if tag in (502, 505):
                comp = fields(v)
                body = fields(get(comp, 503))
                owner = get(body, 504, None)
                if owner is not None and get(fields(owner), 4, 0) != guid:
                    raise ValueError('组件 owner 错误')
                if tag == 502 and get(comp, 502, 0) == 5 and get(fields(get(comp, 11)), 501, 0) != guid:
                    raise ValueError('图元内部身份错误')
        asset = ASSETS[e['shape']] if e['shape'] in ASSETS else e['asset_id']
        expected = [asset, e['x']-recipe['canvas']['width']/2,
                    recipe['canvas']['height']/2-e['y'], e['width'], e['height']] + e['pivot'] + [.5]*4 + e['scale'] + [-e['rotation']] + e['color']
        if len(row) != len(expected) or any(not math.isclose(a, b, abs_tol=1e-4, rel_tol=1e-6) for a, b in zip(row, expected)):
            raise ValueError(f"图元几何或颜色不一致：{e['name']}")
        # 键鼠、手机、手柄和额外平台均逐项回读，避免只核默认平台。
        components = reader._components(reader._fields(encode(c)))
        transform = reader._message(reader._message(components[12], 503), 13)
        platforms = list(reader._messages(reader._message(transform, 12), 501))
        if {reader._get(p,501) for p in platforms} != {0,1,2,3} or len(platforms) != 4:
            raise ValueError('平台布局不完整')
        for platform in platforms:
            rect = reader._message(platform,502)
            values = (reader._vector(rect,504) + reader._vector(rect,505) + reader._vector(rect,506)
                      + reader._vector(rect,501,(1,2,3),(1,1,1))[:2]
                      + [reader._vector(rect,508,(1,2,3),(0,0,0))[2]])
            wanted = element_rows(e,recipe['canvas'])[str(reader._get(platform,501))]
            if any(not math.isclose(a,b,abs_tol=1e-4,rel_tol=1e-6)for a,b in zip(values,wanted)):
                raise ValueError('平台图元变换回读错误')
    return scene


def identity(value, label):
    if type(value) is not int or not 1 <= value <= 2**31 - 1:
        raise ValueError(label + '必须为正整数且不超过2^31-1')
    return value


def rebuild(recipe, reference, guid_base=1074300000, index_base=200000):
    """编辑当前控件，保持现有身份；仅为新增图元从调用方的保留区分配身份。

    reference 是单组原生模板。guid/index 不填写即为新增身份；source_guid
    仅选择样式模板，不能被当作新增控件的身份。无可见/身份变动时原字节返回。
    """
    elements = compile_recipe(recipe)
    original, top, primary, source_root, units, order, source_scene = load_reference(reference)
    if recipe.get('reference_sha256') != hashlib.sha256(original).hexdigest():
        raise ValueError('模板哈希改变，请重新提取配方后核对')
    profiles = validate_profiles(recipe, units)
    root_guid = identity(recipe.get('root_guid', source_root), '根GUID')
    root_index = identity(recipe.get('root_index', registration_index(content(primary))), '根索引')
    identity(guid_base, '新增GUID起点')
    identity(index_base, '新增索引起点')
    reference_type = get(fields(get(fields(primary), 1)), 3, 0)
    check_guid_scope(root_guid, reference_type)
    # root_platforms 保留原根位置、缩放及四平台差异；canvas改变按比例调整根尺寸。
    root_rows = copy.deepcopy(recipe.get('root_platforms', platform_rows(primary)))
    if not isinstance(root_rows, dict) or set(root_rows) != {'0', '1', '2', '3'}:
        raise ValueError('根布局必须包含四个平台')
    for row in root_rows.values():
        if not isinstance(row, list) or len(row) != 9:
            raise ValueError('根平台变换需要九个数值')
        for value in row:
            number(value, '根平台变换')
        if min(row[2:4]) <= 0 or 0 in row[6:8]:
            raise ValueError('根平台尺寸或缩放无效')
    width, height = source_scene['root_transform'][2:4]
    for row in root_rows.values():
        row[2] *= recipe['canvas']['width'] / width
        row[3] *= recipe['canvas']['height'] / height
    generated, guids = {}, []
    used_indices = {root_index}
    for ordinal, element in enumerate(elements):
        guid = identity(element.get('guid', guid_base + ordinal + 1), '图元GUID')
        index = identity(element.get('index', index_base + ordinal + 1), '图元索引')
        check_guid_scope(guid, reference_type)
        if guid == root_guid or guid in generated or index in used_indices:
            raise ValueError('图元GUID或控件索引重复')
        used_indices.add(index)
        source = element.get('source_guid')
        if source is not None and (type(source) is not int or source not in units):
            raise ValueError('source_guid不在当前模板中')
        asset = ASSETS.get(element['shape'], element.get('asset_id'))
        if source is None:
            candidates = [g for g in order if get(fields(image_payload(units[g])), 2, 0) == asset]
            if not candidates:
                candidates = [g for g in order if get(fields(image_payload(units[g])), 2, 0) in ASSETS.values()]
            if not candidates:
                raise ValueError('缺少匹配的基础图元模板，原生图片必须指定source_guid')
            source = candidates[0]
        template = units[source]
        source_payload = image_payload(template)
        if element.get('image_profile') is not None:
            expected_payload = profiles[element['image_profile']]
        else:
            source_asset = get(fields(source_payload), 2, 0)
            if (element['shape'] == 'native_image' or source_asset not in ASSETS.values()) and source_asset != asset:
                raise ValueError('更换原生资源必须选择已核对的图片样式')
            expected_payload = source_payload
        if (image_parameters(expected_payload) != image_parameters(source_payload)
                or get(fields(expected_payload), 2, 0) != get(fields(source_payload), 2, 0)):
            changed = content(template)
            for item in changed:
                if item[0] == 505 and get(fields(item[2]), 502, 0) == 38:
                    item[2] = patch(item[2], [503, 31], expected_payload)
                    item[3] = None
            template = patch(template, [19, 1], encode(changed))
        rows = element_rows(element, recipe['canvas'])
        rgba = element['color']
        packed_color = rgba[3] << 24 | rgba[0] << 16 | rgba[1] << 8 | rgba[2]
        source_content = content(template)
        payload = image_payload(template)
        unchanged = (guid == source and index == registration_index(source_content)
            and root_guid == get(source_content, 504, 0)
            and element['name'] == component_name(source_content)
            and rows == platform_rows(template)
            and asset == get(fields(payload), 2, 0)
            and packed_color == get(fields(payload), 4, 0))
        raw_unit = template if unchanged else unit_from(template, guid, element['name'], rows,
            parent=root_guid, image=(asset, rgba), index=index)
        if image_parameters(image_payload(raw_unit)) != image_parameters(expected_payload):
            raise ValueError('修改改变了原生图片附属参数')
        if mask_payload(raw_unit) != mask_payload(units[source]):
            raise ValueError('修改改变了图元遮罩')
        generated[guid] = raw_unit
        guids.append(guid)
    children = list(reversed(guids))
    root_unchanged = (root_guid == source_root
        and root_index == registration_index(content(primary))
        and recipe['name'] == component_name(content(primary))
        and children == list(reversed(order)) and root_rows == platform_rows(primary))
    root = primary if root_unchanged else unit_from(primary, root_guid, recipe['name'],
        root_rows, children=children, index=root_index)
    if mask_payload(root) != mask_payload(primary):
        raise ValueError('修改改变了根遮罩')
    if root == primary and guids == order and generated == units:
        return original, elements
    shared = [item for item in top if item[0] not in (1, 2)]
    body = encode([[1, 2, root, None]] + [[2, 2, generated[g], None] for g in children] + shared)
    result = struct.pack('>5I', len(body)+20, 1, 0x326, 3, len(body)) + body + b'\0\0\x06\x79'
    scene = parse_scene(result)
    if scene['missing_refs'] or len(scene['records']) != len(elements):
        raise ValueError('修改后图元数量或引用错误')
    # 不只验证元数据：以实际落盘记录的四平台变换、资源、颜色、层序回读。
    actual = {get(content(v), 501, 0): v for t, w, v, r in fields(result[20:-4]) if t == 2}
    for element, guid in zip(elements, guids):
        for key, row in platform_rows(actual[guid]).items():
            expected = element_rows(element, recipe['canvas'])[key]
            if any(not math.isclose(a, b, abs_tol=1e-4, rel_tol=1e-6) for a, b in zip(row, expected)):
                raise ValueError('修改后四平台变换不一致')
    return result, elements


def render(scene):
    """从实际 GIA 回读生成本地预览；不是编辑器渲染验证。"""
    if scene.get('native_mask',scene.get('ignored_mask',False)):
        raise ValueError('原生遮罩已保留；本地预览无法等价模拟，请在千星编辑器确认')
    unsupported = sorted({r[0] for r in scene['records']} - set(ASSETS.values()))
    if unsupported:
        raise ValueError(f'原生图片资源 {unsupported} 已保留；缺少资源图，不能伪造预览')
    import cv2
    import numpy as np
    width, height = scene['root_transform'][2:4]
    zoom = 4
    canvas = np.zeros((round(height*zoom), round(width*zoom), 4), dtype=np.float32)
    for row in scene['records']:
        asset, x, y, w, h, px, py = row[:7]
        sx, sy, angle = row[11:14]
        rgba = row[14:18]
        w, h = w*zoom, h*zoom
        cx, cy = (x+width/2)*zoom, (height/2-y)*zoom
        layer = np.zeros(canvas.shape, dtype=np.uint8)
        left, right = cx-px*w*sx, cx+(1-px)*w*sx
        bottom, top = cy+py*h*sy, cy-(1-py)*h*sy
        box = [min(left,right),min(top,bottom),max(left,right),max(top,bottom)]
        radians=math.radians(angle)
        def rotate_point(point):
            dx,dy=point[0]-cx,point[1]-cy
            return (cx+dx*math.cos(radians)+dy*math.sin(radians),
                    cy-dx*math.sin(radians)+dy*math.cos(radians))
        if asset == 100001:
            points=[rotate_point(p)for p in [(left,top),(right,top),(right,bottom),(left,bottom)]]
            cv2.fillPoly(layer,[np.round(points).astype(np.int32)],rgba)
        elif asset == 100002:
            center=rotate_point(((left+right)/2,(top+bottom)/2))
            cv2.ellipse(layer,tuple(round(v)for v in center),
                        (max(1,round(abs(w*sx)/2)), max(1,round(abs(h*sy)/2))), -angle, 0, 360, rgba, -1)
        else:
            points = [(cx+(.5-px)*w*sx, top), (left,bottom), (right,bottom)]
            points=[rotate_point(p)for p in points]
            cv2.fillPoly(layer,[np.round(points).astype(np.int32)],rgba)
        # 先变换几何再裁切，避免大三角形在旋转前被画布截断。
        layer = layer.astype(np.float32)/255
        layer[:, :, :3] *= layer[:, :, 3:4]
        canvas[:, :, :3] = layer[:, :, :3] + canvas[:, :, :3]*(1-layer[:, :, 3:4])
        canvas[:, :, 3:4] = layer[:, :, 3:4] + canvas[:, :, 3:4]*(1-layer[:, :, 3:4])
    rgb = np.divide(canvas[:, :, :3], canvas[:, :, 3:4], out=np.zeros_like(canvas[:, :, :3]), where=canvas[:, :, 3:4]>0)
    rgba = np.round(np.clip(np.dstack((rgb,canvas[:, :, 3])),0,1)*255).astype(np.uint8)
    ok, png = cv2.imencode('.png', cv2.cvtColor(rgba,cv2.COLOR_RGBA2BGRA))
    if not ok:
        raise ValueError('无法生成 PNG 预览')
    return png.tobytes()

