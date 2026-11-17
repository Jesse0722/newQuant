from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import select, update, insert

from test_daily_quote_repair import db, row, snapshot, backup, states
from app.services.daily_quote_repair_service import (
    Q, B, A, VALUE_FIELDS, RepairError, make_repair_plan, validate_plan,
    apply_repair_plan, verify_repair_batch, rollback_repair_batch, digest,
    state_hash, normalized_source_row, _input_grid_digest,
)
from app.services.market_data_quality_service import readonly_connection
from app.services.quote_repair_io import writer_connection
from scripts.repair_daily_quotes import render_plan


def seed_optional(db, **overrides):
    with writer_connection(db[0],str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code=='000001.SZ').values(
            **{'turnover_rate':3.25,'float_share':12345.6789012345,**overrides}))


def make(db, rows=None, **kwargs):
    source=snapshot(rows if rows is not None else [row()])
    with readonly_connection(db[0],db[1]) as (conn,_):
        return make_repair_plan(conn,source,**kwargs)


def test_explicit_preserve_repairs_core_and_records_existing_optional_lineage(db):
    seed_optional(db)
    default=make(db)
    assert default['summary']['skipped']==1 and default['items']==[]
    plan=make(db,preserve_existing_optional=True)
    validate_plan(plan)
    assert plan['policy']['selection']=='single_authoritative_core_preserve_optional_v1'
    assert plan['policy']['preserve_existing_optional'] is True
    assert plan['summary']['updates']==1 and plan['summary']['skipped']==0
    item=plan['items'][0]
    assert item['new_values']['pre_close']==10 and item['new_values']['amount']==10
    for field in ('turnover_rate','float_share'):
        assert item['new_values'][field]==item['old_values'][field]
        assert item['source_json']['field_source'][field]=={
            'kind':'retained_existing_optional','field':field,'old_row_hash':item['old_hash']}
    assert item['source_json']['preserved_optional_fields']==['turnover_rate','float_share']
    assert item['source_json']['field_source']['amount']==item['source_json']['raw_hash']
    assert '旧值' in render_plan(plan) and '不是本次供应商提供' in render_plan(plan)


@pytest.mark.parametrize('kwargs',[
    {'preserve_existing_optional':True,'allow_clear_optional':True},
    {'preserve_existing_optional':1}, {'preserve_existing_optional':'true'},
    {'preserve_existing_optional':None}, {'allow_clear_optional':1},
])
def test_policy_api_requires_exclusive_strict_bools(db,kwargs):
    with pytest.raises(RepairError):make(db,**kwargs)


def test_source_optional_values_take_priority_over_old_values(db):
    seed_optional(db)
    plan=make(db,[row(turnover_rate=4.5,float_share=9999)],preserve_existing_optional=True)
    item=plan['items'][0]
    assert item['new_values']['turnover_rate']==4.5 and item['new_values']['float_share']==9999
    assert item['source_json']['preserved_optional_fields']==[]
    assert item['source_json']['field_source']=={field:item['source_json']['raw_hash'] for field in VALUE_FIELDS}


def test_invalid_existing_optional_is_not_carried(db):
    seed_optional(db,turnover_rate=-1,float_share=-99)
    plan=make(db,preserve_existing_optional=True)
    item=plan['items'][0]
    assert item['new_values']['turnover_rate'] is None and item['new_values']['float_share'] is None
    assert item['source_json']['preserved_optional_fields']==[]


def mixed_plan(db):
    seed_optional(db)
    source=snapshot([row(),row(day='20261009')])
    second=normalized_source_row(source['rows'][1],source['source'])
    second.update(turnover_rate=3.25,float_share=12345.6789012345)
    with writer_connection(db[0],str(db[1])) as conn:
        conn.execute(insert(Q).values(**second))
    return make(db,[row(),row(day='20261009')],preserve_existing_optional=True)


def rehash(plan):
    for item in plan['items']:
        item['old_hash']=state_hash(item['old_values'])
        item['new_hash']=digest(item['new_values'])
    plan['input_grid_digest']=_input_grid_digest(plan)


