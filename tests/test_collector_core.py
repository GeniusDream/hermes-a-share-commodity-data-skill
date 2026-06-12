from a_share_data_collector import Row, parse_symbols, DEFAULT_COMMODITY_CODES, emit
import json


def test_parse_symbols_known_and_custom():
    out = parse_symbols('白银连续,自定义=nf_XX0,nf_PG0', DEFAULT_COMMODITY_CODES)
    assert out['白银连续'] == 'nf_AG0'
    assert out['自定义'] == 'nf_XX0'
    assert out['nf_PG0'] == 'nf_PG0'


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
