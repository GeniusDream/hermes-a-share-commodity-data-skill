#!/usr/bin/env python3
"""A-share raw-material affected-board daily data collector, scorer, interface tester, and closure engine."""
import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
import warnings
from typing import Any, Callable, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from a_share_commodity_universe import ALL_QUOTE_CODES, ALL_MINLINE_SYMBOLS, DOMESTIC, FAMILY_KEYWORDS, family_for, normalize_name

import psycopg

DB_DSN = os.getenv('A_SHARE_DAILY_DSN') or 'postgresql://' + 'a_share' + ':a_share_daily_local@127.0.0.1:15432/a_share_daily'
TRADE_DATE = dt.datetime.now().date()
RUN_ID = os.getenv('A_SHARE_RUN_ID') or f"{TRADE_DATE:%Y%m%d}_{dt.datetime.now():%H%M%S}_{os.getpid()}"
RUN_TYPE = os.getenv('A_SHARE_RUN_TYPE') or 'collector'
RUN_TRIGGER = os.getenv('A_SHARE_RUN_TRIGGER') or 'manual'
REPORT_WINDOW_START = dt.datetime.combine(TRADE_DATE - dt.timedelta(days=1), dt.time(15, 0))
REPORT_WINDOW_END = dt.datetime.combine(TRADE_DATE, dt.time(15, 0))
RETRY_ATTEMPTS = int(os.getenv('A_SHARE_FETCH_RETRIES', '3'))
RETRY_BASE_SLEEP = float(os.getenv('A_SHARE_FETCH_RETRY_SLEEP', '1.0'))
BOARD_HISTORY_RETRY_ATTEMPTS = int(os.getenv('A_SHARE_BOARD_HISTORY_RETRIES', '2'))
BOARD_HISTORY_PACE_SECONDS = float(os.getenv('A_SHARE_BOARD_HISTORY_PACE_SECONDS', '0.25'))

SOURCE_NAMES = [
    'sina_futures',
    'sina_index',
    'akshare_fund_flow_industry',
    'akshare_fund_flow_concept',
    'akshare_sector_spot',
    'eastmoney_news',
    'wscn_livenews',
    'sina_futures_minline_windows',
    'sina_futures_history',
    'akshare_index_history',
    'akshare_board_history',
]

HISTORY_DAYS = int(os.getenv('A_SHARE_HISTORY_DAYS', '31'))
HISTORY_START_DATE = TRADE_DATE - dt.timedelta(days=HISTORY_DAYS)

INDEX_HISTORY_SYMBOLS = [
    ('sh000001', '000001', '上证指数'),
    ('sz399001', '399001', '深证成指'),
    ('sz399006', '399006', '创业板指'),
]

# 历史相关性仍以核心国内品种为主，扩展池先作为当日异动雷达和候选链路发现；
# 这样避免把农产品/小众化工等样本不足链路直接混入主评分。
FUTURES_HISTORY_SYMBOLS = [(x['symbol'], x['code'], x['name']) for x in DOMESTIC if x.get('core')]
KLINE_COMMODITY_NAMES = {
    '焦煤连续', '焦炭连续', '铁矿石连续', '螺纹钢连续', '热轧卷板连续',
    '铜连续', '铝连续', '沪锌连续', '镍连续',
    '上海原油连续', '甲醇连续', '燃料油连续', 'PTA连续', 'PVC连续',
}

BOARD_HISTORY_SYMBOLS = [
    # AKShare/Eastmoney 板块历史优先使用 BK 代码，避免每次中文名查代码的不稳定步骤。
    # industry: period='日k'; concept: period='daily'.
    {'asset_type': 'industry', 'code': 'BK0437', 'name': '煤炭行业', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK0479', 'name': '钢铁', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK0478', 'name': '有色金属', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK1027', 'name': '小金属', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK1626', 'name': '稀土', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK1031', 'name': '光伏设备', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK0546', 'name': '玻璃玻纤', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK1019', 'name': '化学原料', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK0471', 'name': '化学纤维', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK0481', 'name': '汽车零部件', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK1200', 'name': '电力设备', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK0739', 'name': '工程机械', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK1242', 'name': '家电零部件Ⅱ', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK1208', 'name': '建筑材料', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK0476', 'name': '装修建材', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK1419', 'name': '煤化工', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK0464', 'name': '石油石化', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK1265', 'name': '包装印刷', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK1032', 'name': '风电设备', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK1030', 'name': '电机Ⅱ', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK0457', 'name': '电网设备', 'period': '日k'},
    {'asset_type': 'industry', 'code': 'BK1408', 'name': '机器人', 'period': '日k'},
    {'asset_type': 'concept', 'code': 'BK0578', 'name': '稀土永磁', 'period': 'daily'},
    {'asset_type': 'concept', 'code': 'BK0900', 'name': '新能源车', 'period': 'daily'},
    {'asset_type': 'concept', 'code': 'BK1175', 'name': '玻璃基板', 'period': 'daily'},
    {'asset_type': 'concept', 'code': 'BK1090', 'name': '机器人概念', 'period': 'daily'},
]

# 同花顺板块指数作为 Eastmoney push2his 失效时的历史行情兜底。
# 只配置与当前“受原材料影响板块” universe 名称较稳定的一组行业；保留原 BK code 写入，避免影响评分映射。
THS_INDUSTRY_HISTORY_FALLBACK = {
    'BK0437': '煤炭开采加工',
    'BK0479': '钢铁',
    'BK1027': '小金属',
    'BK1031': '光伏设备',
    'BK1019': '化学原料',
    'BK0471': '化学纤维',
    'BK0481': '汽车零部件',
    'BK0739': '工程机械',
    'BK1208': '建筑材料',
    'BK0464': '石油加工贸易',
    'BK1265': '包装印刷',
    'BK1032': '风电设备',
    'BK1030': '电机',
    'BK0457': '电网设备',
}


@contextlib.contextmanager
def eastmoney_no_proxy_env():
    """Bypass proxy and force IPv4 for Eastmoney/AKShare requests in this process.

    Live probes on this host showed two independent failure modes for Eastmoney
    push2his history endpoints:
    - the local HTTP/SOCKS proxy can return empty/502 responses;
    - direct DNS may prefer IPv6, where Eastmoney closes the connection with
      RemoteDisconnected, while IPv4 returns 200 OK for the same URL.

    AKShare's wrappers call requests.get internally, so the most reliable scoped
    fix is to set NO_PROXY='*' and temporarily force socket.getaddrinfo to AF_INET
    only while the Eastmoney-backed history calls run.
    """
    keys = ('NO_PROXY', 'no_proxy')
    old_env = {k: os.environ.get(k) for k in keys}
    old_getaddrinfo = socket.getaddrinfo

    def ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return old_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    try:
        os.environ['NO_PROXY'] = '*'
        os.environ['no_proxy'] = '*'
        socket.getaddrinfo = ipv4_getaddrinfo
        yield
    finally:
        socket.getaddrinfo = old_getaddrinfo
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def clean_num(x):
    try:
        if x is None or x == '' or (isinstance(x, float) and math.isnan(x)):
            return None
        return float(x)
    except Exception:
        return None


def parse_ohlc_from_raw(raw: dict[str, Any], close_val: Optional[float] = None):
    raw = raw if isinstance(raw, dict) else {}
    def pick(*keys):
        for k in keys:
            if k in raw and raw[k] not in (None, ''):
                v = clean_num(raw[k])
                if v is not None:
                    return v
        return None
    o = pick('开盘', '开盘价', 'open')
    h = pick('最高', '最高价', 'high')
    l = pick('最低', '最低价', 'low')
    c = pick('收盘', '收盘价', 'close')
    if c is None and close_val is not None:
        c = float(close_val)
    if o is None and c is not None:
        o = c
    if h is None and o is not None and c is not None:
        h = max(o, c)
    if l is None and o is not None and c is not None:
        l = min(o, c)
    if None in (o, h, l, c):
        return None
    return o, h, l, c


def get(url, headers=None, timeout=15, encoding='utf-8'):
    headers = headers or {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout).read().decode(encoding, errors='replace')


def retry_fetch(source: str, fn: Callable[[], Any], attempts: int = RETRY_ATTEMPTS) -> tuple[Any, dict[str, Any]]:
    started = time.time()
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            data = fn()
            rows = len(data) if hasattr(data, '__len__') else (1 if data is not None else 0)
            if rows <= 0:
                raise RuntimeError('empty response')
            return data, {
                'source': source, 'status': 'ok', 'rows_count': int(rows), 'attempts': attempt,
                'latency_ms': int((time.time() - started) * 1000), 'error': None,
            }
        except Exception as e:
            last_error = f'{type(e).__name__}: {str(e)[:260]}'
            if attempt < attempts:
                time.sleep(RETRY_BASE_SLEEP * attempt)
    return [], {
        'source': source, 'status': 'failed', 'rows_count': 0, 'attempts': attempts,
        'latency_ms': int((time.time() - started) * 1000), 'error': last_error,
    }


