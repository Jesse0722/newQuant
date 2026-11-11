"""Synthetic offline inputs; never reconstruct membership from current basics."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def save_json(path, value):
    body = (json.dumps(value, ensure_ascii=False) + '\n').encode()
    path.write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def raw_source(query, rows, day='2026-10-30'):
    basic = query == 'query_stock_basic'
    return {'provider':'baostock','sdk_version':'0.9.1','query':query,
        'request':{'code':'','code_name':''} if basic else {'day':day},
        'response_day':'' if basic else day,
        'fields':['code','code_name','ipoDate','outDate','type','status'] if basic else ['code','tradeStatus','code_name'],
        'rows':rows,'error_code':'0','row_count':len(rows),'observed_at':'2026-11-11T12:00:00+08:00'}


@pytest.fixture
def package(tmp_path):
    directory = tmp_path/'input'
    directory.mkdir()
    membership = raw_source('query_all_stock', [['sh.600001','1','历史名称'],['sh.603001','0','停牌名称'],['sz.302132','1','创业板'],['sh.688001','1','科创板'],['sh.000001','1','上证指数']])
    basic = raw_source('query_stock_basic', [
        ['sh.600001','现名称','2000-01-01','2026-11-01','1','0'],
        ['sh.603001','停牌现名称','2010-01-01','','1','1'],
        ['sh.605999','仅当前主数据','2020-01-01','','1','1'],
        ['sh.000001','上证指数','1991-07-15','','2','1']])
    input_doc={'version':'historical-universe-input-v1','selection':'sse_main_board_a',
        'scope':'security_subset','temporal_basis':'retrospective','dates':['20261030'],
        'membership_sources':[{'trade_date':'20261030','path':'membership.json','sha256':save_json(directory/'membership.json',membership)}],
        'basic_source':{'path':'basic.json','sha256':save_json(directory/'basic.json',basic)},
        'documentation_sources':[{'id':'provider-definitions','path':'definition.md','sha256':hashlib.sha256(b'synthetic definitions').hexdigest(),'url':'https://provider.example.invalid/definition','locator':'synthetic definitions only'}]}
    (directory/'definition.md').write_bytes(b'synthetic definitions')
    path=directory/'input.json'
    save_json(path,input_doc)
    return path


def build(package, output):
    from app.services.historical_universe_service import build_historical_universe
    return build_historical_universe(package, hashlib.sha256(package.read_bytes()).hexdigest(), output)


def mutate_source(package, filename, mutation):
    doc=json.loads(package.read_text())
    path=package.parent/filename
    source=json.loads(path.read_text())
    mutation(source)
    sha=save_json(path,source)
    if filename=='membership.json':doc['membership_sources'][0]['sha256']=sha
    else:doc['basic_source']['sha256']=sha
    save_json(package,doc)


def test_historical_membership_keeps_suspensions_names_and_current_retirees(package,tmp_path):
    output=tmp_path/'output'
    result=build(package,output)
    rows=list(csv.DictReader(io.StringIO((output/'universe.csv').read_text())))
    assert [(r['ts_code'],r['is_listed'],r['is_trading'],r['name']) for r in rows]==[
        ('600001.SH','1','1','历史名称'),('603001.SH','1','0','停牌名称')]
    assert not (output/'counts.csv').exists()
    report=json.loads((output/'build-report.json').read_text())
    assert report['scope']=='security_subset' and report['temporal_basis']=='retrospective'
    assert report['days'][0]['observed_listed']==2
    assert report['days'][0]['observed_trading']==1
    assert report['days'][0]['observed_suspended']==1
    lineage=[json.loads(line) for line in (output/'row-lineage.jsonl').read_text().splitlines()]
    assert lineage[0]['membership']['row_number']==1
    assert lineage[0]['membership']['raw_values']['code_name']=='历史名称'
    assert lineage[0]['basic']['raw_values']['code_name']=='现名称'
    assert lineage[0]['basic']['raw_values']['status']=='0'
    assert result['scope']=='security_subset'
    assert os.stat(output).st_mode & 0o777 == 0o700
    assert all(os.stat(p).st_mode & 0o777 == 0o600 for p in output.iterdir())
    index=json.loads((output/'complete-index.json').read_text())
    for name,item in index['files'].items():assert hashlib.sha256((output/name).read_bytes()).hexdigest()==item['sha256']


@pytest.mark.parametrize('filename,mutation',[
    ('membership.json',lambda d:d.update(row_count=999)),
    ('membership.json',lambda d:d.update(row_count=True)),
    ('membership.json',lambda d:d.update(rows=[] ,row_count=0)),
    ('membership.json',lambda d:d.update(error_code='1')),
    ('membership.json',lambda d:d.update(response_day='2026-11-10')),
    ('membership.json',lambda d:d.update(request={'day':'2026-11-10'})),
    ('membership.json',lambda d:d.update(fields=['code','tradeStatus','tradeStatus'])),
    ('membership.json',lambda d:d['rows'][0].append('extra')),
    ('membership.json',lambda d:d['rows'][0].__setitem__(1,1)),
    ('membership.json',lambda d:d['rows'][0].__setitem__(1,'unknown')),
    ('membership.json',lambda d:d['rows'][0].__setitem__(0,'SH.600001')),
    ('membership.json',lambda d:d.update(rows=d['rows']+[d['rows'][0]],row_count=6)),
    ('basic.json',lambda d:d['rows'][0].__setitem__(4,'2')),
    ('basic.json',lambda d:d['rows'][0].__setitem__(2,'')),
    ('basic.json',lambda d:d['rows'][0].__setitem__(2,'2026-10-31')),
    ('basic.json',lambda d:d['rows'][0].__setitem__(3,'2026-10-30')),
    ('basic.json',lambda d:d['rows'][0].__setitem__(5,'unknown')),
    ('basic.json',lambda d:d.update(rows=d['rows'][1:],row_count=3)),
])
def test_rejects_unknown_or_conflicting_raw_inputs_before_output(package,tmp_path,filename,mutation):
    mutate_source(package,filename,mutation)
    output=tmp_path/'output'
    with pytest.raises(ValueError):build(package,output)
    assert not output.exists()


def test_302_is_explicit_cyb_family_in_all_classifiers():
    from app.services.market_data_quality_service import CODE
    from app.services.source_identity import identity_code
    from app.services.main_wave_service import _market_group
    from app.services.tushare_adapter import BaoStockAdapter,TencentAdapter
    for code in ['300001','301001','302132']:
        assert CODE.fullmatch(code+'.SZ')
        assert identity_code('akshare',code,0)==code+'.SZ'
        assert _market_group(code+'.SZ')=='cyb'
        assert BaoStockAdapter._infer_market(code+'.SZ')=='创业板'
        assert TencentAdapter._infer_market(code+'.SZ')=='创业板'
    for code in ['303001.SZ','302132.SH','302132.BJ']:
        assert CODE.fullmatch(code) is None
    with pytest.raises(ValueError):identity_code('akshare','302132',1)


def test_cyb_sql_filter_includes_302_but_no_unknown_3xx():
    from sqlalchemy import create_engine,MetaData,Table,Column,String,select
    from app.services.main_wave_service import _market_group_filter
    from app.models.stock import DailyQuote
    engine=create_engine('sqlite:///:memory:')
    metadata=MetaData()
    table=Table(DailyQuote.__tablename__,metadata,Column('ts_code',String))
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(table.insert(),[{'ts_code':s} for s in ['300001.SZ','301001.SZ','302132.SZ','303001.SZ','302132.SH']])
        assert set(conn.execute(select(DailyQuote.ts_code).where(_market_group_filter('cyb'))).scalars())=={'300001.SZ','301001.SZ','302132.SZ'}
    engine.dispose()


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(scope='full_market_point_in_time'),
    lambda d:d.update(selection='all_a_share'),
    lambda d:d.update(temporal_basis='contemporaneous'),
    lambda d:d.update(dates=['20261030','20261030']),
    lambda d:d.update(dates=['20261030','20261110']),
    lambda d:d['membership_sources'].append(dict(d['membership_sources'][0])),
    lambda d:d['membership_sources'][0].update(trade_date='20261110'),
    lambda d:d['membership_sources'][0].update(sha256='0'*64),
    lambda d:d['basic_source'].update(sha256='0'*64),
    lambda d:d['basic_source'].update(path='../outside.json'),
    lambda d:d['basic_source'].update(path='/tmp/outside.json'),
    lambda d:d.update(documentation_sources=[]),
    lambda d:d['documentation_sources'][0].update(sha256='0'*64),
    lambda d:d['documentation_sources'][0].update(url='https://'),
    lambda d:d['documentation_sources'][0].update(url='https://u:secret@provider.invalid/'),
    lambda d:d['documentation_sources'][0].update(locator=''),
    lambda d:d['documentation_sources'].append(dict(d['documentation_sources'][0])),
])
def test_package_scope_grid_hashes_and_docs_are_mandatory(package,tmp_path,mutation):
    doc=json.loads(package.read_text())
    mutation(doc)
    save_json(package,doc)
    output=tmp_path/'output'
    with pytest.raises(ValueError):build(package,output)
    assert not output.exists()


@pytest.mark.parametrize('filename', ['input.json','membership.json','basic.json'])
def test_duplicate_json_keys_rejected_even_with_matching_pinned_hash(package,tmp_path,filename):
    path=package.parent/filename
    body=path.read_text()
    key='scope' if filename=='input.json' else 'error_code'
    path.write_text('{'+json.dumps(key)+':"forged",'+body[1:])
    if filename!='input.json':
        doc=json.loads(package.read_text())
        pointer=doc['membership_sources'][0] if filename=='membership.json' else doc['basic_source']
        pointer['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        save_json(package,doc)
    with pytest.raises(ValueError,match='重复JSON'):build(package,tmp_path/'output')


def test_pinned_package_mismatch_refuses_before_output(package,tmp_path):
    from app.services.historical_universe_service import build_historical_universe
    with pytest.raises(ValueError):build_historical_universe(package,'0'*64,tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_source_symlink_escape_is_rejected(package,tmp_path):
    path=package.parent/'basic.json'
    outside=tmp_path/'outside.json'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError):build(package,tmp_path/'output')


@pytest.mark.parametrize('filename,mutation',[
    ('membership.json',lambda d:d.update(observed_at='2026-11-11T12:00:00')),
    ('membership.json',lambda d:d.update(provider='other')),
    ('membership.json',lambda d:d.update(sdk_version='other')),
    ('membership.json',lambda d:d.update(query='query_stock_basic')),
    ('membership.json',lambda d:d['rows'][0].__setitem__(0,'sh.606001')),
    ('membership.json',lambda d:d['rows'][0].__setitem__(2,' ')),
    ('basic.json',lambda d:d.update(response_day='2026-10-30')),
    ('basic.json',lambda d:d.update(request={'code':'sh.600001','code_name':''})),
    ('basic.json',lambda d:d.update(rows=d['rows']+[d['rows'][0]],row_count=5)),
    ('basic.json',lambda d:d['rows'][0].__setitem__(4,'unknown')),
    ('basic.json',lambda d:d['rows'][0].__setitem__(2,'2026-02-30')),
    ('basic.json',lambda d:d['rows'][0].__setitem__(3,'')),
])
def test_raw_request_identity_lifecycle_and_unknown_candidates_are_strict(package,tmp_path,filename,mutation):
    mutate_source(package,filename,mutation)
    with pytest.raises(ValueError):build(package,tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_all_basic_rows_do_not_add_members_even_when_valid_and_current(package,tmp_path):
    # In particular sh.605999 is in current basics but never appears in dated membership.
    build(package,tmp_path/'output')
    assert '605999' not in (tmp_path/'output'/'universe.csv').read_text()


def test_two_dates_keep_their_own_names_and_states(package,tmp_path):
    doc=json.loads(package.read_text())
    doc['dates'].append('20261029')
    second=raw_source('query_all_stock',[['sh.600001','0','另一天原名']],day='2026-10-29')
    doc['membership_sources'].append({'trade_date':'20261029','path':'day-two.json','sha256':save_json(package.parent/'day-two.json',second)})
    save_json(package,doc)
    build(package,tmp_path/'output')
    rows=list(csv.DictReader((tmp_path/'output'/'universe.csv').open()))
    assert rows[0]['trade_date']=='20261029' and rows[0]['name']=='另一天原名' and rows[0]['is_trading']=='0'
    assert rows[1]['trade_date']=='20261030' and rows[1]['name']=='历史名称' and rows[1]['is_trading']=='1'


def test_package_hash_and_parse_consume_one_read(package,tmp_path,monkeypatch):
    from app.services import historical_universe_service as service
    original=service._read_regular
    pin=hashlib.sha256(package.read_bytes()).hexdigest()
    calls=[]
    def read(path):
        body=original(path);calls.append(path)
        path.write_text('invalid replacement after read')
        return body
    monkeypatch.setattr(service,'_read_regular',read)
    service.build_historical_universe(package,pin,tmp_path/'output')
    assert calls==[package.resolve()]
    assert json.loads((tmp_path/'output'/'build-report.json').read_text())['input_package']['sha256']==pin


def test_source_hash_and_parse_consume_identical_bytes(package,tmp_path,monkeypatch):
    from app.services import historical_universe_service as service
    original=service._package_bytes
    seen=[]
    def read(base,relative):
        body,resolved=original(base,relative);seen.append(relative)
        Path(resolved).write_bytes(b'replaced after one read')
        return body,resolved
    monkeypatch.setattr(service,'_package_bytes',read)
    build(package,tmp_path/'output')
    assert sorted(seen)==['basic.json','definition.md','membership.json']


@pytest.mark.parametrize('existing', ['directory','file','symlink'])
def test_output_must_be_new_and_existing_content_never_changes(package,tmp_path,existing):
    output=tmp_path/'output'
    target=tmp_path/'unrelated'
    target.write_bytes(b'preserve')
    if existing=='directory':
        output.mkdir();(output/'sentinel').write_bytes(b'preserve')
    elif existing=='file':output.write_bytes(b'preserve')
    else:output.symlink_to(target)
    with pytest.raises(ValueError):build(package,output)
    assert target.read_bytes()==b'preserve'
    if existing=='directory':assert (output/'sentinel').read_bytes()==b'preserve'
    else:assert output.read_bytes()==b'preserve'


@pytest.mark.parametrize('failure_phase', ['fsync','fchmod','short_write','interrupt'])
def test_publish_failures_clean_owned_files_and_close_descriptors(package,tmp_path,monkeypatch,failure_phase):
    from app.services import historical_universe_service as service
    original_open=os.open
    original_fsync=os.fsync
    original_chmod=os.fchmod
    original_fdopen=os.fdopen
    opened=[]
    def opening(path,*args,**kwargs):
        fd=original_open(path,*args,**kwargs)
        # Input source fd opens are closed by the existing evidence helpers too.
        opened.append(fd)
        return fd
    monkeypatch.setattr(service.os,'open',opening)
    calls=[]
    def syncing(fd):
        calls.append(fd)
        if len(calls)==2:
            if failure_phase=='interrupt':raise KeyboardInterrupt
            raise OSError('injected fsync failure')
        return original_fsync(fd)
    def chmod(fd,mode):
        if mode==0o600:raise OSError('injected chmod failure')
        return original_chmod(fd,mode)
    class Short:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):return self
        def __exit__(self,*args):self.stream.close()
        def write(self,body):return len(body)-1
    if failure_phase in ('fsync','interrupt'):monkeypatch.setattr(service.os,'fsync',syncing)
    elif failure_phase=='fchmod':monkeypatch.setattr(service.os,'fchmod',chmod)
    else:
        def fdopen(*args,**kwargs):
            stream=original_fdopen(*args,**kwargs)
            return Short(stream) if args[1]=='wb' else stream
        monkeypatch.setattr(service.os,'fdopen',fdopen)
    with pytest.raises((ValueError,KeyboardInterrupt)):build(package,tmp_path/'output')
    assert not (tmp_path/'output').exists()
    for fd in opened:
        with pytest.raises(OSError):os.fstat(fd)


def test_publish_preserves_competing_file_and_only_cleans_own_artifacts(package,tmp_path,monkeypatch):
    from app.services import historical_universe_service as service
    original=os.open
    output=tmp_path/'output'
    def competing(path,flags,*args,**kwargs):
        if path=='row-lineage.jsonl' and flags & os.O_CREAT:
            (output/'competitor').write_bytes(b'keep')
            (output/'row-lineage.jsonl').write_bytes(b'other writer')
        return original(path,flags,*args,**kwargs)
    monkeypatch.setattr(service.os,'open',competing)
    with pytest.raises(ValueError):build(package,output)
    assert (output/'competitor').read_bytes()==b'keep'
    assert (output/'row-lineage.jsonl').read_bytes()==b'other writer'
    assert not (output/'universe.csv').exists()


def test_publish_preserves_replacement_instead_of_deleting_it(package,tmp_path,monkeypatch):
    from app.services import historical_universe_service as service
    original=os.fsync
    output=tmp_path/'output'
    count=[]
    def replace(fd):
        count.append(fd)
        if len(count)==2:
            (output/'universe.csv').unlink()
            (output/'universe.csv').write_bytes(b'replacement')
            raise OSError('injected failure after replacement')
        return original(fd)
    monkeypatch.setattr(service.os,'fsync',replace)
    with pytest.raises(ValueError):build(package,output)
    assert (output/'universe.csv').read_bytes()==b'replacement'
    assert not (output/'row-lineage.jsonl').exists()


def test_cli_real_process_and_import_do_not_bootstrap_application(package,tmp_path):
    script=Path(__file__).resolve().parents[1]/'scripts'/'build_historical_universe.py'
    command=[sys.executable,str(script),'--input-package',str(package),'--input-sha256',hashlib.sha256(package.read_bytes()).hexdigest(),'--output-dir',str(tmp_path/'output')]
    result=subprocess.run(command,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['scope']=='security_subset'
    # An existing directory cannot be adopted on retry.
    assert subprocess.run(command,capture_output=True,text=True,timeout=10).returncode==1
    assertion="import sys; import scripts.build_historical_universe; assert not [n for n in sys.modules if n=='app.database' or n=='app.config' or n.startswith('app.providers') or 'scheduler' in n]"
    process=subprocess.run([sys.executable,'-c',assertion],cwd=script.parents[1],capture_output=True,text=True,timeout=10)
    assert process.returncode==0,process.stderr


def test_cli_errors_do_not_echo_exception_credentials(package,tmp_path,monkeypatch,capsys):
    from scripts import build_historical_universe as cli
    def failure(*args):raise ValueError('https://user:NEVER_PRINT@private.invalid/')
    monkeypatch.setattr(cli,'build_historical_universe',failure)
    assert cli.main(['--input-package',str(package),'--input-sha256','0'*64,'--output-dir',str(tmp_path/'output')])==1
    capture=capsys.readouterr()
    assert 'NEVER_PRINT' not in capture.out+capture.err


def test_302_repair_units_and_upstream_identity_remain_compatible():
    from test_daily_quote_repair import row,snapshot
    from app.services.daily_quote_repair_service import normalized_source_row
    source=snapshot([row(code='302132.SZ')])
    normalized=normalized_source_row(source['rows'][0],source['source'])
    assert normalized['ts_code']=='302132.SZ'
    assert normalized['vol']==10 and normalized['amount']==10


def test_empty_document_cannot_satisfy_required_documentation(package,tmp_path):
    doc=json.loads(package.read_text())
    (package.parent/'definition.md').write_bytes(b'')
    doc['documentation_sources'][0]['sha256']=hashlib.sha256(b'').hexdigest()
    save_json(package,doc)
    with pytest.raises(ValueError):build(package,tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_serialization_finishes_before_any_output_is_reserved(package,tmp_path,monkeypatch):
    from app.services import historical_universe_service as service
    def failure(_value):raise ValueError('synthetic serialization failure')
    monkeypatch.setattr(service,'_json_bytes',failure)
    with pytest.raises(ValueError):build(package,tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_directory_replacement_does_not_receive_writes_or_cleanup(package,tmp_path,monkeypatch):
    from app.services import historical_universe_service as service
    original=os.fsync
    output=tmp_path/'output'
    moved=tmp_path/'moved-original'
    calls=[]
    def replacing(fd):
        calls.append(fd)
        if len(calls)==1:
            output.rename(moved)
            output.mkdir()
            (output/'sentinel').write_bytes(b'keep unrelated')
        return original(fd)
    monkeypatch.setattr(service.os,'fsync',replacing)
    with pytest.raises(ValueError):build(package,output)
    assert sorted(p.name for p in output.iterdir())==['sentinel']
    assert (output/'sentinel').read_bytes()==b'keep unrelated'
    assert list(moved.iterdir())==[]
