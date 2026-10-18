"""六版通用图元算法回归检查。只读当前交付；所有写入实验均在系统临时目录。"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
DELIVERY = PROJECT / '交付物' / '手机图标合集.10' / '手机图标合集.10.超限.gia'
MANIFEST = HERE / '合集配置.json'
PYTHON = Path(os.environ['UI_PYTHON']) if os.environ.get('UI_PYTHON') else Path(sys.executable)
EXPECTED_GROUPS = {'电话': 35, '微信': 15, 'QQ': 47, '相机': 24, '相册': 32, '手电筒': 31, '笔记': 23}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'无法加载模块：{path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_bytes(root: Path):
    if not root.exists():
        return None
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob('*')) if p.is_file()}


def unit_maps(algorithm, group):
    return {
        algorithm.component_name(algorithm.content(unit)): unit
        for unit in group['unit_records'].values()
    }


def identity_lists(algorithm, groups):
    guids, indices = [], []
    for group in groups:
        root = group['root_record']
        guids.append(algorithm.get(algorithm.content(root), 501, 0))
        indices.append(algorithm.registration_index(algorithm.content(root)))
        for guid, unit in group['unit_records'].items():
            guids.append(guid)
            indices.append(algorithm.registration_index(algorithm.content(unit)))
    return guids, indices


class SixVersionRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PYTHON.is_file():
            raise RuntimeError(f'项目隔离 Python 不存在：{PYTHON}')
        cls.alg = load_module('ui6_regression_core', HERE / '生成图元.py')
        cls.pack = load_module('ui6_regression_bundle', HERE / '合包工具.py')
        cls.geometry = load_module('ui6_regression_geometry', HERE / '几何工具.py')
        cls.optimize = load_module('ui6_regression_optimize', HERE / '图元优化.py')
        cls.generate_module = load_module('ui6_regression_generator', HERE / '统一生成.py')
        cls.config = json.loads(MANIFEST.read_text(encoding='utf-8-sig'))
        cls.entries = cls.config['groups']
        cls.recipes = {
            entry['name']: json.loads((HERE / entry['recipe']).read_text(encoding='utf-8-sig'))
            for entry in cls.entries
        }
        cls.templates = {entry['name']: HERE / entry['template'] for entry in cls.entries}
        cls.current_raw = DELIVERY.read_bytes()
        cls.current_groups = cls.pack.split_bundle(cls.current_raw)

    def recipe(self, name='电话'):
        return copy.deepcopy(self.recipes[name])

    def split(self, raw):
        groups = self.pack.split_bundle(raw)
        self.assertEqual(len(groups), 1)
        return groups[0]

    def rebuild(self, recipe, reference, guid_base=1074330000, index_base=230000):
        return self.alg.rebuild(recipe, reference, guid_base=guid_base, index_base=index_base)

    def test_manifest_baseline_and_group_budget(self):
        self.assertEqual(digest(DELIVERY), self.config['baseline_sha256'])
        self.assertEqual(set(self.recipes), set(EXPECTED_GROUPS))
        self.assertEqual(sum(EXPECTED_GROUPS.values()), 207)
        for name, count in EXPECTED_GROUPS.items():
            recipe = self.recipes[name]
            self.assertEqual(recipe['algorithm_name'], '10.15-六版算法')
            self.assertEqual(len(self.alg.compile_recipe(recipe)), count, name)
            self.assertEqual(digest(self.templates[name]), recipe['reference_sha256'], name)

    def test_current_delivery_matches_all_seven_templates(self):
        self.assertEqual([g['name'] for g in self.current_groups],
                         [self.recipes[e['name']]['name'] for e in self.entries])
        self.assertEqual(sum(len(g['unit_records']) for g in self.current_groups), 207)
        self.assertEqual(sum(len(g['unit_records']) + 1 for g in self.current_groups), 214)
        guids, indices = identity_lists(self.alg, self.current_groups)
        self.assertEqual(len(guids), 214)
        self.assertEqual(len(set(guids)), 214)
        self.assertEqual(len(indices), 214)
        self.assertEqual(len(set(indices)), 214)

        for current, entry in zip(self.current_groups, self.entries):
            template = self.split(self.templates[entry['name']].read_bytes())
            self.assertEqual(current['root_record'], template['root_record'], entry['name'])
            self.assertEqual(current['unit_records'], template['unit_records'], entry['name'])
            self.assertEqual(current['scene'], template['scene'], entry['name'])

    def test_platforms_colors_image_profiles_and_masks_are_preserved(self):
        for group, entry in zip(self.current_groups, self.entries):
            name = entry['name']
            recipe = self.recipes[name]
            template = self.split(self.templates[name].read_bytes())
            self.assertEqual(self.alg.mask_payload(group['root_record']),
                             self.alg.mask_payload(template['root_record']), name)
            self.assertEqual(set(self.alg.platform_rows(group['root_record'])), {'0', '1', '2', '3'}, name)

            units = unit_maps(self.alg, group)
            self.assertEqual(set(units), {e['name'] for e in recipe['elements']}, name)
            expected_profiles = recipe.get('image_profiles', {})
            for element in recipe['elements']:
                unit = units[element['name']]
                self.assertEqual(set(self.alg.platform_rows(unit)), {'0', '1', '2', '3'},
                                 (name, element['name']))
                image_color = self.alg.get(self.alg.fields(self.alg.image_payload(unit)), 4, None)
                self.assertIsInstance(image_color, int, (name, element['name']))
                rgba = [(image_color >> 16) & 255, (image_color >> 8) & 255,
                        image_color & 255, (image_color >> 24) & 255]
                self.assertEqual(rgba, element['color'], (name, element['name']))
                profile_key = element.get('image_profile')
                if profile_key is not None:
                    expected = bytes.fromhex(expected_profiles[profile_key]['parameters_hex'])
                    self.assertEqual(self.alg.image_parameters(self.alg.image_payload(unit)), expected,
                                     (name, element['name']))

    def test_duplicate_platform_id_is_rejected_by_all_reference_readers(self):
        reference = self.templates['微信']
        recipe = self.recipe('微信')
        target_guid = recipe['elements'][0]['source_guid']
        raw = self.alg.convert_gia_bytes_to_overlimit(reference.read_bytes())
        top = self.alg.fields(raw[20:-4])
        target_item = next(item for item in top if item[0] == 2 and
                           self.alg.get(self.alg.content(item[2]), 501, 0) == target_guid)
        target_unit = target_item[2]

        content = self.alg.content(target_unit)
        transform_component = next(item for item in content if item[0] == 505 and
                                   self.alg.get(self.alg.fields(item[2]), 502, 0) == 12)
        component = self.alg.fields(transform_component[2])
        body = self.alg.fields(self.alg.get(component, 503))
        transform = self.alg.fields(self.alg.get(body, 13))
        layout = self.alg.fields(self.alg.get(transform, 12))
        platforms = [item for item in layout if item[0] == 501]
        self.assertEqual(len(platforms), 4)
        duplicate_zero = next(copy.deepcopy(item) for item in platforms
                              if self.alg.get(self.alg.fields(item[2]), 501, 0) == 0)
        layout.append(duplicate_zero)
        resulting_platforms = [item for item in layout if item[0] == 501]
        resulting_ids = [self.alg.get(self.alg.fields(item[2]), 501, 0) for item in resulting_platforms]
        self.assertEqual(len(resulting_platforms), 5)
        self.assertEqual(resulting_ids.count(0), 2)
        self.alg.put(transform, 12, self.alg.encode(layout))
        self.alg.put(body, 13, self.alg.encode(transform))
        self.alg.put(component, 503, self.alg.encode(body))
        transform_component[2], transform_component[3] = self.alg.encode(component), None
        bad_unit = self.alg.patch(target_unit, [19, 1], self.alg.encode(content))
        target_item[2], target_item[3] = bad_unit, None
        malformed = self.pack.container(self.alg.encode(top))

        with self.assertRaises(ValueError):
            self.alg.platform_rows(bad_unit)
        with self.assertRaises(ValueError):
            self.pack.split_bundle(malformed)

        with tempfile.TemporaryDirectory(prefix='ui6_bad_platform_') as tmp:
            bad_reference = Path(tmp) / 'duplicate-platform.gia'
            bad_reference.write_bytes(malformed)
            with self.assertRaises(ValueError):
                self.alg.extract(bad_reference)
            recipe['reference_sha256'] = digest(bad_reference)
            with self.assertRaises(ValueError):
                self.alg.rebuild(recipe, bad_reference)

    def test_same_source_rebuild_is_byte_exact_for_every_group(self):
        for name, reference in self.templates.items():
            raw, elements = self.rebuild(self.recipe(name), reference)
            self.assertEqual(raw, reference.read_bytes(), name)
            self.assertEqual(len(elements), EXPECTED_GROUPS[name], name)

    def test_element_adjustment_changes_only_the_target_unit(self):
        recipe = self.recipe('电话')
        target = recipe['elements'][8]
        original = self.split(self.templates['电话'].read_bytes())
        recipe['adjustments'] = {'elements': {target['id']: {'dx': 1.25}}}
        raw, _ = self.rebuild(recipe, self.templates['电话'])
        changed = self.split(raw)
        self.assertEqual(changed['root_record'], original['root_record'])
        before, after = unit_maps(self.alg, original), unit_maps(self.alg, changed)
        self.assertEqual(set(before), set(after))
        differences = {name for name in before if before[name] != after[name]}
        self.assertEqual(differences, {target['name']})

    def test_part_adjustment_changes_exactly_that_part(self):
        recipe = self.recipe('电话')
        part = '底板'
        expected = {e['name'] for e in recipe['elements'] if e['part'] == part}
        self.assertGreater(len(expected), 1)
        recipe['adjustments'] = {'parts': {part: {'dy': 0.75}}}
        original = self.split(self.templates['电话'].read_bytes())
        changed = self.split(self.rebuild(recipe, self.templates['电话'])[0])
        before, after = unit_maps(self.alg, original), unit_maps(self.alg, changed)
        self.assertEqual({n for n in before if before[n] != after[n]}, expected)

    def test_addition_allocates_new_global_identity_without_rewriting_old_units(self):
        recipe = self.recipe('电话')
        original_count = len(recipe['elements'])
        added = copy.deepcopy(recipe['elements'][0])
        added.update(id='regression-added', name='电话_回归_新增部件_矩形',
                     part='回归新增部件', role='矩形', x=added['x'] + 3)
        added.pop('guid', None)
        added.pop('index', None)
        recipe['elements'].append(added)
        guid_base, index_base = 1074330000, 230000
        raw, elements = self.alg.rebuild(recipe, self.templates['电话'], guid_base, index_base)
        rebuilt = self.split(raw)
        source = self.split(self.templates['电话'].read_bytes())
        self.assertEqual(len(elements), original_count + 1)
        self.assertEqual(len(rebuilt['unit_records']), original_count + 1)
        for guid, unit in source['unit_records'].items():
            self.assertEqual(rebuilt['unit_records'][guid], unit)
        new_guids = set(rebuilt['unit_records']) - set(source['unit_records'])
        self.assertEqual(new_guids, {guid_base + original_count + 1})
        new_unit = rebuilt['unit_records'][next(iter(new_guids))]
        self.assertEqual(self.alg.registration_index(self.alg.content(new_unit)), index_base + original_count + 1)

    def test_deletion_removes_only_the_selected_unit_and_reference(self):
        recipe = self.recipe('电话')
        removed = recipe['elements'].pop(7)
        original = self.split(self.templates['电话'].read_bytes())
        changed = self.split(self.rebuild(recipe, self.templates['电话'])[0])
        before, after = unit_maps(self.alg, original), unit_maps(self.alg, changed)
        self.assertNotIn(removed['name'], after)
        self.assertEqual(set(before) - set(after), {removed['name']})
        self.assertTrue(all(before[name] == after[name] for name in after))
        self.assertEqual(len(changed['scene']['records']), len(recipe['elements']))

    def test_reordering_updates_only_root_order(self):
        recipe = self.recipe('电话')
        recipe['elements'] = recipe['elements'][::2] + recipe['elements'][1::2]
        wanted = [e['name'] for e in recipe['elements']]
        original = self.split(self.templates['电话'].read_bytes())
        changed = self.split(self.rebuild(recipe, self.templates['电话'])[0])
        self.assertNotEqual(changed['root_record'], original['root_record'])
        self.assertEqual(changed['unit_records'], original['unit_records'])
        with tempfile.TemporaryDirectory(prefix='ui6_order_') as tmp:
            path = Path(tmp) / 'ordered.gia'
            path.write_bytes(self.rebuild(recipe, self.templates['电话'])[0])
            _, _, _, _, units, order, _ = self.alg.load_reference(path)
            actual = [self.alg.component_name(self.alg.content(units[guid])) for guid in order]
        self.assertEqual(actual, wanted)

    def test_invalid_recipe_values_and_profiles_are_rejected(self):
        bad = self.recipe()
        bad['elements'][1]['id'] = bad['elements'][0]['id']
        with self.assertRaises(ValueError):
            self.alg.compile_recipe(bad)

        bad = self.recipe()
        bad['elements'][0]['image_profile'] = 'missing-profile'
        with self.assertRaises(ValueError):
            self.alg.compile_recipe(bad)

        bad = self.recipe()
        profile = bad['image_profiles'][bad['elements'][0]['image_profile']]
        profile['parameters_hex'] = '00'
        with self.assertRaises(ValueError):
            self.alg.rebuild(bad, self.templates['电话'])

        bad = self.recipe()
        bad['elements'][0]['x'] = math.nan
        with self.assertRaises(ValueError):
            self.alg.compile_recipe(bad)

    def test_bundle_rejects_duplicate_guid_and_cross_group_index_conflict(self):
        phone = self.recipe('电话')
        wechat = self.recipe('微信')
        raw, _ = self.alg.build(phone, self.templates['电话'], guid_base=1074330000, index_base=230000)
        with self.assertRaises(ValueError):
            self.pack.bundle([raw, raw])

        other, _ = self.alg.build(wechat, self.templates['微信'], guid_base=1074340000, index_base=230000)
        with self.assertRaises(ValueError):
            self.pack.bundle([raw, other])

    def test_container_modes_round_trip_exactly(self):
        for name, path in self.templates.items():
            raw = path.read_bytes()
            self.assertEqual(self.alg.convert_gia_bytes_to_overlimit(
                self.alg.convert_gia_bytes_to_classic(raw)), raw, name)
        self.assertEqual(self.alg.convert_gia_bytes_to_overlimit(
            self.alg.convert_gia_bytes_to_classic(self.current_raw)), self.current_raw)

    def test_manifest_compilation_is_read_only_and_matches_v10(self):
        protected = [MANIFEST, DELIVERY]
        protected.extend((HERE / item['recipe']) for item in self.entries)
        protected.extend((HERE / item['template']) for item in self.entries)
        before = {p: digest(p) for p in protected}
        raw, details = self.generate_module.compile_manifest()
        self.assertEqual(raw, self.current_raw)
        self.assertEqual(digest(DELIVERY), self.config['baseline_sha256'])
        self.assertEqual(details['delivery_version'], 10)
        self.assertEqual(details['group_count'], 7)
        self.assertEqual(details['element_count'], 207)
        self.assertEqual(details['identity_count'], 214)
        self.assertEqual(details['platform_rows'], 856)
        self.assertEqual({p: digest(p) for p in protected}, before)

    def test_unified_loader_accepts_one_path_argument(self):
        loaded = self.generate_module.load(HERE / '生成图元.py')
        self.assertEqual(loaded.ALGORITHM_NAME, '10.15-六版算法')
        self.assertTrue(callable(loaded.rebuild))

    def test_generation_check_has_no_filesystem_side_effects(self):
        with tempfile.TemporaryDirectory(prefix='ui6_check_') as tmp:
            root = Path(tmp)
            target = root / '手机图标合集.10' / '手机图标合集.10.超限.gia'
            target.parent.mkdir(parents=True)
            target.write_bytes(self.current_raw)
            before = tree_bytes(root)
            report = self.generate_module.generate(output_root=root, check=True)
            self.assertTrue(report)
            self.assertEqual(tree_bytes(root), before)

        before = {p: digest(p) for p in (MANIFEST, DELIVERY)}
        process = subprocess.run([str(PYTHON), '-B', str(HERE / '统一生成.py'), '--check'],
                                 capture_output=True, timeout=180)
        self.assertEqual(process.returncode, 0, process.stderr.decode('utf-8', errors='replace'))
        self.assertEqual({p: digest(p) for p in (MANIFEST, DELIVERY)}, before)

    def test_same_version_write_is_idempotent_and_conflicts_are_untouched(self):
        with tempfile.TemporaryDirectory(prefix='ui6_generate_') as tmp:
            root = Path(tmp)
            report = self.generate_module.generate(output_root=root)
            target = root / '手机图标合集.10' / '手机图标合集.10.超限.gia'
            self.assertEqual(Path(report['output']), target)
            self.assertEqual(target.read_bytes(), self.current_raw)
            before = target.read_bytes()
            self.generate_module.generate(output_root=root)
            self.assertEqual(target.read_bytes(), before)

            target.write_bytes(b'occupied by a different GIA')
            conflicted = tree_bytes(root)
            with self.assertRaises(ValueError):
                self.generate_module.generate(output_root=root)
            self.assertEqual(tree_bytes(root), conflicted)

    def copied_workspace(self, root: Path):
        """只复制六版与所需 GIA 依赖；隔离区内不包含任何旧算法目录。"""
        isolated_project = root / '项目' / 'ui'
        isolated_algorithm = isolated_project / '算法' / '10.15-六版算法'
        isolated_algorithm.mkdir(parents=True)
        for source in HERE.iterdir():
            if source.is_file() and source.suffix in {'.py', '.json'}:
                shutil.copy2(source, isolated_algorithm / source.name)
            elif source.is_dir() and source.name in {'配方', '模板'}:
                shutil.copytree(source, isolated_algorithm / source.name)
        return isolated_algorithm, root

    def toolbox_env(self):
        source_tool = (Path(os.environ['UI_TOOLBOX_ROOT']) if os.environ.get('UI_TOOLBOX_ROOT')
                       else PROJECT.parents[1] / '工具与依赖' / 'Miliastra-toolbox-primitive-shape')
        return dict(os.environ, UI_TOOLBOX_ROOT=str(source_tool))

    def test_algorithm_copy_runs_without_legacy_algorithm_directories(self):
        with tempfile.TemporaryDirectory(prefix='ui6_isolated_') as tmp:
            algorithm_dir, root = self.copied_workspace(Path(tmp))
            self.assertFalse((root / '项目' / 'ui' / '算法' / '10.15-五版算法').exists())
            output_root = root / '项目' / 'ui' / '交付物'
            baseline = output_root / '手机图标合集.10' / '手机图标合集.10.超限.gia'
            baseline.parent.mkdir(parents=True)
            baseline.write_bytes(self.current_raw)
            before = tree_bytes(output_root)
            process = subprocess.run([str(PYTHON), '-B', str(algorithm_dir / '统一生成.py'), '--check'],
                                     cwd=root, env=self.toolbox_env(), capture_output=True, timeout=180)
            self.assertEqual(process.returncode, 0, process.stderr.decode('utf-8', errors='replace'))
            self.assertEqual(tree_bytes(output_root), before)

    def test_failed_generation_does_not_leave_partial_delivery(self):
        with tempfile.TemporaryDirectory(prefix='ui6_failed_') as tmp:
            root = Path(tmp)
            algorithm_dir, _ = self.copied_workspace(root)
            manifest_path = algorithm_dir / '合集配置.json'
            config = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
            recipe_path = algorithm_dir / config['groups'][0]['recipe']
            recipe = json.loads(recipe_path.read_text(encoding='utf-8-sig'))
            recipe['elements'][0]['x'] = math.nan
            recipe_path.write_text(json.dumps(recipe, ensure_ascii=False), encoding='utf-8')
            output_root = root / '试生成'
            env_before = os.environ.get('UI_TOOLBOX_ROOT')
            os.environ['UI_TOOLBOX_ROOT'] = self.toolbox_env()['UI_TOOLBOX_ROOT']
            try:
                module = load_module('ui6_isolated_generator', algorithm_dir / '统一生成.py')
                with self.assertRaises(ValueError):
                    module.generate(manifest_path=manifest_path, output_root=output_root, version=11)
            finally:
                if env_before is None:
                    os.environ.pop('UI_TOOLBOX_ROOT', None)
                else:
                    os.environ['UI_TOOLBOX_ROOT'] = env_before
            self.assertFalse(output_root.exists())

    def test_mutating_version_ten_requires_version_increment(self):
        with tempfile.TemporaryDirectory(prefix='ui6_version_') as tmp:
            root = Path(tmp)
            algorithm_dir, _ = self.copied_workspace(root)
            manifest_path = algorithm_dir / '合集配置.json'
            config = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
            recipe_path = algorithm_dir / config['groups'][0]['recipe']
            recipe = json.loads(recipe_path.read_text(encoding='utf-8-sig'))
            recipe['elements'][0]['x'] += 0.25
            recipe_path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding='utf-8')
            env_before = os.environ.get('UI_TOOLBOX_ROOT')
            os.environ['UI_TOOLBOX_ROOT'] = self.toolbox_env()['UI_TOOLBOX_ROOT']
            try:
                module = load_module('ui6_mutated_generator', algorithm_dir / '统一生成.py')
            finally:
                if env_before is None:
                    os.environ.pop('UI_TOOLBOX_ROOT', None)
                else:
                    os.environ['UI_TOOLBOX_ROOT'] = env_before

            version_ten_root = root / 'v10'
            with self.assertRaises(ValueError):
                module.generate(manifest_path=manifest_path, output_root=version_ten_root)
            self.assertFalse(version_ten_root.exists())

            report = module.generate(manifest_path=manifest_path, output_root=root / 'v11', version=11)
            expected = root / 'v11' / '手机图标合集.11' / '手机图标合集.11.超限.gia'
            self.assertEqual(Path(report['output']), expected)
            self.assertTrue(expected.is_file())

    @staticmethod
    def polygon_area(points):
        return abs(math.fsum(points[i][0] * points[(i + 1) % len(points)][1]
                             - points[(i + 1) % len(points)][0] * points[i][1]
                             for i in range(len(points))) / 2)

    @staticmethod
    def component_contains(element, x, y):
        dx, dy = x - element['x'], y - element['y']
        if element['shape'] == 'ellipse':
            return ((2 * dx / element['width']) ** 2
                    + (2 * dy / element['height']) ** 2 <= 1)
        return abs(dx) <= element['width'] / 2 and abs(dy) <= element['height'] / 2

    def test_rounded_box_area_matches_analytic_rounded_rectangle(self):
        geo = self.geometry
        drawing = geo.Drawing('rounding')
        width, height, radius, cx, cy = 20.0, 12.0, 3.0, 10.0, 15.0
        elements = drawing.rounded_box('主体', '圆角框', cx, cy, width, height, radius, '#336699')
        self.assertGreaterEqual(len(elements), 5)
        self.assertTrue(all(e['color'] == [51, 102, 153, 255] for e in elements))

        step = 0.05
        mismatches = 0
        covered = 0
        for ix in range(round(width / step)):
            x = cx - width / 2 + (ix + 0.5) * step
            for iy in range(round(height / step)):
                y = cy - height / 2 + (iy + 0.5) * step
                expected = geo.inside_rounded_rect(x, y, cx, cy, width, height, radius)
                actual = any(self.component_contains(element, x, y) for element in elements)
                mismatches += expected != actual
                covered += expected
        self.assertEqual(mismatches, 0)
        measured_area = covered * step * step
        expected_area = width * height - (4 - math.pi) * radius * radius
        self.assertLess(abs(measured_area - expected_area), 0.5)
        self.assertTrue(geo.inside_rounded_rect(cx + width / 2 - radius + radius / math.sqrt(2),
                                                cy + height / 2 - radius + radius / math.sqrt(2),
                                                cx, cy, width, height, radius))
        self.assertFalse(geo.inside_rounded_rect(cx + width / 2, cy + height / 2,
                                                 cx, cy, width, height, radius))

    def test_polygon_decomposition_preserves_area_and_ellipse_boundary(self):
        geo = self.geometry
        drawing = geo.Drawing('area')
        points = [(0, 0), (4, 0), (4, 3), (0, 3)]
        triangles = drawing.polygon('部件', '矩形轮廓', points, (240, 220, 200))
        self.assertTrue(triangles)
        self.assertTrue(all(element['shape'] == 'triangle' for element in triangles))
        decomposed_area = math.fsum(self.polygon_area(geo.element_boundary(e)) for e in triangles)
        self.assertAlmostEqual(decomposed_area, 12.0, places=8)

        # 该凸四边形的最优剖分只需两个图元；扇形拆分会产生八个。
        optimized = geo.Drawing('optimal')
        quad = [(2, 3), (4, 0), (2, -2), (0, 0)]
        quad_elements = optimized.polygon('部件', '低图元轮廓', quad, '#abcdef')
        self.assertEqual(len(quad_elements), 2)
        self.assertTrue(all(element['shape'] == 'triangle' for element in quad_elements))
        quad_area = math.fsum(self.polygon_area(geo.element_boundary(e)) for e in quad_elements)
        self.assertAlmostEqual(quad_area, 10.0, places=8)
        ids = [element['id'] for element in quad_elements]
        self.assertEqual(ids, ['optimal:0001', 'optimal:0002'])
        self.assertEqual(len(set(ids)), 2)

        ellipse = drawing.add('部件', '椭圆', 'ellipse', 7, -2, 8, 6, '#ffffff', rotation=17)
        sampled_area = self.polygon_area(geo.element_boundary(ellipse))
        self.assertAlmostEqual(sampled_area, math.pi * 4 * 3, delta=0.002)

    def test_rounding_patch_is_finite_non_degenerate_and_symmetric(self):
        triangles = self.geometry.rounding_patch((0, 0), (1, 0), (0, 1), 10)
        self.assertEqual(len(triangles), 3)
        self.assertTrue(all(len(triangle) == 3 for triangle in triangles))
        areas = [self.polygon_area(triangle) for triangle in triangles]
        self.assertTrue(all(math.isfinite(area) and area > 0 for area in areas))
        q, origin, p = triangles[0]
        _, q_again, s = triangles[1]
        s_again, origin_again, t = triangles[2]
        self.assertEqual(origin, origin_again)
        self.assertEqual(q, q_again)
        self.assertEqual(s, s_again)
        self.assertAlmostEqual(math.dist(origin, p), 10.0, places=9)
        self.assertAlmostEqual(math.dist(origin, t), 10.0, places=9)
        self.assertAlmostEqual(q[0], s[1], places=9)
        self.assertAlmostEqual(q[1], s[0], places=9)
        for triangle in triangles:
            self.assertTrue(all(math.isfinite(v) for point in triangle for v in point))
        with self.assertRaises(ValueError):
            self.geometry.rounding_patch((0, 0), (1, 0), (1, 0), 10)

    def test_convex_clipping_area_and_empty_intersection(self):
        subject = [(0, 0), (4, 0), (4, 4), (0, 4)]
        clip = [(2, -1), (5, -1), (5, 3), (2, 3)]
        forward = self.geometry.clip_convex(subject, clip)
        reversed_boundary = self.geometry.clip_convex(subject, list(reversed(clip)))
        self.assertAlmostEqual(self.polygon_area(forward), 6.0, places=9)
        self.assertAlmostEqual(self.polygon_area(reversed_boundary), 6.0, places=9)
        self.assertAlmostEqual(self.polygon_area(forward), self.polygon_area(reversed_boundary), places=9)
        self.assertEqual(self.geometry.clip_convex(subject, [(6, 0), (8, 0), (8, 2), (6, 2)]), [])
        with self.assertRaises(ValueError):
            self.geometry.clip_convex(subject, [(0, 0), (3, 0), (1, 1), (3, 3), (0, 3)])

    def test_geometry_rejects_non_finite_and_invalid_dimensions(self):
        drawing = self.geometry.Drawing('invalid')
        with self.assertRaises((TypeError, ValueError)):
            drawing.add('部件', 'NaN', 'rect', math.nan, 0, 1, 1, '#000000')
        with self.assertRaises(ValueError):
            drawing.rounded_box('部件', '过大圆角', 0, 0, 10, 8, 5, '#000000')
        with self.assertRaises(ValueError):
            drawing.polygon('部件', '凹多边形', [(0, 0), (4, 0), (2, 1), (4, 4), (0, 4)], '#000000')

    def test_concave_contour_preserves_notch_area_and_sampled_coverage(self):
        import cv2
        import numpy as np
        points = [(0, 0), (8, 0), (8, 2), (3, 2), (3, 6), (8, 6), (8, 8), (0, 8)]
        operations = self.optimize.contour_ops(points)
        self.assertAlmostEqual(sum(w * h / 2 for _, _, w, h, _ in operations), 44)
        self.assertEqual(operations, self.optimize.contour_ops(list(reversed(points))))
        self.assertEqual(operations, self.optimize.contour_ops(points[3:] + points[:3] + [points[3]]))
        boundaries = [np.asarray(self.geometry.element_boundary(dict(
            shape='triangle', x=x, y=y, width=w, height=h, rotation=a)), np.float32)
            for x, y, w, h, a in operations]
        polygon = np.asarray(points, np.float32)
        for x in range(32):
            for y in range(32):
                p = ((x + .371) / 4, (y + .219) / 4)
                expected = cv2.pointPolygonTest(polygon, p, False) > 0
                actual = any(cv2.pointPolygonTest(b, p, False) >= 0 for b in boundaries)
                self.assertEqual(actual, expected, p)

    def test_contour_cost_matches_exhaustive_convex_triangulations(self):
        points = [(0, 0), (4, 0), (7, 2), (6, 6), (2, 8), (-1, 4)]
        def enumerate_costs(vertices):
            if len(vertices) < 3:
                return [0]
            results = []
            for k in range(1, len(vertices) - 1):
                count = len(self.optimize.triangle_ops(vertices[0], vertices[k], vertices[-1]))
                results.extend(a + b + count for a in enumerate_costs(vertices[:k + 1])
                               for b in enumerate_costs(vertices[k:]))
            return results
        self.assertEqual(len(self.optimize.contour_ops(points)), min(enumerate_costs(points)))
        acute = [(0, 0), (6, 0), (2, 4)]
        self.assertEqual(len(self.optimize.triangle_ops(*acute)), 3)
        self.assertEqual(len(self.geometry._triangle_ops(*acute)), 4)
        for triangle in [[(0, 0), (2, 0), (1, 3)], [(0, 0), (3, 0), (0, 4)],
                         [(0, 0), (8, 0), (1, .2)]]:
            ops = self.optimize.triangle_ops(*triangle)
            self.assertLessEqual(len(ops), len(self.geometry._triangle_ops(*triangle)))
            self.assertAlmostEqual(sum(w * h / 2 for _, _, w, h, _ in ops), self.polygon_area(triangle))

    def test_contour_rejects_invalid_rings_and_normalizes_coordinates(self):
        invalid = [[], [(0, 0), (1, 0)], [(0, 0), (1, 0), (2, 0)],
                   [(0, 0), (2, 2), (0, 2), (2, 0)],
                   [(0, 0), (3, 0), (1, 0), (2, 2), (0, 2)],
                   [(0, 0), (2, 0), (2, 2), (1, 0), (0, 2)],
                   [(0, 0), (2, 0), (2, 2), (0, 0), (0, 2)],
                   [(0, 0), (math.nan, 0), (0, 1)],
                   [(0, 0), (math.inf, 0), (0, 1)],
                   [(0, 0), (True, 0), (0, 1)], [(0, 0)] * 129]
        for points in invalid:
            with self.subTest(points=points), self.assertRaises((ValueError, TypeError)):
                self.optimize.contour_ops(points)
        for scale in (1e-100, 1e100):
            ops = self.optimize.contour_ops([(0, 0), (6 * scale, 0), (2 * scale, 4 * scale)])
            self.assertEqual(len(ops), 3)
            self.assertTrue(math.isclose(sum(w * h / 2 for _, _, w, h, _ in ops),
                                         12 * scale * scale, rel_tol=1e-9))
        with self.assertRaises(ValueError):
            self.optimize.triangle_ops((0, 0), (1, 0), (0, 0))

    def test_concave_cost_matches_independent_exhaustive_candidates(self):
        import cv2
        import numpy as np
        points = [(0, 0), (5, 0), (5, 5), (2, 2), (0, 5)]
        polygon = np.asarray(points, np.float32)
        def enumerate_triangles(vertices):
            if len(vertices) < 3:
                return [()]
            results = []
            for k in range(1, len(vertices) - 1):
                triangle = (vertices[0], vertices[k], vertices[-1])
                results.extend((triangle,) + a + b for a in enumerate_triangles(vertices[:k + 1])
                               for b in enumerate_triangles(vertices[k:]))
            return results
        costs = []
        rejected = 0
        for triangles in enumerate_triangles(points):
            valid = True
            for triangle in triangles:
                a, b, c = triangle
                if (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0]) <= 0:
                    valid = False
                    break
                # 独立用OpenCV核中心与每条边的采样，不调用DP内部对角线判断。
                samples = [tuple(sum(p[d] for p in triangle) / 3 for d in (0, 1))]
                for p, q in zip(triangle, triangle[1:] + triangle[:1]):
                    samples.extend(tuple(p[d] + (q[d] - p[d]) * t / 20 for d in (0, 1))
                                   for t in range(21))
                if any(cv2.pointPolygonTest(polygon, p, True) < -1e-6 for p in samples):
                    valid = False
                    break
            if valid:
                self.assertAlmostEqual(sum(self.polygon_area(t) for t in triangles), self.polygon_area(points))
                costs.append(sum(len(self.optimize.triangle_ops(*t)) for t in triangles))
            else:
                rejected += 1
        self.assertTrue(costs)
        self.assertGreater(rejected, 0)
        self.assertEqual(len(self.optimize.contour_ops(points)), min(costs))

    def test_uniform_overlap_contains_original_skinny_rotated_triangles(self):
        import cv2
        import numpy as np
        operations = [(8, 9, 200, .02, 37), (8, 9, .03, 180, -63)]
        before = copy.deepcopy(operations)
        expanded = self.optimize.expand_ops(operations)
        self.assertEqual(before, operations)
        for old, new in zip(operations, expanded):
            def boundary(row):
                x, y, w, h, a = row
                return self.geometry.element_boundary(dict(shape='triangle', x=x, y=y,
                                                            width=w, height=h, rotation=a))
            polygon = np.asarray(boundary(new), np.float32)
            self.assertAlmostEqual(new[2] / old[2], new[3] / old[3])
            for p in boundary(old):
                self.assertGreaterEqual(cv2.pointPolygonTest(polygon, p, True), -1e-4)
            self.assertGreater(new[2] * new[3], old[2] * old[3])
        self.assertEqual(self.optimize.expand_ops(operations, 1), operations)
        for factor in (0, .99, math.nan, math.inf, True):
            with self.assertRaises((ValueError, TypeError)):
                self.optimize.expand_ops(operations, factor)

    @staticmethod
    def optimization_scene(layers):
        # 每项为资源、中心x/y、宽/高、旋转、RGBA；使用实际回读行的坐标约定。
        return {'root_transform': [0, 0, 20, 20, .5, .5, .5, .5, .5, .5, 1, 1, 0], 'records': [
            [asset, x, y, w, h, .5, .5, .5, .5, .5, .5, 1, 1, angle, *rgba]
            for asset, x, y, w, h, angle, rgba in layers]}

    def test_cleanup_candidates_are_pixel_exact_and_do_not_mutate_scene(self):
        red, blue = (200, 20, 30, 255), (10, 30, 200, 255)
        scene = self.optimization_scene([
            (100003, 0, 0, 2, 3, 25, blue),
            (100001, 0, 0, 18, 18, 0, red),
            (100002, 0, 0, 4, 5, 17, red)])
        before = copy.deepcopy(scene)
        report = self.optimize.cleanup_candidates(scene, render=self.alg.render)
        self.assertEqual(scene, before)
        self.assertTrue(report['pixel_equal'])
        self.assertEqual(report['candidates'], [dict(index=0, reason='fully_occluded'),
                                               dict(index=2, reason='same_opaque_color')])
        self.assertEqual(report['keep_indices'], [1])
        self.assertEqual(report['before_pixels_sha256'], report['after_pixels_sha256'])

    def test_cleanup_retains_transparency_color_changes_and_partial_coverage(self):
        blue, red = (10, 30, 200, 255), (200, 20, 30, 255)
        for top in [(100001, 0, 0, 18, 18, 0, (*red[:3], 128)),
                    (100001, 6, 0, 6, 18, 0, red)]:
            scene = self.optimization_scene([(100001, 0, 0, 10, 10, 0, blue), top])
            report = self.optimize.cleanup_candidates(scene, render=self.alg.render)
            self.assertEqual(report['keep_indices'], [0, 1])
            self.assertFalse(report['candidates'])
        scene = self.optimization_scene([(100001, 0, 0, 18, 18, 0, red),
                                          (100001, 0, 0, 3, 3, 0, blue)])
        self.assertEqual(self.optimize.cleanup_candidates(scene, render=self.alg.render)['keep_indices'], [0, 1])
        # 不得将相互依赖的同色片一起删除，底层必须留下。
        scene['records'][1][14:18] = red
        scene['records'].append(copy.deepcopy(scene['records'][1]))
        report = self.optimize.cleanup_candidates(scene, render=self.alg.render)
        self.assertEqual(report['keep_indices'], [0])

    def test_cleanup_rejects_unknown_inputs_and_rolls_back_render_mismatch(self):
        import cv2
        import numpy as np
        scene = self.optimization_scene([(100001, 0, 0, 18, 18, 0, (10, 20, 30, 255)),
                                          (100001, 0, 0, 3, 3, 0, (10, 20, 30, 255))])
        def different_renderer(source):
            image = np.full((2, 2, 4), len(source['records']), np.uint8)
            return cv2.imencode('.png', image)[1].tobytes()
        report = self.optimize.cleanup_candidates(scene, render=different_renderer)
        self.assertFalse(report['pixel_equal'])
        self.assertEqual(report['keep_indices'], [0, 1])
        self.assertEqual(report['candidates'], [])
        self.assertTrue(report['rejected_candidates'])
        invalid = [dict(scene, native_mask=True), dict(scene, ignored_mask=True)]
        invalid.extend([dict(scene, missing_refs=[123]),
                        dict(scene, root_transform=scene['root_transform'] + [15, 0])])
        for tail in ([15, 0], [0, 0], [15]):
            bad = copy.deepcopy(scene)
            bad['records'][0].extend(tail)
            invalid.append(bad)
        bad = copy.deepcopy(scene)
        bad['records'][0].pop()
        invalid.append(bad)
        for index, value in [(0, 888888), (3, -1), (13, math.nan), (14, 1.5), (5, 1e100), (7, 0)]:
            bad = copy.deepcopy(scene)
            bad['records'][0][index] = value
            invalid.append(bad)
        for bad in invalid:
            with self.assertRaises((ValueError, TypeError)):
                self.optimize.cleanup_candidates(bad, render=self.alg.render)
        for kwargs in ({'margin': 0}, {'margin': True}, {'margin': 65}, {'max_pixels': 10}):
            with self.assertRaises(ValueError):
                self.optimize.cleanup_candidates(scene, render=self.alg.render, **kwargs)

    def test_cleanup_retains_canvas_crossing_geometry(self):
        # 本地预览裁掉的部分可能在无原生遮罩的编辑器中仍可见，不能据此删除。
        scene = self.optimization_scene([(100001, 0, 0, 40, 40, 0, (10, 20, 30, 255)),
                                          (100001, 9, 0, 10, 5, 0, (10, 20, 30, 255))])
        report = self.optimize.cleanup_candidates(scene, render=self.alg.render)
        self.assertEqual(report['keep_indices'], [0, 1])
        self.assertFalse(report['candidates'])


def run():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SixVersionRegression)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({
        'algorithm_name': '10.15-六版算法',
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'skipped': len(result.skipped),
        'scope': '当前GIA与七模板保真、207图元/214全局身份、原生参数与遮罩、配方编辑/增删重排、校验拒绝、合包身份/模式、统一生成版本与只读保护、隔离副本、凹轮廓分解成本/面积/负形、微重叠包含、清理像素一致与回撤',
        'limitations': '本地GIA结构与几何计算检查；未启动编辑器、服务或试玩',
    }, ensure_ascii=False, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run())