@pytest.mark.parametrize('tamper',[
    lambda p:p['items'][0]['new_values'].update(float_share=None),
    lambda p:p['items'][0]['new_values'].update(float_share=99999),
    lambda p:p['items'][0]['new_values'].update(close=10.1),
    lambda p:p['items'][0]['new_values'].update(vol=999),
    lambda p:p['items'][0]['source_json']['field_source'].update(float_share=p['items'][0]['source_json']['raw_hash']),
    lambda p:p['items'][0]['source_json']['field_source']['float_share'].update(old_row_hash='0'*64),
    lambda p:p['items'][0]['source_json']['field_source']['float_share'].update(field='amount'),
    lambda p:p['items'][0]['source_json']['field_source'].update(amount={'kind':'retained_existing_optional','field':'amount','old_row_hash':p['items'][0]['old_hash']}),
    lambda p:p['items'][0]['source_json'].update(preserved_optional_fields=['float_share']),
    lambda p:p['items'][0]['source_json'].update(preserved_optional_fields=['turnover_rate','float_share','amount']),
    lambda p:p['items'][0].update(changed_fields=['pre_close']),
])
def test_new_mode_rejects_tampered_effective_values_or_lineage_even_after_rehash(db,tamper):
    seed_optional(db)
    plan=make(db,preserve_existing_optional=True)
    tamper(plan);rehash(plan)
    with pytest.raises(RepairError):validate_plan(plan)


@pytest.mark.parametrize('tamper',[
    lambda p:p['policy'].update(preserve_existing_optional=1),
    lambda p:p['policy'].update(preserve_existing_optional=False),
    lambda p:p['policy'].update(allow_clear_optional=True),
    lambda p:p['policy'].pop('input_validation'),
    lambda p:p.pop('input_grid'),
    lambda p:p['policy'].update(extra_policy='allow_core_mix'),
])
def test_new_selection_requires_explicit_strict_policy_and_full_grid_even_legacy(db,tamper):
    seed_optional(db)
    plan=make(db,preserve_existing_optional=True)
    tamper(plan)
    with pytest.raises(RepairError):validate_plan(plan,allow_legacy=True)


def test_source_value_cannot_be_falsely_labeled_retained(db):
    seed_optional(db)
    plan=make(db,[row(float_share=20000)],preserve_existing_optional=True)
    item=plan['items'][0]
    item['new_values']['float_share']=item['old_values']['float_share']
    item['source_json']['preserved_optional_fields'].append('float_share')
    item['source_json']['field_source']['float_share']={'kind':'retained_existing_optional','field':'float_share','old_row_hash':item['old_hash']}
    rehash(plan)
    with pytest.raises(RepairError):validate_plan(plan)


def test_default_mode_cannot_claim_new_mode_lineage_or_flag(db):
    plan=make(db)
    plan['policy']['preserve_existing_optional']=True
    with pytest.raises(RepairError):validate_plan(plan)
    plan=make(db)
    plan['items'][0]['source_json']['preserved_optional_fields']=[]
    with pytest.raises(RepairError):validate_plan(plan)


def test_default_grid_digest_payload_is_unchanged_and_new_mode_binds_policy(db):
    default=make(db)
    assert default['input_grid_digest']==digest({'policy':'complete-grid-price-volume-v1','codes':default['codes'],
        'dates':default['dates'],'source':default['source'],'cells':default['input_grid']})
    assert 'preserve_existing_optional' not in default['policy']
    preserved=make(db,preserve_existing_optional=True)
    before=preserved['input_grid_digest']
    preserved['policy']['preserve_existing_optional']=False
    assert _input_grid_digest(preserved)!=before


@pytest.mark.parametrize('tamper',[
    lambda p:p['input_grid'][1]['proof'].pop('field_source'),
    lambda p:p['input_grid'][1]['proof'].update(preserved_optional_fields=[]),
    lambda p:p['input_grid'][1]['proof']['field_source']['float_share'].update(old_row_hash='0'*64),
    lambda p:p['input_grid'][1]['proof']['raw_values'].update(close=10.1),
])
def test_unchanged_cells_recompute_effective_row_and_lineage(db,tamper):
    plan=mixed_plan(db)
    assert plan['summary']['updates']==1 and plan['summary']['unchanged']==1
    assert plan['input_grid'][1]['proof']['preserved_optional_fields']==['turnover_rate','float_share']
    tamper(plan)
    plan['input_grid_digest']=_input_grid_digest(plan)
    with pytest.raises(RepairError):validate_plan(plan)


def test_complete_grid_validator_independently_rechecks_written_effective_values(db):
    from app.services.daily_quote_repair_service import _validate_input_grid
    seed_optional(db)
    plan=make(db,preserve_existing_optional=True)
    plan['items'][0]['new_values']['float_share']=None
    rehash(plan)
    with pytest.raises(RepairError):_validate_input_grid(plan)


