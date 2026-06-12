#!/usr/bin/env python3
"""Generate an HTML phase-view K-line dashboard for A-share raw-material chain reports."""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg

SCRIPT_DIR = Path(os.environ.get('HERMES_HOME', str(Path.home() / '.hermes'))) / 'scripts'
if str(SCRIPT_DIR) not in os.sys.path:
    os.sys.path.insert(0, str(SCRIPT_DIR))

from a_share_commodity_universe import DOMESTIC, INTERNATIONAL, normalize_name  # noqa: E402

DB_DSN = os.getenv('A_SHARE_DAILY_DSN') or 'postgresql://' + 'a_share' + ':' + (os.getenv('A_SHARE_DB_PASSWORD') or 'a_share_daily_local') + '@127.0.0.1:15432/a_share_daily'
OUT = Path(os.getenv('A_SHARE_KLINE_HTML_OUT', str(Path.home() / 'a_share_chain_phase_view.html')))
TRADE_DATE = dt.date.fromisoformat(os.getenv('A_SHARE_KLINE_DATE', '2026-06-10'))
# Keep the visual focused around the report window; a full week makes 4H/daily candles look too sparse.
START_DATE = TRADE_DATE - dt.timedelta(days=2)
END_DATE = TRADE_DATE + dt.timedelta(days=1)
REPORT_START = dt.datetime.combine(TRADE_DATE - dt.timedelta(days=1), dt.time(15, 0))
REPORT_END = dt.datetime.combine(TRADE_DATE, dt.time(15, 0))

COMM_META = {normalize_name(x['name']): x for x in (DOMESTIC + INTERNATIONAL)}
SYMBOL_BY_NAME = {normalize_name(x['name']): x.get('symbol') for x in DOMESTIC if x.get('symbol')}
CODE_BY_NAME = {normalize_name(x['name']): x.get('code') for x in (DOMESTIC + INTERNATIONAL)}

# Extra options for each reported chain; used only when data exists.
CHAIN_EXTRAS = {
    '黑色链 → 基建/机械/汽车/家电': {
        'commodities': ['焦煤连续', '焦炭连续', '铁矿石连续', '螺纹钢连续', '热轧卷板连续'],
        'boards': ['煤炭行业', '钢铁', '工程机械', '建筑材料', '家电零部件Ⅱ'],
    },
    '铜铝 → 电力设备/机器人/汽车零部件': {
        'commodities': ['铜连续', '铝连续', '伦铜', '伦铝', '伦镍', '沪锌连续', '镍连续'],
        'boards': ['电机Ⅱ', '电力设备', '电网设备', '机器人', '汽车零部件', '小金属', '稀土'],
    },
    '原油化工 → 消费制造/包装/化纤/电子化学品': {
        'commodities': ['上海原油连续', '纽约原油', '甲醇连续', '燃料油连续', 'PTA连续', 'PVC连续'],
        'boards': ['石油石化', '化学原料', '化学纤维', '煤化工', '包装印刷'],
    },
}