def ensure_schema(cur):
    cur.execute(open(os.path.join(os.environ.get('HERMES_HOME', os.path.expanduser('~/.hermes')), 'a_share_daily_db', 'init', '004_closure_tables.sql')).read())
    cur.execute("ALTER TABLE link_scores ADD COLUMN IF NOT EXISTS llm_model text")
    cur.execute("ALTER TABLE link_scores ADD COLUMN IF NOT EXISTS llm_verdict text")
    cur.execute("ALTER TABLE link_scores ADD COLUMN IF NOT EXISTS llm_adjustment numeric DEFAULT 0")
    cur.execute("ALTER TABLE link_scores ADD COLUMN IF NOT EXISTS llm_reason text")
    cur.execute("ALTER TABLE link_scores ADD COLUMN IF NOT EXISTS llm_missing_links jsonb DEFAULT '[]'::jsonb")
    cur.execute("ALTER TABLE link_scores ADD COLUMN IF NOT EXISTS llm_reviewed_at timestamptz")
    cur.execute("ALTER TABLE link_mappings ADD COLUMN IF NOT EXISTS expected_relation text NOT NULL DEFAULT 'mixed'")
    cur.execute("CREATE TABLE IF NOT EXISTS link_hypothesis_notes (note_id text PRIMARY KEY, link_name text NOT NULL, note_date date NOT NULL, note text NOT NULL, source text NOT NULL DEFAULT 'llm', evidence jsonb NOT NULL DEFAULT '{}'::jsonb, updated_at timestamptz NOT NULL DEFAULT now())")
    cur.execute("CREATE TABLE IF NOT EXISTS morning_predictions (prediction_id text PRIMARY KEY, signal_date date NOT NULL, target_date date NOT NULL, upstream text NOT NULL, expected_sign text NOT NULL, downstream_patterns text[] NOT NULL DEFAULT '{}', basis jsonb NOT NULL DEFAULT '{}'::jsonb, prediction text NOT NULL, outcome jsonb, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now())")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_morning_predictions_target ON morning_predictions (target_date DESC, upstream)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_link_hypothesis_notes_date ON link_hypothesis_notes (note_date DESC, link_name)")
    cur.execute("""CREATE TABLE IF NOT EXISTS report_runs (
        run_id text PRIMARY KEY,
        trade_date date NOT NULL,
        report_type text NOT NULL DEFAULT 'collector',
        trigger text NOT NULL DEFAULT 'manual',
        started_at timestamptz NOT NULL DEFAULT now(),
        finished_at timestamptz,
        status text NOT NULL DEFAULT 'running',
        script_version text,
        notes text,
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS report_outputs (
        run_id text PRIMARY KEY REFERENCES report_runs(run_id) ON DELETE CASCADE,
        trade_date date NOT NULL,
        report_type text NOT NULL,
        content text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS commodity_window_moves (
        report_type text NOT NULL,
        target_date date NOT NULL,
        window_start timestamptz NOT NULL,
        window_end timestamptz NOT NULL,
        symbol text NOT NULL,
        name text NOT NULL,
        start_price numeric,
        end_price numeric,
        pct_chg numeric,
        amplitude numeric,
        high_price numeric,
        low_price numeric,
        first_ts timestamptz,
        last_ts timestamptz,
        source text NOT NULL DEFAULT 'sina_futures_minline',
        raw jsonb NOT NULL DEFAULT '{}'::jsonb,
        first_run_id text,
        last_run_id text,
        observed_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (report_type, target_date, symbol, source)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS kline_candles (
        asset_type text NOT NULL,
        code text NOT NULL,
        name text NOT NULL,
        candle_kind text NOT NULL,
        trade_date date NOT NULL,
        bucket_start timestamptz NOT NULL,
        bucket_end timestamptz NOT NULL,
        visual_ts timestamptz NOT NULL,
        open_price numeric NOT NULL,
        high_price numeric NOT NULL,
        low_price numeric NOT NULL,
        close_price numeric NOT NULL,
        volume numeric,
        synthetic boolean NOT NULL DEFAULT false,
        source text NOT NULL,
        raw jsonb NOT NULL DEFAULT '{}'::jsonb,
        first_run_id text,
        last_run_id text,
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (asset_type, code, candle_kind, visual_ts, source)
    )""")
    for ddl in [
        "ALTER TABLE market_quotes ADD COLUMN IF NOT EXISTS last_run_id text",
        "ALTER TABLE news_items ADD COLUMN IF NOT EXISTS last_run_id text",
        "ALTER TABLE candidate_links ADD COLUMN IF NOT EXISTS first_run_id text",
        "ALTER TABLE candidate_links ADD COLUMN IF NOT EXISTS last_run_id text",
        "ALTER TABLE link_validations ADD COLUMN IF NOT EXISTS source_run_id text",
        "ALTER TABLE link_validations ADD COLUMN IF NOT EXISTS validation_run_id text",
        "ALTER TABLE link_hypothesis_notes ADD COLUMN IF NOT EXISTS run_id text",
        "ALTER TABLE morning_predictions ADD COLUMN IF NOT EXISTS run_id text",
    ]:
        cur.execute(ddl)
    cur.execute("ALTER TABLE source_status ADD COLUMN IF NOT EXISTS run_id text")
    cur.execute("UPDATE source_status SET run_id='legacy_' || to_char(run_date,'YYYYMMDD') WHERE run_id IS NULL")
    cur.execute("ALTER TABLE source_status ALTER COLUMN run_id SET NOT NULL")
    cur.execute("ALTER TABLE link_scores ADD COLUMN IF NOT EXISTS run_id text")
    cur.execute("UPDATE link_scores SET run_id='legacy_' || to_char(trade_date,'YYYYMMDD') WHERE run_id IS NULL")
    cur.execute("ALTER TABLE link_scores ALTER COLUMN run_id SET NOT NULL")
    cur.execute("ALTER TABLE source_status DROP CONSTRAINT IF EXISTS source_status_pkey")
    cur.execute("ALTER TABLE source_status ADD PRIMARY KEY (run_id, source)")
    cur.execute("ALTER TABLE link_scores DROP CONSTRAINT IF EXISTS link_scores_pkey")
    cur.execute("ALTER TABLE link_scores ADD PRIMARY KEY (run_id, link_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_source_status_run ON source_status (run_id, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_link_scores_run_score ON link_scores (run_id, (score + COALESCE(llm_adjustment,0)) DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_report_runs_date_type ON report_runs (trade_date DESC, report_type, started_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_commodity_window_moves_window ON commodity_window_moves (target_date DESC, report_type, updated_at DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_kline_candles_lookup ON kline_candles (asset_type, name, visual_ts DESC)")


def start_report_run(cur, run_id=RUN_ID, report_type=RUN_TYPE, trigger=RUN_TRIGGER, notes=None):
    cur.execute("""INSERT INTO report_runs (run_id, trade_date, report_type, trigger, started_at, status, notes, metadata)
        VALUES (%s,%s,%s,%s,now(),'running',%s,%s::jsonb)
        ON CONFLICT (run_id) DO UPDATE SET trade_date=EXCLUDED.trade_date, report_type=EXCLUDED.report_type,
          trigger=EXCLUDED.trigger, started_at=COALESCE(report_runs.started_at, EXCLUDED.started_at), status='running', notes=EXCLUDED.notes""",
        (run_id, TRADE_DATE, report_type, trigger, notes, json.dumps({'window_start': REPORT_WINDOW_START.isoformat(), 'window_end': REPORT_WINDOW_END.isoformat()}, ensure_ascii=False)))


def finish_report_run(cur, run_id=RUN_ID, status='ok', notes=None):
    cur.execute("UPDATE report_runs SET finished_at=now(), status=%s, notes=COALESCE(%s, notes) WHERE run_id=%s", (status, notes, run_id))


def record_status(cur, st: dict[str, Any], run_date=TRADE_DATE, run_id=RUN_ID):
    cur.execute(
        '''INSERT INTO source_status (run_id, run_date, source, status, rows_count, attempts, started_at, finished_at, latency_ms, error, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,now() - (%s || ' milliseconds')::interval,now(),%s,%s,now())
           ON CONFLICT (run_id, source) DO UPDATE SET run_date=EXCLUDED.run_date, status=EXCLUDED.status, rows_count=EXCLUDED.rows_count,
             attempts=EXCLUDED.attempts, started_at=EXCLUDED.started_at, finished_at=EXCLUDED.finished_at,
             latency_ms=EXCLUDED.latency_ms, error=EXCLUDED.error, updated_at=now()''',
        (run_id, run_date, st['source'], st['status'], st['rows_count'], st['attempts'], st['latency_ms'], st['latency_ms'], st['error'])
    )


def _sina_futures_raw():
    codes=ALL_QUOTE_CODES
    url='https://hq.sinajs.cn/list='+','.join(codes)
    txt=get(url, {'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn'}, timeout=15, encoding='gbk')
    out=[]
    for m in re.finditer(r'var hq_str_([^=]+)="([^"]*)";', txt):
        code, raw=m.group(1), m.group(2)
        parts=raw.split(',')
        try:
            if code.startswith('nf_') and len(parts)>17:
                name=normalize_name(parts[0]); openp=float(parts[2]); high=float(parts[3]); low=float(parts[4]); last=float(parts[5]); settle=float(parts[8]); ref=float(parts[10]) if len(parts)>10 and parts[10] else settle; date=parts[17]
                # 新浪 nf_ 行情在收盘后 parts[5] 可能归零；用结算/最新有效价避免 -100% 假信号。
                if last == 0 and settle:
                    last = settle
                chg_open=(last-openp)/openp*100 if openp else None
                chg_ref=(last-ref)/ref*100 if ref else None
                amp=(high-low)/openp*100 if openp else None
                out.append({'code':code,'name':name,'close':last,'pct_chg':chg_open,'amplitude':amp,'source':'sina_futures','raw':{'open':openp,'high':high,'low':low,'ref':ref,'chg_ref':chg_ref,'date':date}})
            elif code.startswith('hf_') and len(parts)>14:
                name=parts[13]; last=float(parts[0]); high=float(parts[4]); low=float(parts[5]); openp=float(parts[2]) if parts[2] else 0; date=parts[12]
                amp=(high-low)/openp*100 if openp else None
                chg_open=(last-openp)/openp*100 if openp else None
                out.append({'code':code,'name':name,'close':last,'pct_chg':chg_open,'amplitude':amp,'source':'sina_futures','raw':{'open':openp,'high':high,'low':low,'date':date}})
        except Exception:
            continue
    return out


def _window_specs(target_date: dt.date = TRADE_DATE):
    return [
        ('morning', dt.datetime.combine(target_date - dt.timedelta(days=1), dt.time(15, 0)), dt.datetime.combine(target_date, dt.time(9, 30))),
        ('evening', dt.datetime.combine(target_date - dt.timedelta(days=1), dt.time(15, 0)), dt.datetime.combine(target_date, dt.time(15, 0))),
    ]


def _combine_trade_ts(target_date: dt.date, tm: str) -> dt.datetime:
    """Map Sina minute time strings into the user's report window convention."""
    t = dt.datetime.strptime(str(tm)[:5], '%H:%M').time()
    day = target_date - dt.timedelta(days=1) if t >= dt.time(15, 0) else target_date
    return dt.datetime.combine(day, t)


