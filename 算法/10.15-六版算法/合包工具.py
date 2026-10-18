"""通用GIA容器、保真拆组与合包；不依赖旧算法。"""
import importlib.util
from pathlib import Path
import struct
import sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('ui6_core_for_pack', Path(__file__).with_name('生成图元.py'))
alg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alg)

def container(body):
    return struct.pack('>5I',len(body)+20,1,0x326,3,len(body))+body+b'\0\0\x06\x79'


def split_bundle(raw):
    if len(raw)<24:
        raise ValueError('GIA 容器过短')
    length,schema,magic,kind,size=struct.unpack('>5I',raw[:20])
    if (length!=len(raw)-4 or size!=len(raw)-24 or (schema,magic,kind)!=(1,0x326,3)
            or raw[-4:]!=b'\0\0\x06\x79'):
        raise ValueError('GIA 容器无效')
    raw=alg.convert_gia_bytes_to_overlimit(raw)
    top=alg.fields(raw[20:-4])
    roots=[item for item in top if item[0]==1]
    units={}
    for item in top:
        if item[0]!=2:continue
        guid=alg.get(alg.content(item[2]),501,0)
        if not guid or guid in units:raise ValueError('子图元 GUID 重复或为空')
        units[guid]=item
    root_ids=[alg.get(alg.content(item[2]),501,0)for item in roots]
    if not roots or not all(root_ids) or len(set(root_ids))!=len(roots) or set(root_ids)&set(units):
        raise ValueError('素材组 GUID 无效或冲突')
    shared=[item for item in top if item[0]not in(1,2)]
    groups=[]; consumed=set();used_indices=set()
    for root in roots:
        data=root[2]; rc=alg.content(data); root_guid=alg.get(rc,501,0)
        alg.platform_rows(data)
        if alg.get(alg.fields(alg.get(alg.fields(data),1)),4,0)!=root_guid:
            raise ValueError('根 locator 身份不一致')
        alg.check_guid_scope(root_guid,alg.get(alg.fields(alg.get(alg.fields(data),1)),3,0))
        root_index=alg.registration_index(rc)
        if root_index in used_indices:raise ValueError('素材组注册索引重复')
        used_indices.add(root_index)
        for t,w,v,r in rc:
            if t not in(502,505):continue
            comp=alg.fields(v);body=alg.fields(alg.get(comp,503))
            owner=alg.get(body,504,None)
            if owner is not None and alg.get(alg.fields(owner),4,0)!=root_guid:
                raise ValueError('根组件 owner 不一致')
            if t==502 and alg.get(comp,502,0)==5 and alg.get(alg.fields(alg.get(comp,11)),501,0)!=root_guid:
                raise ValueError('根内部身份不一致')
        children=alg.reader._children(alg.reader._fields(alg.encode(rc)))
        if len(children)!=len(set(children)) or not set(children)<=set(units):
            raise ValueError('素材组含重复或悬空子引用')
        if set(children)&consumed:raise ValueError('不同素材组引用了同一个图元')
        locators=[alg.get(alg.fields(v),4,0)for t,w,v,r in alg.fields(data)if t==2]
        if locators!=children:raise ValueError('根 children 与 locator 不一致')
        if alg.get(alg.fields(data),3).decode('utf-8')!=alg.component_name(rc):
            raise ValueError('根名称双写不一致')
        for child in children:
            unit=units[child]; uc=alg.content(unit[2])
            alg.platform_rows(unit[2])
            if alg.get(uc,504,0)!=root_guid:raise ValueError('子图元归属不一致')
            if alg.get(alg.fields(unit[2]),3).decode('utf-8')!=alg.component_name(uc):
                raise ValueError('子图元名称双写不一致')
            if alg.get(alg.fields(alg.get(alg.fields(unit[2]),1)),4,0)!=child:
                raise ValueError('子图元 locator 身份不一致')
            alg.check_guid_scope(child,alg.get(alg.fields(alg.get(alg.fields(unit[2]),1)),3,0))
            child_index=alg.registration_index(uc)
            if child_index in used_indices:raise ValueError('控件注册索引重复')
            used_indices.add(child_index)
            for t,w,v,r in uc:
                if t not in(502,505):continue
                comp=alg.fields(v); body=alg.fields(alg.get(comp,503))
                owner=alg.get(body,504,None)
                if owner is not None and alg.get(alg.fields(owner),4,0)!=child:
                    raise ValueError('子图元组件 owner 不一致')
                if t==502 and alg.get(comp,502,0)==5 and alg.get(alg.fields(alg.get(comp,11)),501,0)!=child:
                    raise ValueError('子图元内部身份不一致')
        selected=[item for item in top if item[0]==2 and alg.get(alg.content(item[2]),501,0)in children]
        single=container(alg.encode([root]+selected+shared))
        scene=alg.parse_scene(single)
        if scene['missing_refs']:raise ValueError('单组回读存在悬空引用')
        groups.append(dict(root_guid=root_guid,name=alg.component_name(rc),raw=single,
                           root_record=data,unit_records={i:units[i][2]for i in children},scene=scene))
        consumed.update(children)
    if consumed!=set(units):raise ValueError('合集包含孤立图元')
    return groups


def bundle(inputs):
    if not inputs:raise ValueError('至少需要一份 GIA')
    shared=None; root_items=[]; unit_items=[]; seen=set(); sources=[];seen_indices=set()
    for raw in inputs:
        groups=split_bundle(raw)
        if len(groups)!=1:raise ValueError('合包输入必须是单组 GIA')
        raw=alg.convert_gia_bytes_to_overlimit(raw)
        top=alg.fields(raw[20:-4])
        current=alg.encode([i for i in top if i[0]not in(1,2)])
        if shared is not None and shared!=current:raise ValueError('公共顶层元数据不一致，不能直接合包')
        shared=current
        identities={groups[0]['root_guid']}|set(groups[0]['unit_records'])
        if seen&identities:raise ValueError('不同输入的 GUID 冲突')
        indices={alg.registration_index(alg.content(groups[0]['root_record']))}
        indices.update(alg.registration_index(alg.content(unit))for unit in groups[0]['unit_records'].values())
        if seen_indices&indices:raise ValueError('不同素材组的注册索引冲突')
        seen_indices.update(indices)
        seen.update(identities);sources.append(groups[0])
        root_items.extend(i for i in top if i[0]==1)
        unit_items.extend(i for i in top if i[0]==2)
    result=container(alg.encode(root_items+unit_items)+shared)
    readback=split_bundle(result)
    if len(readback)!=len(sources):raise ValueError('合集根数量错误')
    for before,after in zip(sources,readback):
        if (before['root_record']!=after['root_record'] or before['unit_records']!=after['unit_records']
                or before['scene']!=after['scene']):
            raise ValueError('合包改变了图元、名称、未知字段或层序')
    return result,readback

