from a_share_data_collector import (
    DEFAULT_COMMODITY_CODES,
    Row,
    emit,
    format_board_name_rows,
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