def _sina_minline_window_rows(target_date: dt.date = TRADE_DATE):
    headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn'}
    specs=_window_specs(target_date)
    results=[]
    for sym, name in ALL_MINLINE_SYMBOLS:
        try:
            url=f'https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_DATA=/InnerFuturesNewService.getMinLine?symbol={sym}'
            txt=get(url, headers=headers, timeout=12)
            body=txt.split('var _DATA=(',1)[1].rsplit(');',1)[0]
            import ast
            rows=ast.literal_eval(body)
        except Exception:
            continue
        points=[]
        for r in rows:
            if len(r) < 2:
                continue
            try:
                ts=_combine_trade_ts(target_date, str(r[0]))
                price=float(r[1])
            except Exception:
                continue
            tm=ts.time()
            active=(tm >= dt.time(20,0)) or (tm < dt.time(3,0)) or (dt.time(9,0) <= tm <= dt.time(15,0))
            if active:
                points.append((ts, price, r))
        if not points:
            continue
        for report_type, start, end in specs:
            window=[p for p in points if start <= p[0] <= end]
            if len(window) < 2:
                continue
            first=window[0][1]; last=window[-1][1]
            high=max(p[1] for p in window); low=min(p[1] for p in window)
            results.append({
                'report_type': report_type, 'target_date': target_date,
                'window_start': start, 'window_end': end,
                'symbol': sym, 'name': name,
                'start_price': first, 'end_price': last,
                'pct_chg': (last-first)/first*100 if first else None,
                'amplitude': (high-low)/first*100 if first else None,
                'high_price': high, 'low_price': low,
                'first_ts': window[0][0], 'last_ts': window[-1][0],
                'source': 'sina_futures_minline',
                'raw': {'points': len(window), 'first_time': str(window[0][0]), 'last_time': str(window[-1][0])},
            })
    return results


def _sina_index_rows():
    txt=get('https://hq.sinajs.cn/list=s_sh000001,s_sz399001,s_sz399006', {'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn'}, timeout=8, encoding='gbk')
    code_map={'s_sh000001':'000001','s_sz399001':'399001','s_sz399006':'399006'}
    results=[]
    for m in re.finditer(r'var hq_str_([^=]+)="([^"]*)";', txt):
        code=m.group(1); parts=m.group(2).split(',')
        if len(parts) >= 6:
            results.append(('index', code_map.get(code, code), parts[0], clean_num(parts[1]), clean_num(parts[3]), clean_num(parts[5])*10000 if clean_num(parts[5]) is not None else None, clean_num(parts[4]), None, None, None, 'sina_index', {'raw':m.group(2), 'amount_unit':'万元'}))
    return results


def _ak_industry_rows():
    warnings.filterwarnings('ignore')
    import akshare as ak
    results=[]
    with contextlib.redirect_stderr(io.StringIO()):
        df=ak.stock_fund_flow_industry(symbol='即时')
    for _, r in df.iterrows():
        results.append(('industry', str(r.get('行业')), str(r.get('行业')), clean_num(r.get('行业指数')), clean_num(r.get('行业-涨跌幅')), clean_num(r.get('净额')), None, None, None, None, 'akshare_fund_flow_industry', dict(r)))
    return results


def _ak_concept_rows():
    warnings.filterwarnings('ignore')
    import akshare as ak
    results=[]
    with contextlib.redirect_stderr(io.StringIO()):
        df=ak.stock_fund_flow_concept(symbol='即时')
    for _, r in df.iterrows():
        results.append(('concept', str(r.get('行业')), str(r.get('行业')), clean_num(r.get('行业指数')), clean_num(r.get('行业-涨跌幅')), clean_num(r.get('净额')), None, None, None, None, 'akshare_fund_flow_concept', dict(r)))
    return results


def _ak_sector_rows():
    warnings.filterwarnings('ignore')
    import akshare as ak
    results=[]
    with contextlib.redirect_stderr(io.StringIO()):
        df=ak.stock_sector_spot()
    for _, r in df.iterrows():
        results.append(('legacy_sector', str(r.get('label')), str(r.get('板块')), clean_num(r.get('平均价格')), clean_num(r.get('涨跌幅')), clean_num(r.get('总成交额')), clean_num(r.get('总成交量')), None, None, None, 'akshare_sector_spot', dict(r)))
    return results


def _date_yyyymmdd(day: dt.date) -> str:
    return day.strftime('%Y%m%d')


def _parse_day(value: Any) -> Optional[dt.date]:
    if value is None:
        return None
    try:
        return dt.datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except Exception:
        return None


def _history_pct(prev_close: Optional[float], close: Optional[float]) -> Optional[float]:
    if prev_close in (None, 0) or close is None:
        return None
    return (float(close) - float(prev_close)) / float(prev_close) * 100


def _ak_index_history_rows(start_date: dt.date = HISTORY_START_DATE, end_date: dt.date = TRADE_DATE):
    warnings.filterwarnings('ignore')
    import akshare as ak
    results=[]
    start=_date_yyyymmdd(start_date); end=_date_yyyymmdd(end_date)
    with eastmoney_no_proxy_env(), contextlib.redirect_stderr(io.StringIO()):
        for symbol, code, name in INDEX_HISTORY_SYMBOLS:
            try:
                df=ak.stock_zh_index_daily_em(symbol=symbol, start_date=start, end_date=end)
                fallback_source='eastmoney'
            except Exception:
                # Tencent index history is slower but has proven reachable when
                # Eastmoney push2his returns RemoteDisconnected/empty replies.
                df=ak.stock_zh_index_daily_tx(symbol=symbol, start_date=start, end_date=end)
                fallback_source='tencent'
            prev_close=None
            for _, r in df.iterrows():
                day=_parse_day(r.get('date'))
                close=clean_num(r.get('close'))
                if not day or day < start_date or day > end_date:
                    continue
                pct=_history_pct(prev_close, close)
                high=clean_num(r.get('high')); low=clean_num(r.get('low')); openp=clean_num(r.get('open'))
                amp=(high-low)/openp*100 if high is not None and low is not None and openp else None
                raw=dict(r); raw.update({'history_start': start, 'history_end': end, 'history_provider': fallback_source})
                results.append((day, 'index', code, name, close, pct, clean_num(r.get('amount')), clean_num(r.get('volume')), amp, None, None, 'akshare_index_history', raw))
                prev_close=close
    return results


def _sina_futures_history_rows(start_date: dt.date = HISTORY_START_DATE, end_date: dt.date = TRADE_DATE):
    results=[]
    headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn'}
    for symbol, code, name in FUTURES_HISTORY_SYMBOLS:
        url='https://stock2.finance.sina.com.cn/futures/api/json.php/InnerFuturesNewService.getDailyKLine?' + urllib.parse.urlencode({'symbol': symbol})
        rows=json.loads(get(url, headers=headers, timeout=20))
        prev_close=None
        for item in rows:
            day=_parse_day(item.get('d'))
            if not day or day < start_date or day > end_date:
                if day and day < start_date:
                    prev_close=clean_num(item.get('c'))
                continue
            close=clean_num(item.get('c'))
            pct=_history_pct(prev_close, close)
            high=clean_num(item.get('h')); low=clean_num(item.get('l')); openp=clean_num(item.get('o'))
            amp=(high-low)/openp*100 if high is not None and low is not None and openp else None
            results.append((day, 'commodity', code, name, close, pct, None, clean_num(item.get('v')), amp, None, None, 'sina_futures_history', item))
            prev_close=close
    return results


def _ak_board_history_rows(start_date: dt.date = HISTORY_START_DATE, end_date: dt.date = TRADE_DATE):
    warnings.filterwarnings('ignore')
    import akshare as ak
    results=[]
    errors=[]
    start=_date_yyyymmdd(start_date); end=_date_yyyymmdd(end_date)
    with eastmoney_no_proxy_env(), contextlib.redirect_stderr(io.StringIO()):
        for meta in BOARD_HISTORY_SYMBOLS:
            last_error = None
            for board_attempt in range(1, BOARD_HISTORY_RETRY_ATTEMPTS + 1):
                try:
                    if BOARD_HISTORY_PACE_SECONDS > 0:
                        time.sleep(BOARD_HISTORY_PACE_SECONDS)
                    if meta['asset_type'] == 'industry':
                        df=ak.stock_board_industry_hist_em(symbol=meta['code'], start_date=start, end_date=end, period=meta['period'], adjust='')
                    elif meta['asset_type'] == 'concept':
                        df=ak.stock_board_concept_hist_em(symbol=meta['code'], start_date=start, end_date=end, period=meta['period'], adjust='')
                    else:
                        continue
                    for _, r in df.iterrows():
                        day=_parse_day(r.get('日期'))
                        if not day or day < start_date or day > end_date:
                            continue
                        raw=dict(r); raw.update({'bk_code': meta['code'], 'history_start': start, 'history_end': end, 'board_attempt': board_attempt})
                        results.append((day, meta['asset_type'], meta['code'], meta['name'], clean_num(r.get('收盘')), clean_num(r.get('涨跌幅')), clean_num(r.get('成交额')), clean_num(r.get('成交量')), clean_num(r.get('振幅')), None, None, 'akshare_board_history', raw))
                    last_error = None
                    break
                except Exception as e:
                    last_error = f"{type(e).__name__}:{str(e)[:80]}"
                    if board_attempt < BOARD_HISTORY_RETRY_ATTEMPTS:
                        time.sleep(RETRY_BASE_SLEEP * board_attempt)
                    continue
            if last_error:
                ths_name = THS_INDUSTRY_HISTORY_FALLBACK.get(meta.get('code'))
                if ths_name:
                    try:
                        df = ak.stock_board_industry_index_ths(symbol=ths_name, start_date=start, end_date=end)
                        prev_close = None
                        made = 0
                        for _, r in df.iterrows():
                            day=_parse_day(r.get('日期'))
                            close=clean_num(r.get('收盘价'))
                            if not day or day < start_date or day > end_date:
                                continue
                            pct=_history_pct(prev_close, close)
                            high=clean_num(r.get('最高价')); low=clean_num(r.get('最低价')); openp=clean_num(r.get('开盘价'))
                            amp=(high-low)/openp*100 if high is not None and low is not None and openp else None
                            raw=dict(r); raw.update({'bk_code': meta['code'], 'history_start': start, 'history_end': end, 'history_provider': 'ths_fallback', 'ths_name': ths_name})
                            results.append((day, meta['asset_type'], meta['code'], meta['name'], close, pct, clean_num(r.get('成交额')), clean_num(r.get('成交量')), amp, None, None, 'akshare_board_history', raw))
                            prev_close=close
                            made += 1
                        if made:
                            last_error = None
                    except Exception as e:
                        last_error = f"{last_error}; ths_fallback:{type(e).__name__}:{str(e)[:80]}"
                if last_error:
                    errors.append(f"{meta.get('code')}:{last_error}")
    if not results and errors:
        raise RuntimeError('all board history fetches failed: ' + '; '.join(errors[:8]))
    return results


