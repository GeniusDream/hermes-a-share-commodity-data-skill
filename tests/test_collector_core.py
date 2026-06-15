from a_share_data_collector import (
    DEFAULT_COMMODITY_CODES,
    DEFAULT_INDEX_HISTORY_CODES,
    Row,
    collect_commodity_universe,
    emit,
    format_board_name_rows,
    parse_index_symbols,
    parse_symbols,
)
import json


def test_parse_symbols_known_and_custom():
    out = parse_symbols('白银连续,自定义=nf_XX0,nf_PG0', DEFAULT_COMMODITY_CODES)
    assert out['白银连续'] == 'nf_AG0'
    assert out['自定义'] == 'nf_XX0'
    assert out['nf_PG0'] == 'nf_PG0'


def test_default_commodity_universe_is_broad():
    assert len(DEFAULT_COMMODITY_CODES) >= 70
    assert DEFAULT_COMMODITY_CODES['碳酸锂连续'] == 'nf_LC0'
    assert DEFAULT_COMMODITY_CODES['集运指数欧线连续'] == 'nf_EC0'
    assert DEFAULT_COMMODITY_CODES['丙烯连续'] == 'nf_PL0'


def test_format_board_name_rows_filters_keyword():
    records = [
        {'name': '电池', 'code': '881166'},
        {'name': '锂电池概念', 'code': '308508'},
        {'name': '贵金属', 'code': '881155'},
    ]
    rows = format_board_name_rows(records, 'concept', keyword='电池')
    assert [r.name for r in rows] == ['电池', '锂电池概念']
    assert rows[0].source == 'akshare_ths'
    assert rows[0].dataset == 'a_share_board_name'
    assert rows[0].code == '881166'
    assert rows[0].raw == {'board_type': 'concept'}


def test_emit_jsonl(tmp_path):
    path = tmp_path / 'rows.jsonl'
    emit([Row(source='test', dataset='demo', name='电池', pct_chg=-2.53)], 'jsonl', str(path))
    line = path.read_text(encoding='utf-8').strip()
    obj = json.loads(line)
    assert obj['source'] == 'test'
    assert obj['dataset'] == 'demo'
    assert obj['name'] == '电池'
    assert obj['pct_chg'] == -2.53


def test_emit_csv(tmp_path):
    path = tmp_path / 'rows.csv'
    emit([Row(source='test', dataset='demo', name='贵金属')], 'csv', str(path))
    text = path.read_text(encoding='utf-8')
    assert 'source,dataset' in text
    assert '贵金属' in text


def test_commodity_universe_rows_include_metadata():
    rows = collect_commodity_universe({'碳酸锂连续': 'nf_LC0', '铜连续': 'nf_CU0'})
    assert [r.dataset for r in rows] == ['commodity_universe', 'commodity_universe']
    assert rows[0].raw['exchange'] == 'GFEX'
    assert rows[0].raw['contract_type'] == 'continuous'
    assert rows[1].raw['category'] == '有色/贵金属'


def test_parse_index_symbols_known_and_custom():
    out = parse_index_symbols('上证指数,自定义=sh000999,sh000300')
    assert out['上证指数'] == DEFAULT_INDEX_HISTORY_CODES['上证指数']
    assert out['自定义'] == 'sh000999'
    assert out['sh000300'] == 'sh000300'


def test_default_index_history_universe_has_benchmarks():
    assert DEFAULT_INDEX_HISTORY_CODES['沪深300'] == 'sh000300'
    assert DEFAULT_INDEX_HISTORY_CODES['中证500'] == 'sh000905'
    assert DEFAULT_INDEX_HISTORY_CODES['中证1000'] == 'sh000852'
