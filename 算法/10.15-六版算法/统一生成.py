"""统一入口：按配方生成、保真合包、只读检查及单组配方提取。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
DEFAULT_MANIFEST = HERE / '合集配置.json'


def load(path):
    path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location('ui6_' + hashlib.sha256(str(path).encode()).hexdigest()[:16], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load(HERE / '生成图元.py')
pack = load(HERE / '合包工具.py')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def local_path(parent, value):
    if not isinstance(value, str) or not value.strip() or Path(value).is_absolute():
        raise ValueError('配方及模板路径必须为配置目录内的相对路径')
    path = (parent / value).resolve()
    if not path.is_relative_to(parent.resolve()):
        raise ValueError('配方及模板路径越出配置目录')
    return path


def compile_manifest(manifest_path=DEFAULT_MANIFEST):
    manifest_path = Path(manifest_path).resolve()
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        raise ValueError('不支持的合集配置格式')
    core.identity(manifest.get('delivery_version'), '交付版本')
    definitions = manifest.get('groups')
    if not isinstance(definitions, list) or not definitions:
        raise ValueError('合集必须至少包含一组')
    input_paths = [manifest_path, HERE / '生成图元.py', HERE / '合包工具.py', Path(__file__)]
    selected, names = [], set()
    for entry in definitions:
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str) or not entry['name'].strip():
            raise ValueError('图标组定义或名称无效')
        if entry['name'] in names:
            raise ValueError('配置中的图标键重复')
        names.add(entry['name'])
        recipe_path = local_path(manifest_path.parent, entry.get('recipe'))
        template_path = local_path(manifest_path.parent, entry.get('template'))
        if sha(template_path.read_bytes()) != entry.get('template_sha256'):
            raise ValueError('模板哈希与合集配置不符：' + entry['name'])
        selected.append((entry, recipe_path, template_path))
        input_paths.extend((recipe_path, template_path))
    before = {str(path): sha(path.read_bytes()) for path in input_paths}
    singles, groups = [], []
    for entry, recipe_path, template_path in selected:
        raw, elements = core.rebuild(read_json(recipe_path), template_path,
            core.identity(entry.get('guid_base'), '新增GUID起点'),
            core.identity(entry.get('index_base'), '新增索引起点'))
        parsed = pack.split_bundle(raw)
        if len(parsed) != 1:
            raise ValueError('模板必须为单组GIA')
        singles.append(raw)
        groups.append(dict(icon=entry['name'], internal_name=parsed[0]['name'],
            elements=len(elements), group_sha256=sha(raw), template_sha256=entry['template_sha256']))
    raw, parsed = pack.bundle(singles)
    if raw != pack.bundle(singles)[0]:
        raise ValueError('重复合包不一致')
    if core.convert_gia_bytes_to_overlimit(core.convert_gia_bytes_to_classic(raw)) != raw:
        raise ValueError('经典/超限模式往返不一致')
    if before != {str(path): sha(path.read_bytes()) for path in input_paths}:
        raise ValueError('生成期间输入文件变化')
    ids, indices, platforms = set(), set(), 0
    for group in parsed:
        for record in [group['root_record'], *group['unit_records'].values()]:
            content = core.content(record)
            ids.add(core.get(content, 501))
            indices.add(core.registration_index(content))
            platforms += len(core.platform_rows(record))
    elements = sum(group['elements'] for group in groups)
    if len(ids) != elements + len(groups) or len(indices) != len(ids):
        raise ValueError('全局身份计数与图元数不符')
    return raw, dict(algorithm_name='10.15-六版算法', manifest=str(manifest_path),
        delivery_version=manifest['delivery_version'], group_count=len(groups), element_count=elements,
        identity_count=len(ids), platform_rows=platforms, gia_sha256=sha(raw),
        groups=groups, inputs=before, checks=['配方、模板哈希与预算', '四平台几何、名称及层序',
        'GUID和控件注册索引全局唯一', 'owner、父子、locator与孤立引用',
        '原生图片参数、遮罩与未编辑控件保持', '外层元数据一致及保真合包',
        '重复生成、模式往返与输入哈希保持'], failed=0,
        editor_status='仅本地结构和几何检查，编辑器实际导入、原生采样及试玩待确认')


def generate(manifest_path=DEFAULT_MANIFEST, version=None, check=False, output_root=None):
    manifest_path = Path(manifest_path).resolve()
    manifest = read_json(manifest_path)
    raw, report = compile_manifest(manifest_path)
    current = report['delivery_version']
    version = current if version is None else core.identity(version, '交付版本')
    if version < current:
        raise ValueError('交付版本不能低于配置基线')
    if version == current and manifest.get('baseline_sha256') and sha(raw) != manifest['baseline_sha256']:
        raise ValueError('配方已改变，请递增版本；不能改变基线同版资产')
    root = PROJECT / '交付物' if output_root is None else Path(output_root).resolve()
    target = root / f'手机图标合集.{version}' / f'手机图标合集.{version}.超限.gia'
    if str(target.resolve()) in report['inputs']:
        raise ValueError('输出不得覆盖配方、模板或源码输入')
    if target.exists() and (not target.is_file() or target.read_bytes() != raw):
        raise ValueError('同版已有资产不同，请递增版本：' + str(target))
    if check:
        if target.read_bytes() != raw:
            raise ValueError('已保存GIA与当前配方重建不符')
    else:
        # 所有配方、模板、全局身份、基线及目标均已验证后才创建输出。
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(raw)
    report.update(delivery_version=version, output=str(target), check_only=bool(check))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--version', type=int)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--extract', type=Path, help='从单组GIA提取可编辑配方')
    parser.add_argument('--recipe', type=Path, help='提取配方保存位置，已有文件拒绝覆盖')
    args = parser.parse_args()
    try:
        if args.extract:
            if args.recipe is None or args.check or args.version is not None or args.output_root is not None:
                raise ValueError('提取必须提供--recipe，不能混用生成/检查参数')
            recipe = core.extract(args.extract)
            data = (json.dumps(recipe, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            if args.recipe.exists():
                raise ValueError('配方目标已存在，拒绝覆盖')
            args.recipe.parent.mkdir(parents=True, exist_ok=True)
            args.recipe.write_bytes(data)
            print(json.dumps(dict(recipe=str(args.recipe), element_count=len(recipe['elements'])), ensure_ascii=False))
        else:
            if args.recipe is not None:
                raise ValueError('--recipe仅用于--extract')
            report = generate(args.manifest, args.version, args.check, args.output_root)
            print(json.dumps(report, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, '生成失败：' + str(error) + '\n')


if __name__ == '__main__':
    main()