def fetch_history_sources(start_date: dt.date = HISTORY_START_DATE, end_date: dt.date = TRADE_DATE):
    payload={}; statuses=[]
    for source, fn in [
        ('sina_futures_history', lambda: _sina_futures_history_rows(start_date, end_date)),
        ('akshare_index_history', lambda: _ak_index_history_rows(start_date, end_date)),
        ('akshare_board_history', lambda: _ak_board_history_rows(start_date, end_date)),
    ]:
        data, st = retry_fetch(source, fn)
        payload[source]=data
        statuses.append(st)
    return payload, statuses


def _parse_east_news_time(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    text=str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return dt.datetime.strptime(text, fmt)
        except Exception:
            pass
    return None


def east_news(page_size=50, max_pages=20):
    out=[]
    for page in range(1, max_pages + 1):
        url='https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?'+urllib.parse.urlencode({
            'client':'web','biz':'web_news_col','column':'345','order':'1','needInteractData':'0','page_index':str(page),'page_size':str(page_size),'req_trace':'db-'+str(time.time())
        })
        j=json.loads(get(url, {'User-Agent':'Mozilla/5.0','Referer':'https://finance.eastmoney.com/'}))
        items=j.get('data',{}).get('list',[]) or []
        if not items:
            break
        oldest=None
        for it in items:
            pub=_parse_east_news_time(it.get('showTime'))
            if pub:
                oldest=pub if oldest is None else min(oldest, pub)
            if pub and (pub < REPORT_WINDOW_START or pub > REPORT_WINDOW_END):
                continue
            out.append(it)
        if oldest is not None and oldest < REPORT_WINDOW_START:
            break
    return out


def wscn_news(channels=('a-stock-channel','commodity-channel','oil-channel','global-channel'), limit_each=50, max_pages=20):
    headers={'User-Agent':'Mozilla/5.0','Accept':'application/json, text/plain, */*','Referer':'https://wallstreetcn.com/','Origin':'https://wallstreetcn.com'}
    out=[]; seen=set()
    start_ts=int(REPORT_WINDOW_START.timestamp()); end_ts=int(REPORT_WINDOW_END.timestamp())
    for ch in channels:
        cursor='0'
        for _ in range(max_pages):
            url='https://api-prod.wallstreetcn.com/apiv1/content/lives?'+urllib.parse.urlencode({'channel':ch,'client':'pc','cursor':cursor,'limit':str(limit_each)})
            j=json.loads(get(url, headers, timeout=15)); data=j.get('data',{}) or {}; items=data.get('items',[]) or []
            next_cursor=data.get('next_cursor')
            if not items: break
            oldest_ts=None
            for item in items:
                iid=str(item.get('id') or '')
                if not iid or iid in seen: continue
                seen.add(iid)
                ts=item.get('display_time') or 0
                if ts:
                    oldest_ts=ts if oldest_ts is None else min(oldest_ts, ts)
                if ts and (ts < start_ts or ts > end_ts):
                    continue
                out.append({'id':iid,'source':'华尔街见闻','channel':ch,'published_at':dt.datetime.fromtimestamp(ts) if ts else None,'title':(item.get('title') or '').strip() or (item.get('content_text') or '')[:40],'body':(item.get('content_text') or '').strip(),'url':f'https://wallstreetcn.com/livenews/{iid}','raw':item})
            if oldest_ts is not None and oldest_ts < start_ts:
                break
            if not next_cursor or str(next_cursor) == str(cursor):
                break
            cursor=str(next_cursor)
    return out


def fetch_all_sources():
    payload={}; statuses=[]
    for source, fn in [
        ('sina_futures', _sina_futures_raw),
        ('sina_index', _sina_index_rows),
        ('akshare_fund_flow_industry', _ak_industry_rows),
        ('akshare_fund_flow_concept', _ak_concept_rows),
        ('akshare_sector_spot', _ak_sector_rows),
        ('eastmoney_news', east_news),
        ('wscn_livenews', wscn_news),
    ]:
        data, st = retry_fetch(source, fn)
        payload[source]=data
        statuses.append(st)
    return payload, statuses


def news_tags(title, body):
    text=(title or '')+' '+(body or '')
    tags=[]
    patterns={'AI/CPO':'AI|算力|CPO|光模块|液冷|高速连接器','机器人':'机器人|减速器|丝杠|电机','玻璃/光伏':'玻璃|纯碱|光伏|玻璃基板','黑色链':'焦煤|煤炭|钢铁|螺纹|热卷|铁矿|基建','有色':'铜|铝|稀土|镍|有色|金属新材料','能源化工':'原油|油价|甲醇|化工|石化|化纤','宏观海外':'央行|逆回购|美联储|纳指|道指|海外|美元|美债'}
    for tag, pat in patterns.items():
        if re.search(pat, text, re.I): tags.append(tag)
    return tags


def upsert_quote(cur, asset_type, code, name, close, pct_chg, amount, volume, amplitude, leading_stock, leading_stock_pct, source, raw, trade_date=TRADE_DATE):
    cur.execute('''INSERT INTO market_quotes (trade_date, asset_type, code, name, close, pct_chg, amount, volume, amplitude, leading_stock, leading_stock_pct, source, raw, last_run_id, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,now())
        ON CONFLICT (trade_date, asset_type, code, source) DO UPDATE SET
        name=EXCLUDED.name, close=EXCLUDED.close, pct_chg=EXCLUDED.pct_chg, amount=EXCLUDED.amount, volume=EXCLUDED.volume,
        amplitude=EXCLUDED.amplitude, leading_stock=EXCLUDED.leading_stock, leading_stock_pct=EXCLUDED.leading_stock_pct, raw=EXCLUDED.raw, last_run_id=EXCLUDED.last_run_id, updated_at=now()''',
        (trade_date, asset_type, code, name, close, pct_chg, amount, volume, amplitude, leading_stock, leading_stock_pct, source, json.dumps(raw, ensure_ascii=False, default=str), RUN_ID))


def upsert_history_quote(cur, row):
    trade_date, asset_type, code, name, close, pct_chg, amount, volume, amplitude, leading_stock, leading_stock_pct, source, raw = row
    upsert_quote(cur, asset_type, code, name, close, pct_chg, amount, volume, amplitude, leading_stock, leading_stock_pct, source, raw, trade_date=trade_date)


def upsert_news(cur, n):
    title=n.get('title') or ''
    body=n.get('body') or n.get('summary') or ''
    item_id=n.get('id') or hashlib.sha1((n.get('source','')+title+str(n.get('published_at',''))).encode()).hexdigest()
    tags=news_tags(title, body)
    cur.execute('''INSERT INTO news_items (item_id, published_at, source, channel, title, body, url, tags, raw, last_run_id, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,now())
        ON CONFLICT (item_id) DO UPDATE SET published_at=EXCLUDED.published_at, title=EXCLUDED.title, body=EXCLUDED.body, tags=EXCLUDED.tags, raw=EXCLUDED.raw, last_run_id=EXCLUDED.last_run_id, updated_at=now()''',
        (item_id, n.get('published_at'), n.get('source'), n.get('channel'), title, body, n.get('url'), tags, json.dumps(n.get('raw', n), ensure_ascii=False, default=str), RUN_ID))


def upsert_commodity_window_move(cur, row):
    cur.execute("""INSERT INTO commodity_window_moves
        (report_type, target_date, window_start, window_end, symbol, name, start_price, end_price,
         pct_chg, amplitude, high_price, low_price, first_ts, last_ts, source, raw, first_run_id, last_run_id, observed_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,now(),now())
        ON CONFLICT (report_type, target_date, symbol, source) DO UPDATE SET
          window_start=EXCLUDED.window_start, window_end=EXCLUDED.window_end, name=EXCLUDED.name,
          start_price=EXCLUDED.start_price, end_price=EXCLUDED.end_price, pct_chg=EXCLUDED.pct_chg,
          amplitude=EXCLUDED.amplitude, high_price=EXCLUDED.high_price, low_price=EXCLUDED.low_price,
          first_ts=EXCLUDED.first_ts, last_ts=EXCLUDED.last_ts, raw=EXCLUDED.raw,
          first_run_id=COALESCE(commodity_window_moves.first_run_id, EXCLUDED.first_run_id),
          last_run_id=EXCLUDED.last_run_id, observed_at=EXCLUDED.observed_at, updated_at=now()""",
        (row['report_type'], row['target_date'], row['window_start'], row['window_end'], row['symbol'], row['name'],
         row.get('start_price'), row.get('end_price'), row.get('pct_chg'), row.get('amplitude'), row.get('high_price'), row.get('low_price'),
         row.get('first_ts'), row.get('last_ts'), row.get('source') or 'sina_futures_minline',
         json.dumps(row.get('raw') or {}, ensure_ascii=False, default=str), RUN_ID, RUN_ID))


def upsert_kline_candle(cur, row):
    cur.execute("""INSERT INTO kline_candles
        (asset_type, code, name, candle_kind, trade_date, bucket_start, bucket_end, visual_ts,
         open_price, high_price, low_price, close_price, volume, synthetic, source, raw,
         first_run_id, last_run_id, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,now())
        ON CONFLICT (asset_type, code, candle_kind, visual_ts, source) DO UPDATE SET
          name=EXCLUDED.name, trade_date=EXCLUDED.trade_date, bucket_start=EXCLUDED.bucket_start,
          bucket_end=EXCLUDED.bucket_end, open_price=EXCLUDED.open_price, high_price=EXCLUDED.high_price,
          low_price=EXCLUDED.low_price, close_price=EXCLUDED.close_price, volume=EXCLUDED.volume,
          synthetic=EXCLUDED.synthetic, raw=EXCLUDED.raw,
          first_run_id=COALESCE(kline_candles.first_run_id, EXCLUDED.first_run_id),
          last_run_id=EXCLUDED.last_run_id, updated_at=now()""",
        (row['asset_type'], row['code'], row['name'], row['candle_kind'], row['trade_date'],
         row['bucket_start'], row['bucket_end'], row['visual_ts'], row['open'], row['high'], row['low'], row['close'],
         row.get('volume'), bool(row.get('synthetic', False)), row['source'],
         json.dumps(row.get('raw') or {}, ensure_ascii=False, default=str), RUN_ID, RUN_ID))


def seed_links(cur):
    sql_path=os.path.join(os.environ.get('HERMES_HOME', os.path.expanduser('~/.hermes')), 'a_share_daily_db', 'init', '002_seed_links.sql')
    if os.path.exists(sql_path):
        cur.execute(open(sql_path).read())


def fetch_rows(cur, q, params=()):
    cur.execute(q, params)
    return cur.fetchall()


MIN_CORR_SAMPLES = int(os.getenv('A_SHARE_MIN_CORR_SAMPLES', '20'))


def calc_corr(xs, ys, min_samples=MIN_CORR_SAMPLES):
    pairs=[(float(x),float(y)) for x,y in zip(xs,ys) if x is not None and y is not None]
    if len(pairs)<min_samples: return None
    mx=sum(x for x,_ in pairs)/len(pairs); my=sum(y for _,y in pairs)/len(pairs)
    vx=sum((x-mx)**2 for x,_ in pairs); vy=sum((y-my)**2 for _,y in pairs)
    if vx<=0 or vy<=0: return None
    return sum((x-mx)*(y-my) for x,y in pairs)/(vx*vy)**0.5


def rank_values(vals):
    indexed=sorted((float(v), i) for i, v in enumerate(vals))
    ranks=[0.0]*len(indexed)
    j=0
    while j < len(indexed):
        k=j
        while k + 1 < len(indexed) and indexed[k+1][0] == indexed[j][0]:
            k += 1
        avg=(j + k + 2) / 2.0
        for _, idx in indexed[j:k+1]:
            ranks[idx]=avg
        j=k+1
    return ranks


def calc_spearman(xs, ys, min_samples=MIN_CORR_SAMPLES):
    pairs=[(float(x),float(y)) for x,y in zip(xs,ys) if x is not None and y is not None]
    if len(pairs)<min_samples: return None
    rx=rank_values([x for x,_ in pairs]); ry=rank_values([y for _,y in pairs])
    return calc_corr(rx, ry, min_samples=min_samples)


def trading_lag_date(day, lag, trading_dates):
    # T+N uses A-share trading days, not calendar days. If the commodity date is
    # not an A-share trading day, T+0 maps to the next available A-share trading day.
    import bisect
    if not trading_dates:
        return None
    pos=bisect.bisect_left(trading_dates, day)
    target=pos + int(lag)
    if 0 <= target < len(trading_dates):
        return trading_dates[target]
    return None


def relation_matches(corr, expected_relation):
    if corr is None:
        return None
    rel=(expected_relation or 'mixed').lower()
    if rel in ('same_direction', 'same', 'positive'):
        return corr >= 0
    if rel in ('opposite_direction', 'opposite', 'negative'):
        return corr <= 0
    return None


def canonical_link_key(*parts: Any) -> str:
    """Stable key for candidate links so LLM/rule wording variants merge.

    Candidate evolution should count repeated cross-day evidence for the same
    economic hypothesis, not whitespace/arrow/slash variants created by prompts
    or repeated manual runs. Keep the normalization conservative and Chinese
    domain-specific rather than trying to solve entity resolution generally.
    """
    text=' '.join(str(p or '') for p in parts)
    text=re.sub(r'\s+', '', text)
    text=text.replace('->', '→').replace('—>', '→').replace('－>', '→')
    replacements={
        '焦煤/焦炭':'煤焦', '焦煤焦炭':'煤焦', '焦煤、焦炭':'煤焦',
        '煤炭开采加工':'煤炭', '煤炭行业':'煤炭', '煤炭概念':'煤炭',
        '石油石化':'石化', '石油加工贸易':'石化',
        '锂矿概念':'锂电材料', '锂矿/锂电材料':'锂电材料', '电池材料':'锂电材料',
        '稀土永磁':'稀土磁材', '电机机器人':'电机/机器人',
        '化工化纤':'化工/化纤', '石油石化/化工成本链':'石化/化工',
    }
    for old,new in replacements.items():
        text=text.replace(old,new)
    text=re.sub(r'[，,/、|｜]+', '/', text)
    return text[:220]


def cleanup_same_day_validations(cur):
    """Remove contaminated same-day self-validations from the experience loop."""
    cur.execute("DELETE FROM link_validations WHERE signal_date = validation_date")


def experience_bonus(cur, link_id):
    row=fetch_rows(cur, 'SELECT precision_estimate, confirmed_count, failed_count, best_lag, notes FROM link_experience WHERE link_id=%s', (link_id,))
    if not row: return 0, None
    precision, confirmed, failed, best_lag, notes = row[0]
    precision=float(precision or 0)
    bonus=max(-6, min(6, (precision-0.5)*12)) if (confirmed or 0)+(failed or 0) >= 3 else 0
    return bonus, {'precision_estimate': precision, 'confirmed': confirmed, 'failed': failed, 'best_lag': best_lag, 'notes': notes}


def score_links(cur):
    mappings=fetch_rows(cur, 'SELECT link_id, link_name, upstream_names, downstream_patterns, news_patterns, lag_days, logic, direction_note, expected_relation FROM link_mappings WHERE enabled')
    trading_dates=[r[0] for r in fetch_rows(cur, """
        SELECT DISTINCT trade_date FROM market_quotes
        WHERE asset_type IN ('industry','concept','legacy_sector','index')
          AND pct_chg IS NOT NULL
        ORDER BY trade_date
    """)]
    bench_rows=fetch_rows(cur, """
        SELECT trade_date,pct_chg FROM market_quotes
        WHERE name IN ('沪深300','上证指数','中证全指','深证成指')
          AND pct_chg IS NOT NULL
        ORDER BY CASE name WHEN '沪深300' THEN 1 WHEN '中证全指' THEN 2 WHEN '上证指数' THEN 3 ELSE 4 END
    """)
    benchmark_map={}
    for bday, bpct in bench_rows:
        benchmark_map.setdefault(bday, float(bpct or 0))
    for link_id, link_name, upstream_names, downstream_patterns, news_patterns, lag_days, logic, direction_note, expected_relation in mappings:
        upstream=fetch_rows(cur, 'SELECT name,pct_chg,amplitude FROM market_quotes WHERE trade_date=%s AND name = ANY(%s)', (TRADE_DATE, upstream_names))
        if upstream:
            max_move=max(abs(float(r[1] or 0)) for r in upstream)
            max_amp=max(abs(float(r[2] or 0)) for r in upstream)
        else:
            max_move=max_amp=0
        upstream_score=min(35, max_move*12 + max_amp*4)
        downstream=[]
        for pat in downstream_patterns:
            downstream += fetch_rows(cur, "SELECT name,asset_type,pct_chg FROM market_quotes WHERE trade_date=%s AND asset_type IN ('industry','concept','legacy_sector') AND name ILIKE %s", (TRADE_DATE, f'%{pat}%'))
        seen=set(); ds=[]
        for r in downstream:
            if (r[0],r[1]) not in seen:
                seen.add((r[0],r[1])); ds.append(r)
        downstream_score=0
        if ds:
            best=max(ds, key=lambda r: abs(float(r[2] or 0)))
            downstream_score=min(30, abs(float(best[2] or 0))*8)
        news_hits=[]
        for pat in news_patterns:
            news_hits += fetch_rows(cur, "SELECT title, source FROM news_items WHERE published_at BETWEEN %s AND %s AND (title ILIKE %s OR body ILIKE %s) LIMIT 5", (REPORT_WINDOW_START, REPORT_WINDOW_END, f'%{pat}%', f'%{pat}%'))
        news_score=min(20, len({x[0] for x in news_hits})*4)
        best_corr=None; best_lag=None; corr_score=0; best_meta=None
        candidate_count=0
        if ds and trading_dates:
            for up_name in upstream_names:
                up_hist=fetch_rows(cur, "SELECT trade_date,pct_chg FROM market_quotes WHERE name=%s AND pct_chg IS NOT NULL ORDER BY trade_date", (up_name,))
                up_map={r[0]:float(r[1]) for r in up_hist if r[1] is not None}
                for dname, dtype, *_ in ds[:8]:
                    ds_hist=fetch_rows(cur, "SELECT trade_date,pct_chg FROM market_quotes WHERE name=%s AND asset_type=%s AND pct_chg IS NOT NULL ORDER BY trade_date", (dname,dtype))
                    ds_map={r[0]:float(r[1]) for r in ds_hist if r[1] is not None}
                    if not ds_map:
                        continue
                    for lag in lag_days:
                        candidate_count += 1
                        xs=[]; ys_raw=[]; ys_adj=[]; paired_dates=[]
                        for day, val in up_map.items():
                            yday=trading_lag_date(day, int(lag), trading_dates)
                            if yday in ds_map:
                                xs.append(val)
                                raw_y=ds_map[yday]
                                ys_raw.append(raw_y)
                                ys_adj.append(raw_y - benchmark_map.get(yday, 0.0))
                                paired_dates.append(str(yday))
                        c_adj=calc_corr(xs,ys_adj)
                        if c_adj is None:
                            continue
                        c_raw=calc_corr(xs,ys_raw)
                        sp_adj=calc_spearman(xs,ys_adj)
                        n=len(xs)
                        dir_ok=relation_matches(c_adj, expected_relation)
                        stability=1.0 if (sp_adj is not None and (sp_adj == 0 or c_adj == 0 or sp_adj*c_adj > 0)) else 0.85
                        dir_factor=1.08 if dir_ok is True else (0.82 if dir_ok is False else 1.0)
                        selection_strength=abs(c_adj) * stability * dir_factor * min(1.0, n / 30.0)
                        if best_meta is None or selection_strength > best_meta['selection_strength']:
                            best_corr=c_adj; best_lag=int(lag)
                            best_meta={
                                'upstream_name': up_name,
                                'downstream_name': dname,
                                'downstream_asset_type': dtype,
                                'lag': int(lag),
                                'sample_size': n,
                                'pearson_market_adjusted': c_adj,
                                'pearson_raw': c_raw,
                                'spearman_market_adjusted': sp_adj,
                                'expected_relation': expected_relation,
                                'direction_match': dir_ok,
                                'benchmark': '沪深300/中证全指/上证指数优先；缺失日期按0处理',
                                'lag_basis': 'A股交易日T+N',
                                'selection_strength': selection_strength,
                                'first_pair_date': paired_dates[0] if paired_dates else None,
                                'last_pair_date': paired_dates[-1] if paired_dates else None,
                            }
            if best_meta is not None:
                n_factor=min(1.0, best_meta['sample_size']/30.0)
                robust_factor=1.0 if best_meta.get('spearman_market_adjusted') is not None and best_meta['spearman_market_adjusted']*best_corr >= 0 else 0.85
                dir_factor=1.08 if best_meta.get('direction_match') is True else (0.82 if best_meta.get('direction_match') is False else 1.0)
                corr_score=min(15, abs(best_corr)*15*n_factor*robust_factor*dir_factor)
        exp_bonus, exp = experience_bonus(cur, link_id)
        score=upstream_score+downstream_score+news_score+corr_score+exp_bonus
        confidence='高' if score>=75 else ('中' if score>=55 else ('低' if score>=38 else '观察'))
        history_note=(f'相关性采用A股交易日滞后、市场调整后收益和Pearson/Spearman稳健性；'
                      f'样本少于{MIN_CORR_SAMPLES}组时 corr_score 为 0；相关性仅代表历史倾向，不代表因果。')
        evidence={
            'upstream':[{'name':r[0],'pct_chg':float(r[1] or 0),'amplitude':float(r[2] or 0)} for r in upstream],
            'downstream':[{'name':r[0],'asset_type':r[1],'pct_chg':float(r[2] or 0)} for r in ds[:10]],
            'news':[{'title':r[0],'source':r[1]} for r in news_hits[:10]],
            'logic':logic,
            'direction_note':direction_note,
            'expected_relation': expected_relation,
            'correlation': best_meta,
            'correlation_candidate_count': candidate_count,
            'experience': exp,
            'history_note': history_note,
        }
        cur.execute('''INSERT INTO link_scores (run_id,trade_date,link_id,link_name,score,confidence,upstream_score,downstream_score,news_score,corr_score,best_lag,best_corr,evidence,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,now())
            ON CONFLICT (run_id,link_id) DO UPDATE SET link_name=EXCLUDED.link_name, score=EXCLUDED.score, confidence=EXCLUDED.confidence,
            upstream_score=EXCLUDED.upstream_score, downstream_score=EXCLUDED.downstream_score, news_score=EXCLUDED.news_score, corr_score=EXCLUDED.corr_score,
            best_lag=EXCLUDED.best_lag, best_corr=EXCLUDED.best_corr, evidence=EXCLUDED.evidence, created_at=now()''',
            (RUN_ID, TRADE_DATE, link_id, link_name, score, confidence, upstream_score, downstream_score, news_score, corr_score, best_lag, best_corr, json.dumps(evidence, ensure_ascii=False, default=str)))

def discover_rule_candidates(cur):
    commodities=fetch_rows(cur, "SELECT name,pct_chg,amplitude FROM market_quotes WHERE trade_date=%s AND asset_type='commodity' AND (abs(COALESCE(pct_chg,0))>=0.8 OR COALESCE(amplitude,0)>=2.0)", (TRADE_DATE,))
    ds=fetch_rows(cur, "SELECT name,asset_type,pct_chg FROM market_quotes WHERE trade_date=%s AND asset_type IN ('industry','concept','legacy_sector') AND abs(COALESCE(pct_chg,0))>=1.2 ORDER BY abs(COALESCE(pct_chg,0)) DESC LIMIT 25", (TRADE_DATE,))
    news=fetch_rows(cur, "SELECT title, source, tags FROM news_items WHERE published_at BETWEEN %s AND %s LIMIT 80", (REPORT_WINDOW_START, REPORT_WINDOW_END))
    tag_text=' '.join(' '.join(r[2] or []) + ' ' + r[0] for r in news)
    keyword_map={fam: cfg['downstream'] for fam, cfg in FAMILY_KEYWORDS.items()}
    commodity_families={fam: cfg['upstream'] for fam, cfg in FAMILY_KEYWORDS.items()}
    count=0
    for up_name, up_chg, up_amp in commodities:
        for dname, dtype, dpct in ds[:12]:
            families=[fam for fam, up_pat in commodity_families.items() if re.search(up_pat, str(up_name), re.I)]
            if not families:
                continue
            hit=0
            for fam in families:
                pat=keyword_map[fam]
                # 研究对象覆盖供给端和制造端，但候选发现必须要求A股板块本身属于同一产业族。
                # 不能只因为当日全市场新闻里出现上游关键词，就把任意强势题材板块纳入候选；
                # 否则会污染出“焦煤→半导体/芯片/元件”这类噪声。
                if re.search(pat, str(dname), re.I):
                    hit += 2
            if hit <= 0:
                continue
            score=abs(float(up_chg or 0))*0.8 + abs(float(up_amp or 0))*0.4 + abs(float(dpct or 0))*0.8 + hit
            if score < 3.5:
                continue
            link_name=f'{up_name} → {dname}'
            cid=hashlib.sha1(canonical_link_key(up_name, dname).encode()).hexdigest()[:16]
            evidence={'rule_score':score,'upstream':{'name':up_name,'pct_chg':float(up_chg or 0),'amplitude':float(up_amp or 0)},'downstream':{'name':dname,'asset_type':dtype,'pct_chg':float(dpct or 0)},'news_titles':[r[0] for r in news[:8]]}
            cur.execute('''INSERT INTO candidate_links (candidate_id, first_seen_date, last_seen_date, link_name, upstream_hint, downstream_hint, evidence, llm_reason, seen_count, status, first_run_id, last_run_id, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,1,'proposed',%s,%s,now())
                ON CONFLICT (candidate_id) DO UPDATE SET last_seen_date=EXCLUDED.last_seen_date, evidence=EXCLUDED.evidence,
                  last_run_id=EXCLUDED.last_run_id,
                  seen_count=CASE WHEN candidate_links.last_run_id IS DISTINCT FROM EXCLUDED.last_run_id THEN candidate_links.seen_count+1 ELSE candidate_links.seen_count END, updated_at=now()''',
                (cid, TRADE_DATE, TRADE_DATE, link_name, up_name, dname, json.dumps(evidence, ensure_ascii=False, default=str), '规则发现：原材料大波动+受影响A股板块异动+同产业族关键词共现', RUN_ID, RUN_ID))
            count += 1
    return count


def _validation_result_from_downstream(rows):
    if not rows:
        return 'inconclusive', 0, None
    best=max(rows, key=lambda r: abs(float(r[2] or 0)))
    move=abs(float(best[2] or 0))
    if move >= 0.8:
        result='confirmed'; vscore=min(100, move*20)
    elif move < 0.3:
        result='failed'; vscore=-20
    else:
        result='inconclusive'; vscore=10
    return result, vscore, best


def refresh_link_experience(cur):
    cleanup_same_day_validations(cur)
    cur.execute("""INSERT INTO link_experience (link_id, link_name, confirmed_count, failed_count, inconclusive_count, precision_estimate, best_lag, notes, updated_at)
        SELECT link_id, max(link_name), count(*) FILTER (WHERE validation_result='confirmed'), count(*) FILTER (WHERE validation_result='failed'),
               count(*) FILTER (WHERE validation_result='inconclusive'),
               CASE WHEN (count(*) FILTER (WHERE validation_result IN ('confirmed','failed'))) >= 10
                    THEN ((count(*) FILTER (WHERE validation_result='confirmed')) + 2)::numeric / ((count(*) FILTER (WHERE validation_result IN ('confirmed','failed'))) + 4) ELSE NULL END,
               (array_agg(expected_lag ORDER BY validation_score DESC))[1],
               '自动后验验证：只统计信号日早于验证日的独立后验；同日解释不进入胜率。precision使用样本门槛与Beta(2,2)平滑。', now()
        FROM link_validations
        WHERE signal_date < validation_date
        GROUP BY link_id
        ON CONFLICT (link_id) DO UPDATE SET link_name=EXCLUDED.link_name, confirmed_count=EXCLUDED.confirmed_count,
          failed_count=EXCLUDED.failed_count, inconclusive_count=EXCLUDED.inconclusive_count, precision_estimate=EXCLUDED.precision_estimate,
          best_lag=EXCLUDED.best_lag, notes=EXCLUDED.notes, updated_at=now()""")
    cur.execute("""DELETE FROM link_experience le
                   WHERE NOT EXISTS (
                     SELECT 1 FROM link_validations lv
                     WHERE lv.link_id=le.link_id AND lv.signal_date < lv.validation_date
                   )""")


def validate_today_links(cur):
    """Do not write same-day self-validations.

    Today's after-close link_scores already condition on today's downstream A-share
    move, so using the same rows as T+0 validation creates a circular confirmed
    record. Keep this command for cron compatibility, but only clean old polluted
    rows and refresh experience from genuinely prior signals.
    """
    cleanup_same_day_validations(cur)
    refresh_link_experience(cur)
    return 0


def sync_prediction_json_to_db(cur, path=None):
    if path is None:
        path = os.path.join(os.environ.get('HERMES_HOME', os.path.expanduser('~/.hermes')), 'a_share_daily_db', 'prediction_experience.json')
    if not os.path.exists(path):
        return 0
    try:
        data=json.load(open(path, encoding='utf-8'))
    except Exception:
        return 0
    made=0
    for rec in data.get('records', []):
        if rec.get('report_type') != 'morning_preopen':
            continue
        try:
            signal=dt.date.fromisoformat(rec.get('signal_date'))
            target=dt.date.fromisoformat(rec.get('target_date'))
        except Exception:
            continue
        pid=rec.get('id') or hashlib.sha1(json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:16]
        patterns=rec.get('downstream_patterns') or []
        cur.execute("""INSERT INTO morning_predictions (prediction_id, run_id, signal_date, target_date, upstream, expected_sign, downstream_patterns, basis, prediction, outcome, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,now())
            ON CONFLICT (prediction_id) DO UPDATE SET outcome=EXCLUDED.outcome, updated_at=now()""",
            (pid, rec.get('run_id') or RUN_ID, signal, target, rec.get('upstream') or rec.get('key') or 'unknown', rec.get('expected_sign') or 'mixed', patterns, json.dumps(rec.get('basis') or {}, ensure_ascii=False, default=str), rec.get('prediction') or '', json.dumps(rec.get('outcome'), ensure_ascii=False, default=str) if rec.get('outcome') else None, rec.get('created_at') or dt.datetime.now().isoformat()))
        made += 1
    return made


def promote_candidate_links(cur):
    rows=fetch_rows(cur, """SELECT candidate_id, link_name, upstream_hint, downstream_hint, evidence, llm_reason, seen_count
                            FROM candidate_links
                            WHERE status IN ('watch','proposed')
                              AND seen_count >= 3
                              AND last_seen_date >= first_seen_date + INTERVAL '2 days'
                            ORDER BY seen_count DESC, last_seen_date DESC LIMIT 20""")
    promoted=0
    for cid, link_name, up, down, evidence, reason, seen in rows:
        link_id='cand_' + hashlib.sha1((link_name or cid).encode()).hexdigest()[:16]
        upstream=[x.strip() for x in re.split(r'[,，/、]|\s+', str(up or '')) if x.strip()][:5]
        downstream=[x.strip() for x in re.split(r'[,，/、]|\s+', str(down or '')) if x.strip()][:8]
        news_patterns=list({x for x in upstream + downstream if x})[:10]
        if not upstream or not downstream:
            continue
        cur.execute("""INSERT INTO link_mappings (link_id, link_name, upstream_names, downstream_patterns, news_patterns, lag_days, logic, direction_note, expected_relation, enabled, updated_at)
            VALUES (%s,%s,%s,%s,%s,ARRAY[0,1,3,5],%s,%s,'mixed',true,now())
            ON CONFLICT (link_id) DO UPDATE SET link_name=EXCLUDED.link_name, upstream_names=EXCLUDED.upstream_names,
              downstream_patterns=EXCLUDED.downstream_patterns, news_patterns=EXCLUDED.news_patterns, logic=EXCLUDED.logic,
              direction_note=EXCLUDED.direction_note, expected_relation=EXCLUDED.expected_relation, enabled=true, updated_at=now()""",
            (link_id, link_name, upstream, downstream, news_patterns, reason or '候选链路多次出现后自动晋升，需继续后验验证。', '候选晋升链路：方向和滞后以T+0/T+1/T+3/T+5验证结果动态修正。'))
        cur.execute("UPDATE candidate_links SET status='promoted', promoted_link_id=%s, updated_at=now() WHERE candidate_id=%s", (link_id, cid))
        promoted += 1
    return promoted


def validate_prior_links(cur):
    rows=fetch_rows(cur, '''SELECT DISTINCT ON (ls.trade_date, lm.link_id)
                              ls.trade_date, lm.link_id, ls.link_name, lm.downstream_patterns, lm.lag_days, ls.score, ls.llm_verdict, ls.llm_adjustment, ls.evidence, ls.run_id
                            FROM link_scores ls JOIN link_mappings lm ON ls.link_id=lm.link_id
                            WHERE ls.trade_date < %s AND ls.trade_date >= %s - interval '7 day'
                              AND (ls.score + COALESCE(ls.llm_adjustment,0)) >= 55
                              AND COALESCE(ls.llm_verdict,'keep') <> 'reject'
                            ORDER BY ls.trade_date, lm.link_id, ls.created_at DESC ''', (TRADE_DATE, TRADE_DATE))
    trading_dates=[r[0] for r in fetch_rows(cur, """
        SELECT DISTINCT trade_date FROM market_quotes
        WHERE asset_type IN ('industry','concept','legacy_sector','index')
          AND pct_chg IS NOT NULL
        ORDER BY trade_date
    """)]
    made=0
    for signal_date, link_id, link_name, patterns, lag_days, score, verdict, adj, evidence, source_run_id in rows:
        for lag in lag_days:
            if trading_lag_date(signal_date, int(lag), trading_dates) != TRADE_DATE:
                continue
            downstream=[]
            for pat in patterns:
                downstream += fetch_rows(cur, "SELECT name,asset_type,pct_chg FROM market_quotes WHERE trade_date=%s AND asset_type IN ('industry','concept','legacy_sector') AND name ILIKE %s", (TRADE_DATE, f'%{pat}%'))
            if not downstream:
                result='inconclusive'; vscore=0
            else:
                best=max(downstream, key=lambda r: abs(float(r[2] or 0)))
                move=abs(float(best[2] or 0))
                if move >= 0.8:
                    result='confirmed'; vscore=min(100, move*20)
                elif move < 0.3:
                    result='failed'; vscore=-20
                else:
                    result='inconclusive'; vscore=10
            ev={'prior_evidence': evidence, 'current_downstream':[{'name':r[0],'asset_type':r[1],'pct_chg':float(r[2] or 0)} for r in downstream[:8]]}
            cur.execute('''INSERT INTO link_validations (signal_date, validation_date, link_id, link_name, expected_lag, prior_verdict, prior_score, validation_result, validation_score, evidence, source_run_id, validation_run_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                ON CONFLICT (signal_date, validation_date, link_id, expected_lag) DO UPDATE SET prior_verdict=EXCLUDED.prior_verdict, prior_score=EXCLUDED.prior_score,
                  validation_result=EXCLUDED.validation_result, validation_score=EXCLUDED.validation_score, evidence=EXCLUDED.evidence, source_run_id=EXCLUDED.source_run_id, validation_run_id=EXCLUDED.validation_run_id, created_at=now()''',
                (signal_date, TRADE_DATE, link_id, link_name, int(lag), verdict, float(score)+float(adj or 0), result, vscore, json.dumps(ev, ensure_ascii=False, default=str), source_run_id, RUN_ID))
            made += 1
    refresh_link_experience(cur)
    return made


def _calendar_4h_slot(ts: dt.datetime) -> tuple[dt.datetime, dt.datetime, dt.datetime]:
    start = ts.replace(hour=(ts.hour // 4) * 4, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(hours=4)
    return start, end, start + dt.timedelta(hours=2)


def _sina_futures_kline_candles(target_date: dt.date = TRADE_DATE):
    headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn'}
    rows=[]
    # The HTML phase view is focused around the evening report window. Sina minline is recent-only,
    # so collect all rows it exposes and map them into real calendar 4H candles.
    for sym, name in ALL_MINLINE_SYMBOLS:
        if normalize_name(name) not in KLINE_COMMODITY_NAMES:
            continue
        try:
            url=f'https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_DATA=/InnerFuturesNewService.getMinLine?symbol={sym}'
            txt=get(url, headers=headers, timeout=12)
            body=txt.split('var _DATA=(',1)[1].rsplit(');',1)[0]
            import ast
            raw_rows=ast.literal_eval(body)
        except Exception:
            continue
        buckets={}
        for r in raw_rows:
            if len(r) < 2:
                continue
            try:
                ts=_combine_trade_ts(target_date, str(r[0]))
                price=float(r[1])
            except Exception:
                continue
            if not (target_date - dt.timedelta(days=2) <= ts.date() <= target_date + dt.timedelta(days=1)):
                continue
            bstart, bend, vts = _calendar_4h_slot(ts)
            buckets.setdefault((bstart,bend,vts), []).append((ts, price, r))
        for (bstart,bend,vts), pts in buckets.items():
            pts.sort(key=lambda x: x[0])
            prices=[p[1] for p in pts]
            rows.append({'asset_type':'commodity','code':sym,'name':name,'candle_kind':'calendar_4h','trade_date':vts.date(),
                'bucket_start':bstart,'bucket_end':bend,'visual_ts':vts,'open':prices[0],'high':max(prices),'low':min(prices),'close':prices[-1],
                'volume':None,'synthetic':False,'source':'sina_futures_minline_4h','raw':{'points':len(pts),'first_ts':pts[0][0].isoformat(),'last_ts':pts[-1][0].isoformat()}})
    return rows


def _board_daily_kline_candles(cur, start_date: dt.date = HISTORY_START_DATE, end_date: dt.date = TRADE_DATE):
    cur.execute("""
      SELECT DISTINCT ON (trade_date, asset_type, code, source) trade_date, asset_type, code, name, close, pct_chg, raw, source
      FROM market_quotes
      WHERE trade_date BETWEEN %s AND %s AND source='akshare_board_history'
      ORDER BY trade_date, asset_type, code, source, updated_at DESC
    """, (start_date, end_date))
    out=[]
    for trade_date, asset_type, code, name, close, pct_chg, raw, source in cur.fetchall():
        parsed=parse_ohlc_from_raw(raw or {}, float(close) if close is not None else None)
        if not parsed:
            continue
        o,h,l,c=parsed
        bstart=dt.datetime.combine(trade_date, dt.time(12,0)); bend=dt.datetime.combine(trade_date, dt.time(16,0)); vts=dt.datetime.combine(trade_date, dt.time(14,0))
        out.append({'asset_type':'board','code':code,'name':name,'candle_kind':'a_share_day_session','trade_date':trade_date,
            'bucket_start':bstart,'bucket_end':bend,'visual_ts':vts,'open':o,'high':h,'low':l,'close':c,
            'volume':(raw or {}).get('成交量'),'synthetic':False,'source':'akshare_board_history_day_kline','raw':raw or {}})
    return out


def refresh_kline_candles(cur, start_date: dt.date = HISTORY_START_DATE, end_date: dt.date = TRADE_DATE):
    count=0
    for row in _board_daily_kline_candles(cur, start_date, end_date):
        upsert_kline_candle(cur, row); count += 1
    for row in _sina_futures_kline_candles(TRADE_DATE):
        upsert_kline_candle(cur, row); count += 1
    return count


def collect_history(start_date: dt.date = HISTORY_START_DATE, end_date: dt.date = TRADE_DATE):
    payload, statuses = fetch_history_sources(start_date, end_date)
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_schema(cur)
            for st in statuses:
                record_status(cur, st)
            valid_boards=[f"{m['asset_type']}:{m['code']}" for m in BOARD_HISTORY_SYMBOLS]
            if valid_boards:
                cur.execute("""
                    DELETE FROM market_quotes
                    WHERE source='akshare_board_history'
                      AND trade_date BETWEEN %s AND %s
                      AND NOT ((asset_type || ':' || code) = ANY(%s))
                """, (start_date, end_date, valid_boards))
            for key in ('sina_futures_history', 'akshare_index_history', 'akshare_board_history'):
                for row in payload.get(key) or []:
                    upsert_history_quote(cur, row)
        conn.commit()
    return statuses


def collect_current_data(include_history=True):
    """Data collection only: fetch external interfaces, upsert/de-duplicate into DB, no scoring/report analysis."""
    statuses=[]
    if include_history:
        statuses.extend(collect_history())
    payload, current_statuses = fetch_all_sources()
    statuses.extend(current_statuses)
    minline_rows, minline_status = retry_fetch('sina_futures_minline_windows', lambda: _sina_minline_window_rows(TRADE_DATE))
    statuses.append(minline_status)
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_schema(cur)
            start_report_run(cur, report_type='collector')
            for st in statuses:
                record_status(cur, st)
            for q in payload.get('sina_futures') or []:
                upsert_quote(cur, 'commodity', q['code'], q['name'], q['close'], q['pct_chg'], None, None, q['amplitude'], None, None, q['source'], q['raw'])
            for row in (payload.get('sina_index') or []) + (payload.get('akshare_fund_flow_industry') or []) + (payload.get('akshare_fund_flow_concept') or []) + (payload.get('akshare_sector_spot') or []):
                upsert_quote(cur, *row)
            for it in payload.get('eastmoney_news') or []:
                t=it.get('showTime')
                pub=None
                try: pub=dt.datetime.strptime(t, '%Y-%m-%d %H:%M:%S') if t else None
                except Exception: pass
                upsert_news(cur, {'id':'east-'+str(it.get('code') or hashlib.sha1((it.get('title','')+str(t)).encode()).hexdigest()), 'published_at':pub, 'source':'东方财富', 'channel':it.get('columnName'), 'title':it.get('title') or '', 'body':it.get('summary') or '', 'url':it.get('url'), 'raw':it})
            for it in payload.get('wscn_livenews') or []:
                upsert_news(cur, it)
            for row in minline_rows or []:
                upsert_commodity_window_move(cur, row)
            kline_count = refresh_kline_candles(cur, HISTORY_START_DATE, TRADE_DATE)
            record_status(cur, {'source':'kline_candles', 'status':'ok' if kline_count else 'failed', 'rows_count':kline_count, 'attempts':1, 'latency_ms':0, 'error':None if kline_count else 'no kline rows generated'})
            finish_report_run(cur, status='ok')
        conn.commit()
    return statuses


def analyze_from_db():
    """Analysis only: read DB rows inside report windows and write scores/candidates; no external fetch."""
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_schema(cur)
            start_report_run(cur, report_type='analysis')
            seed_links(cur)
            sync_prediction_json_to_db(cur)
            validations=validate_prior_links(cur)
            score_links(cur)
            new_candidates=discover_rule_candidates(cur)
            finish_report_run(cur, status='ok')
        conn.commit()
    return validations, new_candidates


def collect_and_score():
    statuses = collect_current_data(include_history=True)
    validations, new_candidates = analyze_from_db()
    return statuses, validations, new_candidates


def summarize():
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM market_quotes WHERE trade_date=%s', (TRADE_DATE,)); quote_count=cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM news_items WHERE published_at BETWEEN %s AND %s", (REPORT_WINDOW_START, REPORT_WINDOW_END)); news_count=cur.fetchone()[0]
            cur.execute('SELECT link_name, score, confidence FROM link_scores WHERE run_id=%s ORDER BY score DESC LIMIT 5', (RUN_ID,)); links=cur.fetchall()
            cur.execute('SELECT source,status,rows_count,attempts,latency_ms,error FROM source_status WHERE run_id=%s ORDER BY source', (RUN_ID,)); sources=cur.fetchall()
            cur.execute('SELECT count(*) FROM candidate_links WHERE last_seen_date=%s', (TRADE_DATE,)); cand=cur.fetchone()[0]
            cur.execute('SELECT count(*) FROM link_validations WHERE validation_date=%s', (TRADE_DATE,)); vals=cur.fetchone()[0]
    return {'ok':True,'run_id':RUN_ID,'trade_date':str(TRADE_DATE),'quotes':quote_count,'recent_news':news_count,'top_links':links,'source_status':sources,'candidate_links_today':cand,'validations_today':vals}


def test_interfaces(include_history=False, start_date: dt.date = HISTORY_START_DATE, end_date: dt.date = TRADE_DATE):
    if include_history:
        payload, statuses = fetch_history_sources(start_date, end_date)
    else:
        payload, statuses = fetch_all_sources()
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            ensure_schema(cur)
            for st in statuses:
                record_status(cur, st)
        conn.commit()
    return {'ok': all(s['status']=='ok' for s in statuses), 'run_id': RUN_ID, 'trade_date': str(TRADE_DATE), 'interfaces': statuses}


def _cli_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, '%Y%m%d').date()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--test-interfaces', action='store_true', help='test all primary current-day data interfaces')
    ap.add_argument('--test-history', action='store_true', help='test historical data interfaces only')
    ap.add_argument('--backfill-history', action='store_true', help='fetch and persist historical quote data only')
    ap.add_argument('--collect-only', action='store_true', help='fetch external interfaces and upsert DB rows only; no scoring/analysis')
    ap.add_argument('--analyze-only', action='store_true', help='read existing DB rows and score/discover links only; no external fetch')
    ap.add_argument('--no-history', action='store_true', help='with --collect-only, skip historical backfill collection')
    ap.add_argument('--history-days', type=int, default=HISTORY_DAYS, help='history window days for --test-history/--backfill-history')
    ap.add_argument('--start-date', help='history start date, YYYYMMDD; overrides --history-days')
    ap.add_argument('--end-date', help='history end date, YYYYMMDD; default today')
    ap.add_argument('--validate-today', action='store_true', help='write T+0 validations for today after LLM audit')
    ap.add_argument('--promote-candidates', action='store_true', help='promote repeated candidate links into link_mappings')
    args=ap.parse_args()
    end_date=_cli_date(args.end_date) if args.end_date else TRADE_DATE
    start_date=_cli_date(args.start_date) if args.start_date else end_date - dt.timedelta(days=args.history_days)
    if args.validate_today or args.promote_candidates:
        with psycopg.connect(DB_DSN) as conn:
            with conn.cursor() as cur:
                ensure_schema(cur)
                start_report_run(cur, report_type='evolve' if (args.validate_today or args.promote_candidates) else RUN_TYPE)
                sync_prediction_json_to_db(cur)
                made = validate_today_links(cur) if args.validate_today else 0
                promoted = promote_candidate_links(cur) if args.promote_candidates else 0
                finish_report_run(cur, status='ok')
            conn.commit()
        print(json.dumps({'ok': True, 'run_id': RUN_ID, 'trade_date': str(TRADE_DATE), 'validations_today': made, 'promoted_candidates': promoted}, ensure_ascii=False, default=str))
        return 0
    if args.test_history:
        print(json.dumps(test_interfaces(include_history=True, start_date=start_date, end_date=end_date), ensure_ascii=False, default=str))
        return 0
    if args.backfill_history:
        statuses=collect_history(start_date, end_date)
        print(json.dumps({'ok': all(s['status']=='ok' for s in statuses), 'run_id': RUN_ID, 'trade_date': str(TRADE_DATE), 'history_start': str(start_date), 'history_end': str(end_date), 'interfaces': statuses}, ensure_ascii=False, default=str))
        return 0 if all(s['status']=='ok' for s in statuses) else 2
    if args.collect_only:
        statuses=collect_current_data(include_history=not args.no_history)
        print(json.dumps({'ok': all(s['status']=='ok' for s in statuses), 'run_id': RUN_ID, 'trade_date': str(TRADE_DATE), 'mode': 'collect_only', 'interfaces': statuses}, ensure_ascii=False, default=str))
        return 0 if all(s['status']=='ok' for s in statuses) else 2
    if args.analyze_only:
        validations, candidates = analyze_from_db()
        out=summarize()
        out.update({'mode': 'analyze_only', 'validations_made': validations, 'candidate_links_new_or_updated': candidates})
        print(json.dumps(out, ensure_ascii=False, default=str))
        return 0
    if args.test_interfaces:
        print(json.dumps(test_interfaces(), ensure_ascii=False, default=str))
        return 0
    statuses, validations, candidates = collect_and_score()
    out=summarize()
    out['collection_status']=statuses
    out['validations_made']=validations
    out['rule_candidates_made']=candidates
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0 if all(s['status']=='ok' for s in statuses) else 2


if __name__ == '__main__':
    raise SystemExit(main())