def test_only_retained_fields_can_make_an_entire_plan_unchanged(db):
    seed_optional(db)
    source=snapshot([row()])
    effective=normalized_source_row(source['rows'][0],source['source'])
    effective.update(turnover_rate=3.25,float_share=12345.6789012345)
    with writer_connection(db[0],str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code=='000001.SZ').values(**effective))
    plan=make(db,preserve_existing_optional=True)
    validate_plan(plan)
    assert plan['summary']['unchanged']==1 and plan['items']==[]
    with writer_connection(db[0],str(db[1])) as conn:
        assert apply_repair_plan(conn,plan,None)['status']=='no_changes'
        assert conn.execute(select(B)).all()==[]
    # Even a no-write retained cell must match all frozen old values.
    with writer_connection(db[0],str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code=='000001.SZ').values(float_share=12345))
    with pytest.raises(RepairError):
        with writer_connection(db[0],str(db[1])) as conn:apply_repair_plan(conn,plan,None)


def test_sqlite_preserve_roundtrip_and_unchanged_scope_verify_exactly(db):
    plan=mixed_plan(db)
    before=states(db)
    with writer_connection(db[0],str(db[1])) as conn:
        result=apply_repair_plan(conn,plan,backup(db))
    with readonly_connection(db[0],db[1]) as (conn,_):
        verification=verify_repair_batch(conn,result['batch_id'])
        assert verification['matches'] is True and verification['audit_integrity'] is True
        assert verification['verification_scope']=='full_input_grid' and verification['scope_rows']==2
    with writer_connection(db[0],str(db[1])) as conn:
        rollback_repair_batch(conn,result['batch_id'],backup(db))
    assert states(db)==before
    with readonly_connection(db[0],db[1]) as (conn,_):
        assert verify_repair_batch(conn,result['batch_id'])['matches'] is True


@pytest.mark.parametrize('day', ['20261008','20261009'])
def test_preserved_value_drift_blocks_apply_even_with_fresh_backup(db,day):
    plan=mixed_plan(db)
    with writer_connection(db[0],str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code=='000001.SZ',Q.c.trade_date==day).values(float_share=9999))
    fresh=backup(db)
    with pytest.raises(RepairError):
        with writer_connection(db[0],str(db[1])) as conn:apply_repair_plan(conn,plan,fresh)
    with readonly_connection(db[0],db[1]) as (conn,_):assert conn.execute(select(B)).all()==[]


def test_verify_and_rollback_include_nonwriting_retained_cells(db):
    plan=mixed_plan(db)
    with writer_connection(db[0],str(db[1])) as conn:result=apply_repair_plan(conn,plan,backup(db))
    with writer_connection(db[0],str(db[1])) as conn:
        conn.execute(update(Q).where(Q.c.ts_code=='000001.SZ',Q.c.trade_date=='20261009').values(turnover_rate=88))
    with readonly_connection(db[0],db[1]) as (conn,_):
        verification=verify_repair_batch(conn,result['batch_id'])
        assert verification['audit_integrity'] is True and verification['matches'] is False
        assert verification['mismatches'][0]['disposition']=='unchanged'
    fresh=backup(db)
    with pytest.raises(RepairError):
        with writer_connection(db[0],str(db[1])) as conn:rollback_repair_batch(conn,result['batch_id'],fresh)


def test_cli_flags_are_mutually_exclusive_and_new_mode_is_explicit(db,tmp_path,monkeypatch):
    from scripts import repair_daily_quotes as cli
    seed_optional(db)
    snap=tmp_path/'source.json';cli.write_json(snap,snapshot([row()]))
    monkeypatch.setenv('DATABASE_URL',db[0])
    output=tmp_path/'preserve-plan.json'
    argv=['--app-cwd',str(db[1]),'plan','--snapshot',str(snap),'--output',str(output),'--preserve-existing-optional']
    with pytest.raises(SystemExit):cli.main(argv+['--allow-clear-optional'])
    assert not output.exists()
    assert cli.main(argv)==0
    import json
    plan=json.loads(output.read_text())
    assert plan['policy']['preserve_existing_optional'] is True
    assert plan['summary']['updates']==1
    assert '不是本次供应商提供' in output.with_suffix('.md').read_text()