def rows_dict(cur, q: str, params=()):
    cur.execute(q, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def parse_ohlc_from_raw(raw: dict[str, Any], close_val: float | None):
    if not isinstance(raw, dict):
        raw = {}
    def pick(*keys):
        for k in keys:
            if k in raw and raw[k] not in (None, ''):
                try:
                    return float(raw[k])
                except Exception:
                    pass
        return None
    o = pick('开盘', '开盘价', 'open')
    h = pick('最高', '最高价', 'high')
    l = pick('最低', '最低价', 'low')
    c = pick('收盘', '收盘价', 'close')
    if c is None and close_val is not None:
        c = float(close_val)
    if o is None and c is not None:
        # If only close is available, derive a neutral candle rather than inventing intraday range.
        o = c
    if h is None:
        h = max(x for x in [o, c] if x is not None) if (o is not None and c is not None) else c
    if l is None:
        l = min(x for x in [o, c] if x is not None) if (o is not None and c is not None) else c
    if None in (o, h, l, c):
        return None
    return o, h, l, c


def _fill_calendar_4h(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    by_ts = {dt.datetime.fromisoformat(r['t']): r for r in rows}
    start_dt = dt.datetime.combine(START_DATE, dt.time(0, 0))
    end_dt = dt.datetime.combine(END_DATE + dt.timedelta(days=1), dt.time(0, 0))
    out=[]; last_close=None; slot_start=start_dt
    while slot_start < end_dt:
        visual_ts = slot_start + dt.timedelta(hours=2)
        row = by_ts.get(visual_ts)
        if row:
            out.append(row); last_close=float(row['c'])
        elif last_close is not None:
            out.append({'t': visual_ts.isoformat(), 'bucketEnd': (slot_start + dt.timedelta(hours=4)).isoformat(),
                        'o': last_close, 'h': last_close, 'l': last_close, 'c': last_close,
                        'v': 0.0, 'synthetic': True, 'source': 'calendar_4h_carry_forward'})
        slot_start += dt.timedelta(hours=4)
    return out


def fetch_kline_candles(conn, asset_type: str, name: str) -> list[dict[str, Any]]:
    q = """
      SELECT visual_ts, bucket_end, open_price, high_price, low_price, close_price, volume, synthetic, source
      FROM kline_candles
      WHERE asset_type=%s AND name=%s AND visual_ts >= %s AND visual_ts < %s
      ORDER BY visual_ts
    """
    start_dt = dt.datetime.combine(START_DATE, dt.time(0, 0))
    end_dt = dt.datetime.combine(END_DATE + dt.timedelta(days=1), dt.time(0, 0))
    try:
        with conn.cursor() as cur:
            cur.execute(q, (asset_type, name, start_dt, end_dt))
            rows = cur.fetchall()
    except Exception:
        rows = []
    out=[]
    for visual_ts, bucket_end, o, h, l, c, v, synthetic, source in rows:
        out.append({'t': visual_ts.replace(tzinfo=None).isoformat(),
                    'bucketEnd': bucket_end.replace(tzinfo=None).isoformat() if bucket_end else None,
                    'o': float(o), 'h': float(h), 'l': float(l), 'c': float(c),
                    'v': float(v) if v is not None else None,
                    'synthetic': bool(synthetic), 'source': source})
    return _fill_calendar_4h(out)


def fetch_board_series(conn, name: str) -> list[dict[str, Any]]:
    db_rows = fetch_kline_candles(conn, 'board', name)
    if db_rows:
        return db_rows
    # Prefer historical OHLC board rows. For visual phase comparison, expand A-share board
    # data onto the SAME fixed calendar 4H grid as futures: six slots per day. Candles
    # are drawn at the slot midpoint. The real A-share day-session candle is placed at
    # 14:00, the midpoint of the 12:00-16:00 slot containing the 09:30-15:00 session; other slots carry
    # forward the last close as flat gray candles so the two panels line up visually.
    # Keep one consistent source per option. Mixing Eastmoney/THS board indices with legacy-sector average-price rows creates nonsense scales.
    with conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM market_quotes
               WHERE trade_date BETWEEN %s AND %s AND name=%s AND source='akshare_board_history'""",
            (START_DATE, END_DATE, name),
        )
        has_history = (cur.fetchone()[0] or 0) > 0
    source_filter = "AND source='akshare_board_history'" if has_history else "AND source <> 'akshare_board_history'"
    q = f"""
      SELECT DISTINCT ON (trade_date) trade_date, asset_type, code, name, close, pct_chg, amplitude, raw, source
      FROM market_quotes
      WHERE trade_date BETWEEN %s AND %s AND name=%s {source_filter}
      ORDER BY trade_date,
        CASE WHEN raw ? '开盘' OR raw ? '开盘价' THEN 0 ELSE 1 END,
        updated_at DESC
    """
    daily = {}
    with conn.cursor() as cur:
        for r in rows_dict(cur, q, (START_DATE, END_DATE, name)):
            parsed = parse_ohlc_from_raw(r.get('raw') or {}, float(r['close']) if r.get('close') is not None else None)
            if not parsed:
                continue
            o, h, l, c = parsed
            day = r['trade_date']
            # Calendar 4H bucket 12:00-16:00 contains the A-share 09:30-15:00 session.
            daily[dt.datetime.combine(day, dt.time(16, 0))] = {
                'o': o, 'h': h, 'l': l, 'c': c, 'v': None,
                'pct': float(r['pct_chg'] or 0), 'source': r.get('source'),
                'synthetic': False,
            }
    out = []
    last_close = None
    start_dt = dt.datetime.combine(START_DATE, dt.time(0, 0))
    end_dt = dt.datetime.combine(END_DATE + dt.timedelta(days=1), dt.time(0, 0))
    slot_start = start_dt
    while slot_start < end_dt:
        slot_end = slot_start + dt.timedelta(hours=4)
        visual_ts = slot_start + dt.timedelta(hours=2)
        real = daily.get(slot_end)
        if real:
            row = {'t': visual_ts.isoformat(), 'bucketEnd': slot_end.isoformat(), **real}
            last_close = float(real['c'])
        elif last_close is not None:
            row = {
                't': visual_ts.isoformat(), 'bucketEnd': slot_end.isoformat(), 'o': float(last_close), 'h': float(last_close),
                'l': float(last_close), 'c': float(last_close), 'v': 0.0, 'pct': 0.0,
                'source': 'calendar_4h_carry_forward', 'synthetic': True,
            }
        else:
            slot_start = slot_end
            continue
        out.append(row)
        slot_start = slot_end
    return out


def fetch_futures_series(conn, name: str) -> list[dict[str, Any]]:
    db_rows = fetch_kline_candles(conn, 'commodity', name)
    if db_rows:
        return db_rows
    norm = normalize_name(name)
    symbol = SYMBOL_BY_NAME.get(norm)
    if not symbol:
        # Overseas hf_ rows have no domestic minute source in AKShare futures_zh_minute_sina here.
        return []
    try:
        import akshare as ak
        # Use 15m data, then place it into fixed calendar 4H buckets. The previous
        # implementation grouped every four trading-hour bars, which produced only
        # 2-3 candles/day and made the chart look sparse. For this phase view the
        # x-axis is calendar time, so a day should have six 4H slots. Empty slots
        # are carried forward as flat, low-opacity candles.
        df = ak.futures_zh_minute_sina(symbol=symbol, period='15')
    except Exception:
        return []
    if df is None or df.empty:
        return []
    df = df.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    start_dt = dt.datetime.combine(START_DATE, dt.time(0, 0))
    end_dt = dt.datetime.combine(END_DATE + dt.timedelta(days=1), dt.time(0, 0))
    df = df[(df['datetime'] >= start_dt) & (df['datetime'] < end_dt)].sort_values('datetime')
    if df.empty:
        return []
    out = []
    last_close = None
    slot_start = start_dt
    while slot_start < end_dt:
        slot_end = slot_start + dt.timedelta(hours=4)
        mask = (df['datetime'] > slot_start) & (df['datetime'] <= slot_end)
        part = df[mask]
        if not part.empty:
            o = float(part.iloc[0]['open'])
            h = float(part['high'].astype(float).max())
            l = float(part['low'].astype(float).min())
            c = float(part.iloc[-1]['close'])
            v = float(part['volume'].astype(float).sum()) if 'volume' in part.columns else None
            last_close = c
            synthetic = False
        elif last_close is not None:
            o = h = l = c = float(last_close)
            v = 0.0
            synthetic = True
        else:
            slot_start = slot_end
            continue
        visual_ts = slot_start + dt.timedelta(hours=2)
        out.append({'t': visual_ts.isoformat(), 'bucketEnd': slot_end.isoformat(), 'o': o, 'h': h, 'l': l, 'c': c, 'v': v,
                    'synthetic': synthetic,
                    'source': 'akshare.futures_zh_minute_sina:15m→calendar_4h'})
        slot_start = slot_end
    return out


def window_pct(series: list[dict[str, Any]], start=REPORT_START, end=REPORT_END):
    pts = [(dt.datetime.fromisoformat(x['t']), x) for x in series]
    pts = [(t, x) for t, x in pts if start <= t <= end]
    if len(pts) < 1:
        return None
    first = pts[0][1]['o']
    last = pts[-1][1]['c']
    if not first:
        return None
    return (last - first) / first * 100


def series_option(name: str, kind: str, data: list[dict[str, Any]], is_default=False):
    return {
        'name': name,
        'kind': kind,
        'isDefault': is_default,
        'data': data,
        'windowPct': window_pct(data),
        'count': len(data),
    }


def build_chains():
    chains = []
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
              SELECT run_id, link_name, score, confidence, best_lag, best_corr, llm_verdict, llm_adjustment, llm_reason, evidence
              FROM link_scores
              WHERE trade_date=%s
                AND (score + COALESCE(llm_adjustment,0)) >= 55
                AND COALESCE(llm_verdict,'keep') <> 'reject'
              ORDER BY (score + COALESCE(llm_adjustment,0)) DESC
            """, (TRADE_DATE,))
            link_rows = cur.fetchall()
    for run_id, link_name, score, confidence, lag, corr, verdict, adj, reason, evidence in link_rows:
        ev = evidence or {}
        ups = ev.get('upstream') or []
        ds = ev.get('downstream') or []
        if not ups or not ds:
            continue
        # Only keep links actually shown in yesterday's propagation section.
        if link_name not in CHAIN_EXTRAS:
            continue
        corr_meta = ev.get('correlation') or {}
        default_comm = corr_meta.get('upstream_name') or max(ups, key=lambda x: abs(float(x.get('pct_chg') or 0))).get('name')
        default_board = corr_meta.get('downstream_name') or ds[0].get('name')
        comm_names = []
        for n in [default_comm] + [x.get('name') for x in ups] + CHAIN_EXTRAS.get(link_name, {}).get('commodities', []):
            if n and normalize_name(n) not in [normalize_name(x) for x in comm_names]:
                comm_names.append(normalize_name(n))
        board_names = []
        for n in [default_board] + [x.get('name') for x in ds] + CHAIN_EXTRAS.get(link_name, {}).get('boards', []):
            if n and n not in board_names:
                board_names.append(n)
        with psycopg.connect(DB_DSN) as conn:
            comm_opts = []
            for n in comm_names:
                data = fetch_futures_series(conn, n)
                if data:
                    comm_opts.append(series_option(n, 'commodity', data, normalize_name(n) == normalize_name(default_comm)))
            board_opts = []
            for n in board_names:
                data = fetch_board_series(conn, n)
                if data:
                    board_opts.append(series_option(n, 'board', data, n == default_board))
        if not comm_opts or not board_opts:
            continue
        if not any(x['isDefault'] for x in comm_opts):
            comm_opts[0]['isDefault'] = True
        if not any(x['isDefault'] for x in board_opts):
            board_opts[0]['isDefault'] = True
        history = '样本不足'
        if corr is not None:
            sp = corr_meta.get('spearman_market_adjusted')
            history = f"T+{lag} Pearson {float(corr):+.2f}" + (f" / Spearman {float(sp):+.2f}" if sp is not None else '') + (f" / n={corr_meta.get('sample_size')}" if corr_meta.get('sample_size') else '')
        chains.append({
            'id': re.sub(r'\W+', '_', link_name),
            'linkName': link_name,
            'confidence': confidence,
            'pathway': ' / '.join([confidence + '置信' if confidence else '观察', '相位观察']),
            'score': float(score) + float(adj or 0),
            'history': history,
            'reason': reason or '',
            'commodities': comm_opts,
            'boards': board_opts,
        })
    return chains


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>A股原材料—产业链相位K线观察</title>
<style>
  :root { --bg:#07111f; --card:#0d1b2e; --card2:#0f2238; --text:#e5eefb; --muted:#8ba3bf; --grid:#21334b; --red:#ef4444; --green:#22c55e; --gold:#f59e0b; --cyan:#22d3ee; --purple:#a78bfa; --orange:#fb923c; --yellow:#fde047; }
  *{box-sizing:border-box} body{margin:0;background:radial-gradient(circle at top,#10213a 0,#07111f 45%,#030712 100%);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,"PingFang SC","Microsoft YaHei",sans-serif;}
  header{padding:28px 34px 16px;border-bottom:1px solid #1d314a} h1{margin:0;font-size:26px;letter-spacing:.5px} .subtitle{margin-top:8px;color:var(--muted);font-size:14px}.wrap{padding:22px 26px 42px;max-width:1460px;margin:auto}.note{background:rgba(34,211,238,.08);border:1px solid rgba(34,211,238,.22);border-radius:12px;padding:12px 14px;margin-bottom:18px;color:#c7e7f6;font-size:13px;line-height:1.7}.chain{background:linear-gradient(180deg,rgba(15,34,56,.98),rgba(8,19,34,.98));border:1px solid #1f3655;border-radius:16px;margin:18px 0 28px;box-shadow:0 18px 44px rgba(0,0,0,.28);overflow:hidden}.chain-head{padding:18px 20px 10px;border-bottom:1px solid #203653}.chain-title{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.chain-title h2{margin:0;font-size:19px}.badge{font-size:12px;border:1px solid rgba(245,158,11,.45);color:#ffd58a;background:rgba(245,158,11,.12);padding:3px 8px;border-radius:999px}.meta{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:8px;margin-top:12px}.metric{background:rgba(3,7,18,.35);border:1px solid #1b314c;border-radius:10px;padding:9px 10px;font-size:12px;color:var(--muted)}.metric b{display:block;color:var(--text);font-size:14px;margin-top:3px}.controls{display:grid;grid-template-columns:1fr 1fr 1fr 1.2fr;gap:12px;padding:14px 20px;border-bottom:1px solid #203653}.control label{display:block;color:var(--muted);font-size:12px;margin-bottom:6px} select,input[type=range]{width:100%}select{background:#081525;color:var(--text);border:1px solid #29425f;border-radius:9px;padding:9px 10px}.phaseBox{display:flex;align-items:center;gap:12px}.phaseBox input{accent-color:#22d3ee}.phaseText{min-width:92px;color:#c7e7f6;font-weight:700}.charts{padding:14px 18px 20px}.chart-title{display:flex;justify-content:space-between;align-items:end;color:var(--muted);font-size:12px;margin:6px 4px}.chart-title b{font-size:15px;color:var(--text)}svg{width:100%;height:330px;display:block;background:#07111f;border:1px solid #1c314c;border-radius:12px}.tooltip{position:fixed;display:none;pointer-events:none;background:#020617;border:1px solid #334155;color:#e2e8f0;padding:8px 10px;border-radius:8px;font-size:12px;z-index:99;box-shadow:0 8px 20px rgba(0,0,0,.45)}.foot{color:var(--muted);font-size:12px;text-align:center;margin-top:20px}
</style>
</head>
<body>
<header><h1>A股原材料—产业链相位 K线观察</h1><div class="subtitle">基于 {{date}} 晚报正式强链路；上下图统一使用日历4小时网格。</div></header>
<div class="wrap">
  <div class="note">每张卡片选择一个原材料和一个A股板块；拖动“ A股相位差 ”只移动下方A股K线。阴影表示A股盘内/盘外。</div>
  <div id="app"></div>
  <div class="foot">说明：相位移动只用于视觉观察，不改变原始行情数据。历史相关仅为倾向，不构成因果证明或投资建议。</div>
</div>
<div id="tooltip" class="tooltip"></div>
<script>
const CHAINS = {{chains_json}};
const REPORT_START = new Date('{{report_start}}').getTime();
const REPORT_END = new Date('{{report_end}}').getTime();
const DAY = 24*3600*1000, HOUR = 3600*1000;
function fmtPct(x){ return x===null || x===undefined ? 'NA' : (x>=0?'+':'') + x.toFixed(2) + '%'; }
function fmtTime(t){ const d=new Date(t); return `${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`; }
function axisLabel(t){ const d=new Date(t), hh=String(d.getHours()).padStart(2,'0'); return d.getHours()===0 ? `${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}` : `${hh}:00`; }
function axisTicks(xd, tickH){ const step=(tickH||4)*HOUR; let t=Math.ceil(xd[0]/step)*step, out=[]; for(; t<=xd[1]; t+=step) out.push(t); return out; }
function pickDefault(arr){ return Math.max(0, arr.findIndex(x=>x.isDefault)); }
function xDomainForSeries(comm, board, phaseH){
  // Focus on the selected pair around the report window. This avoids a week-long calendar axis
  // that spreads a handful of 4H/daily candles too far apart.
  let xs=[REPORT_START, REPORT_END];
  comm.data.forEach(d=>xs.push(new Date(d.t).getTime()));
  board.data.forEach(d=>xs.push(new Date(d.t).getTime()+phaseH*HOUR));
  const hardStart=REPORT_START-30*HOUR, hardEnd=REPORT_END+18*HOUR;
  let lo=Math.max(Math.min(...xs)-4*HOUR, hardStart);
  let hi=Math.min(Math.max(...xs)+4*HOUR, hardEnd);
  if(hi-lo < 30*HOUR){ const mid=(lo+hi)/2; lo=mid-15*HOUR; hi=mid+15*HOUR; }
  return [lo,hi];
}
function yDomain(data){ let vals=[]; data.forEach(d=>{vals.push(d.o,d.h,d.l,d.c)}); let lo=Math.min(...vals), hi=Math.max(...vals); if(!isFinite(lo)||!isFinite(hi)||lo===hi){lo=0;hi=1} let pad=(hi-lo)*0.12; return [lo-pad,hi+pad]; }
function renderApp(){
  const app=document.getElementById('app'); app.innerHTML='';
  CHAINS.forEach((chain, idx)=>{
    const ci=pickDefault(chain.commodities), bi=pickDefault(chain.boards);
    const div=document.createElement('section'); div.className='chain'; div.id='chain_'+idx;
    div.innerHTML=`<div class="chain-head"><div class="chain-title"><h2>${chain.linkName}</h2><span class="badge">${chain.confidence}置信</span><span class="badge">评分 ${chain.score.toFixed(1)}</span></div><div class="meta"><div class="metric">历史倾向<b>${chain.history}</b></div><div class="metric">原材料窗口涨跌<b class="commPct"></b></div><div class="metric">A股窗口涨跌<b class="boardPct"></b></div><div class="metric">当前相位<b class="phaseMetric">0h</b></div></div></div>
      <div class="controls"><div class="control"><label>原材料</label><select class="commSel">${chain.commodities.map((s,i)=>`<option value="${i}" ${i===ci?'selected':''}>${s.name}${s.isDefault?'（默认）':''}｜${s.count}根</option>`).join('')}</select></div><div class="control"><label>A股板块</label><select class="boardSel">${chain.boards.map((s,i)=>`<option value="${i}" ${i===bi?'selected':''}>${s.name}${s.isDefault?'（默认）':''}｜${s.count}根</option>`).join('')}</select></div><div class="control"><label>横轴粒度</label><select class="tickSel"><option value="4" selected>4小时｜细</option><option value="8">8小时｜中</option><option value="12">12小时｜疏</option></select></div><div class="control"><label>A股相位差</label><div class="phaseBox"><input class="phase" type="range" min="-24" max="24" step="1" value="0"><span class="phaseText">0h</span></div></div></div>
      <div class="charts"><div class="chart-title"><b class="commTitle"></b><span></span></div><svg class="commSvg"></svg><div class="chart-title"><b class="boardTitle"></b><span></span></div><svg class="boardSvg"></svg></div>`;
    app.appendChild(div);
    const update=()=>renderChain(div, chain);
    div.querySelector('.commSel').addEventListener('change', update); div.querySelector('.boardSel').addEventListener('change', update); div.querySelector('.tickSel').addEventListener('change', update); div.querySelector('.phase').addEventListener('input', update);
    update();
  });
}
function renderChain(root, chain){
  const comm=chain.commodities[+root.querySelector('.commSel').value], board=chain.boards[+root.querySelector('.boardSel').value], phase=+root.querySelector('.phase').value, tickH=+root.querySelector('.tickSel').value;
  root.querySelector('.phaseText').textContent=(phase>=0?'+':'')+phase+'h'; root.querySelector('.phaseMetric').textContent=(phase>=0?'+':'')+phase+'h';
  root.querySelector('.commPct').textContent=fmtPct(comm.windowPct); root.querySelector('.boardPct').textContent=fmtPct(board.windowPct);
  root.querySelector('.commTitle').textContent=`原材料：${comm.name}｜4H K线`;
  root.querySelector('.boardTitle').textContent=`A股板块：${board.name}｜4H K线（相位 ${(phase>=0?'+':'')+phase}h）`;
  const xd=xDomainForSeries(comm, board, phase);
  drawChart(root.querySelector('.commSvg'), comm.data, xd, yDomain(comm.data), 0, 'commodity', tickH);
  drawChart(root.querySelector('.boardSvg'), board.data, xd, yDomain(board.data), phase, 'board', tickH);
}
function svgEl(n, attrs){ const e=document.createElementNS('http://www.w3.org/2000/svg', n); for(const k in attrs)e.setAttribute(k, attrs[k]); return e; }
function drawChart(svg, data, xd, yd, phaseH, type, tickH){
  const W=svg.clientWidth||1200,H=330,m={l:58,r:24,t:22,b:42}; svg.setAttribute('viewBox',`0 0 ${W} ${H}`); svg.innerHTML='';
  const x=t=>m.l+(t-xd[0])/(xd[1]-xd[0])*(W-m.l-m.r); const y=v=>H-m.b-(v-yd[0])/(yd[1]-yd[0])*(H-m.t-m.b);
  for(let i=0;i<=4;i++){let yy=m.t+i*(H-m.t-m.b)/4; svg.appendChild(svgEl('line',{x1:m.l,y1:yy,x2:W-m.r,y2:yy,stroke:'#1d314a'})); let val=yd[1]-(yd[1]-yd[0])*i/4; svg.appendChild(svgText(8,yy+4,val.toFixed(2),'#8ba3bf'))}
  axisTicks(xd, tickH).forEach(tt=>{let xx=x(tt); svg.appendChild(svgEl('line',{x1:xx,y1:m.t,x2:xx,y2:H-m.b,stroke:'#14263c'})); svg.appendChild(svgText(xx-18,H-16,axisLabel(tt),'#8ba3bf'))});
  drawSessions(svg,x,m,W,H,type);
  const shifted=data.map(d=>({...d, _t:new Date(d.t).getTime()+phaseH*HOUR}));
  const xs=shifted.map(d=>x(d._t)).sort((a,b)=>a-b);
  let minGap=Infinity; for(let i=1;i<xs.length;i++){ if(xs[i]-xs[i-1]>1) minGap=Math.min(minGap,xs[i]-xs[i-1]); }
  const bw=Math.max(8, Math.min(34, isFinite(minGap) ? minGap*0.45 : 24));
  shifted.forEach(d=>{ const xx=x(d._t), yo=y(d.o), yc=y(d.c), yh=y(d.h), yl=y(d.l); if(xx<m.l-bw || xx>W-m.r+bw) return; const up=d.c>=d.o, col=d.synthetic?'#64748b':(up?'#ef4444':'#22c55e'); const fill=d.synthetic?'rgba(100,116,139,.18)':(up?'rgba(239,68,68,.42)':'rgba(34,197,94,.42)'); svg.appendChild(svgEl('line',{x1:xx,y1:yh,x2:xx,y2:yl,stroke:col,'stroke-width':d.synthetic?1:1.4,'stroke-dasharray':d.synthetic?'2 2':''})); svg.appendChild(svgEl('rect',{x:xx-bw/2,y:Math.min(yo,yc),width:bw,height:Math.max(2,Math.abs(yc-yo)),fill,stroke:col,'stroke-width':d.synthetic?0.9:1.2,rx:1})); const hit=svgEl('rect',{x:xx-bw,y:m.t,width:bw*2,height:H-m.t-m.b,fill:'transparent'}); hit.addEventListener('mousemove',ev=>showTip(ev, d)); hit.addEventListener('mouseleave',hideTip); svg.appendChild(hit); });
  svg.appendChild(svgEl('rect',{x:m.l,y:m.t,width:W-m.l-m.r,height:H-m.t-m.b,fill:'none',stroke:'#334b6a'}));
}
function svgText(x,y,text,fill){ const t=svgEl('text',{x,y,fill,'font-size':11}); t.textContent=text; return t; }
function addV(svg,xpos,H,color,label){ svg.appendChild(svgEl('line',{x1:xpos,y1:22,x2:xpos,y2:H-42,stroke:color,class:'session'})); }
function addBand(svg,x1,x2,H,fill,label,color){
  const left=Math.min(x1,x2), width=Math.abs(x2-x1);
  if(width<=0) return;
  svg.appendChild(svgEl('rect',{x:left,y:22,width,height:H-64,fill}));
}
function drawSessions(svg,x,m,W,H,type){
  // Use the same A-share trading-window convention on BOTH panels, matching the morning/evening report logic:
  // A股09:30-15:00 is intraday; everything else is outside-A-share-session.
  addV(svg,x(REPORT_START),H,'#fde047','窗口起点'); addV(svg,x(REPORT_END),H,'#fde047','窗口终点');
  const start=new Date(REPORT_START-2*DAY), end=new Date(REPORT_END+2*DAY);
  for(let d=new Date(start.getFullYear(),start.getMonth(),start.getDate()); d<=end; d=new Date(d.getTime()+DAY)){
    const prevClose = new Date(d.getFullYear(),d.getMonth(),d.getDate()-1,15,0).getTime();
    const open = new Date(d.getFullYear(),d.getMonth(),d.getDate(),9,30).getTime();
    const close = new Date(d.getFullYear(),d.getMonth(),d.getDate(),15,0).getTime();
    const nextOpen = new Date(d.getFullYear(),d.getMonth(),d.getDate()+1,9,30).getTime();
    addBand(svg, x(prevClose), x(open), H, 'rgba(167,139,250,.095)', 'A股盘外', '#c4b5fd');
    addBand(svg, x(open), x(close), H, 'rgba(34,211,238,.085)', 'A股盘内', '#67e8f9');
    addBand(svg, x(close), x(nextOpen), H, 'rgba(167,139,250,.095)', 'A股盘外', '#c4b5fd');
  }
}
function showTip(ev,d){ const tip=document.getElementById('tooltip'); tip.style.display='block'; tip.style.left=(ev.clientX+12)+'px'; tip.style.top=(ev.clientY+12)+'px'; tip.innerHTML=`${fmtTime(new Date(d._t||d.t).getTime())}${d.synthetic?'<br><span style="color:#94a3b8">无交易，沿用上一价</span>':''}<br>O ${d.o.toFixed(2)} H ${d.h.toFixed(2)} L ${d.l.toFixed(2)} C ${d.c.toFixed(2)}`; }
function hideTip(){ document.getElementById('tooltip').style.display='none'; }
renderApp();
</script>
</body></html>'''


def main():
    chains = build_chains()
    if not chains:
        raise SystemExit('No chains with data generated')
    content = HTML_TEMPLATE.replace('{{date}}', str(TRADE_DATE)) \
        .replace('{{chains_json}}', json.dumps(chains, ensure_ascii=False)) \
        .replace('{{report_start}}', REPORT_START.isoformat()) \
        .replace('{{report_end}}', REPORT_END.isoformat())
    OUT.write_text(content, encoding='utf-8')
    print(json.dumps({'ok': True, 'out': str(OUT), 'chains': len(chains), 'chain_names': [c['linkName'] for c in chains]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
