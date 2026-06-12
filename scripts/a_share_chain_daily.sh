#!/usr/bin/env bash
set -euo pipefail
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PYTHON="$HERMES_HOME/venvs/a_share_daily/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON="python3"; fi
DB_DIR="$HERMES_HOME/a_share_daily_db"
DB_COLLECTOR="$HERMES_HOME/scripts/a_share_market_db.py"
LLM_AUDITOR="$HERMES_HOME/scripts/a_share_llm_audit.py"
: "${A_SHARE_RUN_ID:=evening_$(date +%Y%m%d_%H%M%S)_$$}"
export A_SHARE_RUN_ID
export A_SHARE_RUN_TYPE="${A_SHARE_RUN_TYPE:-evening}"
export A_SHARE_RUN_TRIGGER="${A_SHARE_RUN_TRIGGER:-cron}"
if command -v docker >/dev/null 2>&1 && [ -f "$DB_DIR/docker-compose.yml" ] && [ -f "$DB_COLLECTOR" ]; then
  docker compose -f "$DB_DIR/docker-compose.yml" up -d >/dev/null 2>&1 || true
  "$PYTHON" "$DB_COLLECTOR" --collect-only >/tmp/a_share_market_db_collect.log 2>&1 || true
  "$PYTHON" "$DB_COLLECTOR" --analyze-only >/tmp/a_share_market_db_analyze.log 2>&1 || true
  if [ -f "$LLM_AUDITOR" ] && command -v hermes >/dev/null 2>&1; then
    "$PYTHON" "$LLM_AUDITOR" >/tmp/a_share_llm_audit.log 2>&1 || true
  fi
  # LLM审核完成后，写入今日T+0后验验证，并将多次出现的候选链路半自动晋升为正式映射。
  "$PYTHON" "$DB_COLLECTOR" --validate-today --promote-candidates >/tmp/a_share_market_db_evolve.log 2>&1 || true
fi
"$PYTHON" - <<'PY'
import json, urllib.request, urllib.parse, uuid, re, datetime, time, warnings, contextlib, io, ast, os, hashlib, sys
SCRIPT_DIR=os.path.join(os.environ.get('HERMES_HOME', os.path.expanduser('~/.hermes')), 'scripts')
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from a_share_commodity_universe import ALL_QUOTE_CODES, ALL_MINLINE_SYMBOLS, CORE_NAMES, EXPANDED_NAMES, FAMILY_KEYWORDS, family_for, impact_for, is_core_name, is_expanded_name, normalize_name
from a_share_commodity_signal import attach_history_percentiles, commodity_signal_score, material_move as commodity_material_move, rank_commodity_moves

WSCN_CRAWLER = os.path.expanduser(os.getenv('WSCN_CRAWLER', '~/Downloads/wallstreet_news_crawler.py'))


def get(url, headers=None, timeout=12, encoding='utf-8'):
    headers = headers or {'User-Agent':'Mozilla/5.0'}
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout).read().decode(encoding, errors='replace')


def east_indices():
    """A股三大指数：优先使用新浪轻量行情接口，避免东方财富 push2 与 AKShare 代理不稳定。"""
    try:
        txt=get('https://hq.sinajs.cn/list=s_sh000001,s_sz399001,s_sz399006', {'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn'}, timeout=8, encoding='gbk')
        code_map={'s_sh000001':'000001','s_sz399001':'399001','s_sz399006':'399006'}
        rows=[]
        for m in re.finditer(r'var hq_str_([^=]+)="([^"]*)";', txt):
            code=m.group(1); parts=m.group(2).split(',')
            if len(parts) >= 6:
                rows.append({'f12':code_map.get(code, code), 'f14':parts[0], 'f2':float(parts[1]), 'f3':float(parts[3]), 'f4':float(parts[2]), 'f6':float(parts[5])*10000})
        return rows
    except Exception:
        url='https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&fields=f12,f14,f2,f3,f4,f6&secids=1.000001,0.399001,0.399006'
        try:
            j=json.loads(get(url))
            return j.get('data',{}).get('diff',[]) or []
        except Exception:
            return []


def parse_east_news_time(value):
    if not value:
        return None
    text=str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.datetime.strptime(text, fmt)
        except Exception:
            pass
    return None


def east_news(page_size=50, max_pages=20, window_start=None, window_end=None):
    # 分页抓取到报告窗口起点，避免只取首页少量新闻导致昨日15:00—今日15:00事件遗漏。
    start=window_start or globals().get('report_window_start')
    end=window_end or globals().get('report_window_end')
    out=[]
    for page in range(1, max_pages + 1):
        url='https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?'+urllib.parse.urlencode({
            'client':'web','biz':'web_news_col','column':'345','order':'1','needInteractData':'0',
            'page_index':str(page),'page_size':str(page_size),'req_trace':str(uuid.uuid4())
        })
        try:
            j=json.loads(get(url, {'User-Agent':'Mozilla/5.0','Referer':'https://finance.eastmoney.com/'}))
            items=j.get('data',{}).get('list',[]) or []
        except Exception:
            items=[]
        if not items:
            break
        oldest=None
        for it in items:
            pub=parse_east_news_time(it.get('showTime'))
            if pub:
                oldest=pub if oldest is None else min(oldest, pub)
            if start and end and pub and (pub < start or pub > end):
                continue
            out.append(it)
        if start and oldest is not None and oldest < start:
            break
    return out


def wallstreet_livenews(channels=('a-stock-channel','commodity-channel','oil-channel','global-channel'), limit_each=50, max_pages=20, window_start=None):
    # 根据用户提供的 ~/Downloads/wallstreet_news_crawler.py 中的华尔街见闻快讯接口实现；
    # 分页抓取到报告窗口起点，避免只取最新20条导致夜盘/盘前重大事件遗漏。
    headers={
        'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36',
        'Accept':'application/json, text/plain, */*',
        'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer':'https://wallstreetcn.com/',
        'Origin':'https://wallstreetcn.com',
    }
    out=[]; seen=set()
    start_ts=int((window_start or globals().get('report_window_start') or (datetime.datetime.now()-datetime.timedelta(days=1))).timestamp())
    end_ts=int((globals().get('report_window_end') or datetime.datetime.now()).timestamp())
    for ch in channels:
        cursor='0'
        for _ in range(max_pages):
            url='https://api-prod.wallstreetcn.com/apiv1/content/lives?'+urllib.parse.urlencode({
                'channel':ch, 'client':'pc', 'cursor':cursor, 'limit':str(limit_each)
            })
            try:
                j=json.loads(get(url, headers, timeout=15))
                data=j.get('data',{}) or {}
                items=data.get('items',[]) or []
                next_cursor=data.get('next_cursor')
            except Exception:
                items=[]; next_cursor=None
            if not items:
                break
            oldest_ts=None
            for item in items:
                iid=item.get('id')
                if iid in seen: continue
                seen.add(iid)
                ts=item.get('display_time') or 0
                if ts:
                    oldest_ts=ts if oldest_ts is None else min(oldest_ts, ts)
                if ts and (ts < start_ts or ts > end_ts):
                    continue
                title=(item.get('title') or '').strip()
                text=(item.get('content_text') or '').strip()
                if not (title or text): continue
                # 快讯正文末尾常带来源括号，保留为 source。
                source=None
                m=re.search(r'[（(]([^()（）]{1,10})[）)]\s*$', text)
                if m:
                    source=m.group(1); text=text[:m.start()].strip()
                out.append({
                    'source_platform':'华尔街见闻快讯', 'channel':ch, 'id':iid,
                    'time':time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts)) if ts else '',
                    'score':int(item.get('score') or 0), 'title':title, 'text':text,
                    'source':source, 'url':f'https://wallstreetcn.com/livenews/{iid}'
                })
            if oldest_ts is not None and oldest_ts < start_ts:
                break
            if not next_cursor or str(next_cursor) == str(cursor):
                break
            cursor=str(next_cursor)
    out.sort(key=lambda x: (x.get('score',0), x.get('time','')), reverse=True)
    return out


def sina_futures():
    codes=ALL_QUOTE_CODES
    url='https://hq.sinajs.cn/list='+','.join(codes)
    try:
        txt=urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn'}), timeout=12).read().decode('gbk','replace')
    except Exception:
        return []
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
                out.append({'code':code,'name':name,'last':last,'open':openp,'ref':ref,'chg_open':chg_open,'chg_ref':chg_ref,'amp':amp,'high':high,'low':low,'date':date})
            elif code.startswith('hf_') and len(parts)>14:
                name=parts[13]; last=float(parts[0]); high=float(parts[4]); low=float(parts[5]); openp=float(parts[2]) if parts[2] else 0; date=parts[12]
                amp=(high-low)/openp*100 if openp else None
                chg_open=(last-openp)/openp*100 if openp else None
                out.append({'code':code,'name':name,'last':last,'open':openp,'chg_open':chg_open,'chg_ref':None,'amp':amp,'high':high,'low':low,'date':date})
        except Exception:
            continue
    return out


def sina_night_moves():
    """真实上一夜盘分钟数据：新浪 InnerFuturesNewService.getMinLine。
    期货夜盘按交易日归属，接口返回顺序通常为 21:00-夜盘收盘、09:00-15:00。
    """
    symbols=ALL_MINLINE_SYMBOLS
    out=[]
    for sym,name in symbols:
        try:
            url=f'https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_DATA=/InnerFuturesNewService.getMinLine?symbol={sym}'
            txt=urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn'}), timeout=8).read().decode('utf-8','replace')
            body=txt.split('var _DATA=(',1)[1].rsplit(');',1)[0]
            rows=ast.literal_eval(body)
            night=[]
            trade_date=None
            for r in rows:
                if len(r) < 2:
                    continue
                tm=str(r[0])
                if len(r) > 6 and r[6]:
                    trade_date=r[6]
                # 上一夜盘：20:00之后到次日03:00前。日盘09:00后不纳入。
                if tm >= '20:00' or tm < '03:00':
                    try:
                        night.append((tm, float(r[1])))
                    except Exception:
                        pass
                elif night:
                    break
            if len(night) >= 2:
                first=night[0][1]; last=night[-1][1]
                high=max(x[1] for x in night); low=min(x[1] for x in night)
                out.append({'symbol':sym,'name':name,'night_open':first,'night_close':last,'night_chg':(last-first)/first*100 if first else None,'night_amp':(high-low)/first*100 if first else None,'night_start':night[0][0],'night_end':night[-1][0],'date':trade_date,'source':'sina_futures_minline'})
        except Exception:
            continue
    return out


def db_fetch_context():
    """Analysis-only data source: read de-duplicated collector rows from PostgreSQL."""
    try:
        import psycopg
        import a_share_market_db as market_db
        dsn=os.getenv('A_SHARE_DAILY_DSN') or market_db.DB_DSN
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT code, name, close, pct_chg, amount
                    FROM market_quotes
                    WHERE trade_date=%s AND asset_type='index'
                    ORDER BY CASE name WHEN '上证指数' THEN 1 WHEN '深证成指' THEN 2 WHEN '创业板指' THEN 3 ELSE 4 END
                    LIMIT 10
                """, (trade_day,))
                idx=[{'f12':r[0], 'f14':r[1], 'f2':float(r[2] or 0), 'f3':float(r[3] or 0), 'f4':None, 'f6':float(r[4] or 0) if r[4] is not None else None} for r in cur.fetchall()]
                cur.execute("""
                    SELECT code, name, close, pct_chg, amplitude, raw
                    FROM market_quotes
                    WHERE trade_date=%s AND asset_type='commodity'
                    ORDER BY updated_at DESC
                """, (trade_day,))
                fut=[]
                seen=set()
                for code,name,close,chg,amp,raw in cur.fetchall():
                    if name in seen:
                        continue
                    seen.add(name)
                    raw=raw or {}
                    fut.append({'code':code, 'name':name, 'last':float(close or 0), 'open':raw.get('open'), 'chg_open':float(chg or 0), 'amp':float(amp or 0), 'high':raw.get('high'), 'low':raw.get('low'), 'date':str(trade_day), 'source':'db:market_quotes'})
                cur.execute("""
                    SELECT symbol, name, start_price, end_price, pct_chg, amplitude, high_price, low_price, first_ts, last_ts, target_date
                    FROM commodity_window_moves
                    WHERE target_date=%s AND report_type='evening'
                    ORDER BY updated_at DESC
                """, (trade_day,))
                night=[]
                for sym,name,startp,endp,chg,amp,highp,lowp,first_ts,last_ts,tdate in cur.fetchall():
                    night.append({'symbol':sym,'name':name,'night_open':float(startp or 0),'night_close':float(endp or 0),'night_chg':float(chg or 0),'night_amp':float(amp or 0),'high_price':float(highp or 0) if highp is not None else None,'low_price':float(lowp or 0) if lowp is not None else None,'night_start':first_ts.strftime('%m-%d %H:%M') if first_ts else '', 'night_end':last_ts.strftime('%m-%d %H:%M') if last_ts else '', 'date':str(tdate), 'source':'db:commodity_window_moves'})
                cur.execute("""
                    SELECT source, channel, title, body, published_at
                    FROM news_items
                    WHERE published_at BETWEEN %s AND %s
                    ORDER BY published_at DESC NULLS LAST
                    LIMIT 160
                """, (report_window_start, report_window_end))
                news=[]
                for src,ch,title,body,pub in cur.fetchall():
                    news.append({'src':src or '', 'title':title or '', 'text':(body or '').replace(chr(10),''), 'media':ch or '', 'time':pub.strftime('%Y-%m-%d %H:%M:%S') if pub else ''})
                return idx, fut, night, news
    except Exception:
        return [], [], [], []


def db_window_history(report_type='evening'):
    try:
        import psycopg
        import a_share_market_db as market_db
        dsn=os.getenv('A_SHARE_DAILY_DSN') or market_db.DB_DSN
        out={}
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT name, pct_chg
                    FROM commodity_window_moves
                    WHERE report_type=%s AND target_date < %s AND pct_chg IS NOT NULL
                    ORDER BY target_date DESC
                    LIMIT 4000
                """, (report_type, trade_day))
                for name, chg in cur.fetchall():
                    out.setdefault(name, []).append(abs(float(chg)))
        return out
    except Exception:
        return {}


def pct(x):
    return 'NA' if x is None else f'{x:+.2f}%'

def fmt_num(x):
    try: return f'{float(x):.2f}'
    except Exception: return str(x)

def idx_line(d):
    amt=''
    try:
        if d.get('f6') is not None: amt=f"，成交额约{float(d['f6'])/1e8:.0f}亿元"
    except Exception: pass
    delta=f"，涨跌额{fmt_num(d.get('f4'))}" if d.get('f4') is not None else ''
    return f"{d.get('f14')} {fmt_num(d.get('f2'))}，涨跌幅{pct(float(d.get('f3')) if d.get('f3') is not None else None)}{delta}{amt}"

now=datetime.datetime.now(); date=now.strftime('%Y-%m-%d')
trade_day=now.date()
planned_close_report=datetime.datetime.combine(trade_day, datetime.time(15,0))
close_late_minutes=max(0, int((now-planned_close_report).total_seconds()//60))
close_schedule_note=f"提示：本次晚报生成较15:00目标延迟{close_late_minutes}分钟。" if close_late_minutes > 15 else ""
report_window_start=datetime.datetime.combine(trade_day-datetime.timedelta(days=1), datetime.time(15,0))
report_window_end=datetime.datetime.combine(trade_day, datetime.time(15,0))
report_window_label=f"{report_window_start.strftime('%m-%d %H:%M')}—{report_window_end.strftime('%m-%d %H:%M')}"
# 口径：A股09:30-15:00为日盘；除此之外均归为夜盘/盘前盘后。
indices, futs, night_moves, db_news_rows = db_fetch_context()
night_moves=attach_history_percentiles(night_moves, db_window_history('evening'))
east=[]; wscn=[]; byname={f['name']:f for f in futs}; night_byname={f['name']:f for f in night_moves}

kw=re.compile('A股|收盘|收跌|收涨|板块|机器人|算力|光模块|CPO|玻璃|有色|钢铁|煤炭|化工|石化|原油|光伏|新能源|汽车|半导体|地产|基建|制造|期货|商品|夜盘|涨停|跌停|锂|稀土|铜|铝|锌|铅|镍|锡|氧化铝|工业硅|黄金|白银|焦煤|焦炭|铁矿|纯碱|燃料油|沥青|LPG|甲醇|PTA|PX|乙二醇|苯乙烯|PVC|聚丙烯|塑料|短纤|尿素|烧碱|橡胶|豆粕|菜粕|豆油|棕榈油|棉花|白糖|生猪|鸡蛋')

def parse_news_time(t):
    if not t:
        return None
    t=str(t).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S','%Y-%m-%d %H:%M','%m-%d %H:%M'):
        try:
            dt=datetime.datetime.strptime(t, fmt)
            if fmt.startswith('%m-'):
                dt=dt.replace(year=trade_day.year)
            return dt
        except Exception:
            pass
    return None

def in_report_window(t):
    dt=parse_news_time(t)
    return dt is None or (report_window_start <= dt <= report_window_end)

raw_news=[]
for it in db_news_rows:
    title=(it.get('title') or '').strip(); text=(it.get('text') or '').strip(); t=it.get('time','')
    if title and kw.search(title+text) and in_report_window(t):
        raw_news.append(it)
for it in east:
    title=(it.get('title') or '').strip(); summary=(it.get('summary') or '').strip(); media=it.get('mediaName',''); t=it.get('showTime','')
    if title and kw.search(title+summary) and in_report_window(t):
        raw_news.append({'src':'东方财富','title':title,'text':summary.replace(chr(10),''),'media':media,'time':t})
for it in wscn:
    title=(it.get('title') or '').strip(); text=(it.get('text') or '').strip(); t=it.get('time',''); ch=it.get('channel','')
    if kw.search(title+text) and in_report_window(t):
        raw_news.append({'src':'华尔街见闻','title':title or text[:36],'text':text.replace(chr(10),''),'media':ch,'time':t})
# 确保华尔街见闻真实进入事件池。
if not any(n['src']=='华尔街见闻' for n in raw_news):
    for it in wscn[:2]:
        title=(it.get('title') or '').strip(); text=(it.get('text') or '').strip(); t=it.get('time',''); ch=it.get('channel','')
        if (title or text) and in_report_window(t):
            raw_news.append({'src':'华尔街见闻','title':title or text[:36],'text':text.replace(chr(10),''),'media':ch,'time':t})


def pct(x):
    return 'NA' if x is None else f'{x:+.2f}%'

def fmt_num(x):
    try: return f'{float(x):.2f}'
    except Exception: return str(x)

def idx_line(d):
    amt=''
    try:
        if d.get('f6') is not None: amt=f"，成交额约{float(d['f6'])/1e8:.0f}亿元"
    except Exception: pass
    delta=f"，涨跌额{fmt_num(d.get('f4'))}" if d.get('f4') is not None else ''
    return f"{d.get('f14')} {fmt_num(d.get('f2'))}，涨跌幅{pct(float(d.get('f3')) if d.get('f3') is not None else None)}{delta}{amt}"

def idx_brief_lines():
    if not indices:
        return ['指数接口暂未返回可靠数据；以新闻收评为辅助参考。']
    lines=[]
    for d in indices:
        amt=''
        try:
            if d.get('f6') is not None: amt=f"，成交额约{float(d['f6'])/1e8:.0f}亿元"
        except Exception: pass
        delta=f"，涨跌额{fmt_num(d.get('f4'))}" if d.get('f4') is not None else ''
        lines.append(f"- {d.get('f14')}：{fmt_num(d.get('f2'))}，{pct(float(d.get('f3')) if d.get('f3') is not None else None)}{delta}{amt}")
    return lines

def fline(names):
    rows=[]
    for n in names:
        f=byname.get(n)
        if f:
            rows.append(f"{n}{fmt_num(f.get('last'))}（较开盘{pct(f.get('chg_open'))}，振幅{pct(f.get('amp'))}）")
    return '、'.join(rows) if rows else '暂无可靠行情'

def trend(name):
    f=byname.get(name); v=f.get('chg_open') if f else None
    if v is None: return '震荡'
    if v>0.8: return '走强'
    if v<-0.8: return '走弱'
    return '震荡'

def status_from(v):
    if v is None: return '震荡'
    if v>0.8: return '走强'
    if v<-0.8: return '走弱'
    return '震荡'

def has_news(pattern):
    r=re.compile(pattern, re.I)
    return [n for n in raw_news if r.search((n.get('title','')+' '+n.get('text','')))]

def src_note(items):
    if not items: return ''
    n=items[0]
    return f"（{n['src']}｜{n['title'][:28]}）"

ai_news=has_news('算力|光模块|CPO|中际旭创|AI')
robot_news=has_news('机器人|减速器|电机|丝杠')
glass_news=has_news('玻璃基板|光伏玻璃|玻璃|纯碱')
commodity_news=has_news('原油|油价|商品|期货|铜|铝|焦煤|甲醇|纯碱')
macro_news=has_news('央行|逆回购|海外|纳指|道指|美联储|首申|港口|石油')

event_lines=[]
if ai_news:
    event_lines.append(f"- AI/CPO：算力链出现高位波动或情绪降温，关注是否扩散至光模块、液冷、高速连接器。{src_note(ai_news)}")
if robot_news:
    event_lines.append(f"- 机器人：板块逆势活跃，资金可能从高位AI链向高端制造题材切换。{src_note(robot_news)}")
if glass_news:
    event_lines.append(f"- 玻璃/材料：玻璃基板、纯碱玻璃链仍有事件催化，需区分题材弹性和成本改善。{src_note(glass_news)}")
if commodity_news:
    event_lines.append(f"- 商品/能源：商品与油价线索会影响有色、化工、建材链的成本和情绪传导。{src_note(commodity_news)}")
if macro_news:
    event_lines.append(f"- 宏观/海外：海外科技股、油价、流动性信息会影响今日A股风险偏好。{src_note(macro_news)}")
night_event_items=[]
for n in sorted([x for x in night_moves if commodity_material_move(x)], key=commodity_signal_score, reverse=True)[:3]:
    night_event_items.append(f"{n.get('name')}夜盘{pct(n.get('night_chg'))}、振幅{pct(n.get('night_amp'))}")
if night_event_items:
    event_lines.insert(0, "- 夜盘/盘前商品信号：" + '；'.join(night_event_items) + "。")
if not event_lines:
    event_lines=[f"- {n['src']}：{n['title'][:42]}。" for n in raw_news[:5]] or ['- 暂无可用事件线索。']
event_text='\n'.join(event_lines[:6])

# 核心池用于正式主结论；扩展池用于“商品异动雷达/潜力候选链路”。
# 扩展池品种只有在商品波动、A股同产业族反馈、新闻/逻辑或历史验证同时增强后，才进入正式传导复盘。
impact_map={name: impact_for(name) for name in set(list(CORE_NAMES) + list(EXPANDED_NAMES))}
track_order=[n for n in ['铜连续','铝连续','伦铜','伦铝','伦镍','螺纹钢连续','热轧卷板连续','铁矿石连续','焦煤连续','纯碱连续','玻璃连续','上海原油连续','纽约原油','甲醇连续','黄金'] if n in impact_map or n in byname]
commodity_rows=[]
for n in track_order:
    f=byname.get(n)
    if f:
        commodity_rows.append(f"{n}｜{fmt_num(f.get('last'))}｜{pct(f.get('chg_open'))}｜{pct(f.get('amp'))}｜{status_from(f.get('chg_open'))}｜{impact_map.get(n,'相关产业链')}")
commodity_text='\n'.join(commodity_rows) if commodity_rows else '暂无可靠商品行情。'

# 今日商品异动：按“昨日15:00—今日15:00”的原材料价格信号排序；日盘实时涨跌只作展示/兜底，不再用裸振幅抢排序。
combined=[]
for f in futs:
    n=night_byname.get(f.get('name')) or {}
    window_chg=n.get('night_chg') if n else f.get('chg_open')
    window_amp=n.get('night_amp') if n else f.get('amp')
    item={'name':f.get('name'), 'day':f, 'night':n,
          'window_chg':window_chg, 'window_amp':window_amp,
          'high_price':n.get('high_price') if n else f.get('high'),
          'low_price':n.get('low_price') if n else f.get('low'),
          'end_price':n.get('night_close') if n else f.get('last'),
          'abs_return_percentile':n.get('abs_return_percentile') if n else None}
    item['score']=commodity_signal_score(item)
    combined.append(item)
for n in night_moves:
    if not byname.get(n.get('name')):
        item={'name':n.get('name'), 'day':{}, 'night':n,
              'window_chg':n.get('night_chg'), 'window_amp':n.get('night_amp'),
              'high_price':n.get('high_price'), 'low_price':n.get('low_price'),
              'end_price':n.get('night_close'), 'abs_return_percentile':n.get('abs_return_percentile')}
        item['score']=commodity_signal_score(item)
        combined.append(item)
def anomaly_score(item):
    return commodity_signal_score(item)

def material_move_item(item):
    return commodity_material_move(item)
# 商品异动是上游原材料信号排序，不直接按链条评分或A股反馈排序；核心池与扩展雷达仍分层展示。
volatile=rank_commodity_moves(combined, core_limit=5, expanded_limit=3, strong_core_limit=8)
if not volatile:
    volatile=sorted(combined, key=anomaly_score, reverse=True)[:6]
volatile_lines=[]
for i,item in enumerate(volatile,1):
    name=item.get('name') or '未知品种'
    f=item.get('day') or {}; n=item.get('night') or {}
    day_chg=f.get('chg_open')
    direction='上涨' if (day_chg or 0)>0 else ('下跌' if (day_chg or 0)<0 else '震荡')
    impact=impact_map.get(name,'相关产业链')
    night_note=f"夜盘{pct(n.get('night_chg'))}、振幅{pct(n.get('night_amp'))}" if n else "夜盘暂无可靠分钟线"
    if f:
        day_note=f"日盘/收盘{direction}，最新{fmt_num(f.get('last'))}，较开盘{pct(day_chg)}，振幅{pct(f.get('amp'))}"
    else:
        day_note="日盘暂无可靠行情"
    pool_label='核心池' if is_core_name(name) else ('扩展雷达' if is_expanded_name(name) else '观察池')
    volatile_lines.append(f"{i}. {name}（{pool_label}）：{night_note}；{day_note}；可能影响：{impact}。")
volatile_text='\n'.join(volatile_lines) if volatile_lines else '暂无可识别的夜盘/日盘商品异动。'

idx_text='\n'.join(idx_brief_lines())
idx_join='；'.join(idx_line(d) for d in indices) if indices else '指数接口暂未返回可靠数据'

def is_active(name, chg_threshold=0.8, amp_threshold=2.0):
    f=byname.get(name)
    if not f: return False
    chg=abs(f.get('chg_open') or 0); amp=f.get('amp') or 0
    return chg>=chg_threshold or amp>=amp_threshold

def link_state(names):
    parts=[]
    for n in names:
        if byname.get(n): parts.append(f"{n}{trend(n)}（{pct(byname[n].get('chg_open'))}）")
    return '、'.join(parts)

def db_strong_links():
    global PROPAGATION_LINES
    PROPAGATION_LINES=[]
    try:
        import psycopg
        dsn='postgresql://' + 'a_share' + ':a_share_daily_local@127.0.0.1:15432/a_share_daily'
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT link_name, score, confidence, evidence, best_lag, best_corr,
                           llm_verdict, llm_adjustment, llm_reason, llm_model
                    FROM link_scores
                    WHERE trade_date=%s
                      AND run_id=%s
                      AND (score + COALESCE(llm_adjustment, 0)) >= 55
                      AND COALESCE(llm_verdict, 'keep') <> 'reject'
                    ORDER BY (score + COALESCE(llm_adjustment, 0)) DESC
                    LIMIT 5
                """, (date, os.environ.get('A_SHARE_RUN_ID')))
                rows=cur.fetchall()
        lines=[]
        for link_name, score, confidence, evidence, best_lag, best_corr, llm_verdict, llm_adjustment, llm_reason, llm_model in rows:
            ev=evidence or {}
            ups=ev.get('upstream') or []
            ds=ev.get('downstream') or []
            news=ev.get('news') or []
            unique_ups=[]; seen_up=set()
            for x in ups:
                nm=x.get('name')
                if nm and nm not in seen_up:
                    unique_ups.append(x); seen_up.add(nm)
            unique_ds=[]; seen_ds=set()
            for x in ds:
                nm=x.get('name')
                if nm and nm not in seen_ds:
                    unique_ds.append(x); seen_ds.add(nm)
            up_txt='、'.join(f"{x.get('name')} {float(x.get('pct_chg') or 0):+.2f}%" for x in unique_ups[:3]) or '原材料端暂无数据'
            ds_txt='、'.join(f"{x.get('name')} {float(x.get('pct_chg') or 0):+.2f}%" for x in unique_ds[:3]) or '受影响板块暂无匹配'
            prop_up_parts=[]
            for x in unique_ups[:3]:
                nm=x.get('name')
                n=night_byname.get(nm)
                if n:
                    prop_up_parts.append(f"{nm}夜盘{float(n.get('night_chg') or 0):+.2f}%/日盘{float(x.get('pct_chg') or 0):+.2f}%")
                else:
                    prop_up_parts.append(f"{nm}日盘{float(x.get('pct_chg') or 0):+.2f}%")
            prop_up_txt='、'.join(prop_up_parts) or up_txt
            news_items=[]; seen_news=set()
            for n in news:
                title=(n.get('title') or '').strip()
                src=(n.get('source') or '').strip()
                if title and title not in seen_news:
                    seen_news.add(title)
                    news_items.append(f"{src + '｜' if src else ''}{title[:34]}")
            news_txt='；'.join(news_items[:2]) if news_items else '暂无直接新闻催化，主要看价格和板块表现'
            logic=(ev.get('logic') or '').strip()
            direction_note=(ev.get('direction_note') or '').strip()
            reason=(llm_reason or '').strip()
            ds_names=' '.join(x.get('name','') for x in unique_ds)
            if any(k in ds_names for k in ['煤炭','有色','石油石化','钢铁','贵金属','稀土','小金属']):
                pathway='资源端/供给端反馈'
            elif any(k in ds_names for k in ['化工','煤化工','化纤','玻璃','建材','金属新材料']):
                pathway='中游材料/加工价差'
            elif any(k in ds_names for k in ['机械','汽车','家电','电机','电力设备','机器人','光伏','包装','消费制造']):
                pathway='制造端成本/需求传导'
            elif any(k in link_name for k in ['黄金','避险','风险偏好']):
                pathway='宏观/避险/风险偏好传导'
            else:
                pathway='受影响板块联动'
            corr_meta=ev.get('correlation') or {}
            if best_corr is not None:
                corr_val=float(best_corr)
                n_txt=f"n={int(corr_meta.get('sample_size'))}" if corr_meta.get('sample_size') is not None else "n=NA"
                pair_txt=''
                if corr_meta.get('upstream_name') and corr_meta.get('downstream_name'):
                    pair_txt=f"；样本对：{corr_meta.get('upstream_name')} × {corr_meta.get('downstream_name')}"
                sp_txt=''
                if corr_meta.get('spearman_market_adjusted') is not None:
                    sp_txt=f"；Spearman {float(corr_meta.get('spearman_market_adjusted')):+.2f}"
                if corr_val >= 0:
                    corr_explain='正相关，历史上更偏同向波动'
                else:
                    corr_explain='负相关，需结合成本压力、价差修复、需求走弱或情绪解释'
                history_txt=f"A股交易日T+{best_lag}；市场调整Pearson {corr_val:+.2f}{sp_txt}；{n_txt}{pair_txt}；{corr_explain}；非因果证明"
            else:
                history_txt='样本不足或相关性不显著；非因果证明'
            analysis_parts=[]
            if reason:
                analysis_parts.append(reason)
            if direction_note:
                analysis_parts.append(direction_note)
            elif logic:
                analysis_parts.append(logic)
            analysis_txt='；'.join(analysis_parts[:2]) or '价格波动与板块异动同场出现，需结合后续交易日验证持续性。'
            # 用户侧传导复盘只展示有统计/审核支撑的强链路；候选晋升链路若还没有
            # 相关性样本且不是高置信，留在后台自进化，不在日报里展开，避免噪声干扰阅读。
            is_backend_candidate = direction_note.startswith('候选晋升链路')
            if is_backend_candidate and best_corr is None and confidence != '高':
                continue
            conclusion=f"{confidence}置信｜{pathway}"
            if unique_ups and unique_ds:
                PROPAGATION_LINES.append(
                    f"{len(PROPAGATION_LINES)+1}. {link_name}｜{conclusion}\n"
                    f"   - 原材料：{prop_up_txt}\n"
                    f"   - A股反馈：{ds_txt}\n"
                    f"   - 事件线索：{news_txt}\n"
                    f"   - 历史倾向：{history_txt}\n"
                    f"   - 传导判断：{analysis_txt}"
                )
            if reason:
                reason=f"；判断：{reason}"
            lines.append(f"{link_name}：{confidence}置信。原材料端：{up_txt}；A股受影响板块：{ds_txt}；事件线索：{news_txt}；{history_txt}{reason}。")
        return lines
    except Exception:
        return []

# 当日强链路只保留在“今日（包括夜盘）商品异动/重大事件 → 今日A股受影响板块传导复盘”中展示。
# 之前“今日核心结论”和“传导复盘”都来自同一批 link_scores/PROPAGATION_LINES，容易重复。
# 这里仍先读取数据库强链路，用于填充 PROPAGATION_LINES，但不再单独生成核心结论区。
db_strong_links()

def db_propagation_review():
    """今日（包括夜盘）商品异动/重大事件 → 今日A股受影响板块传导复盘。
    使用 db_strong_links() 已经读取出的同一批当日链路证据，避免重复连接数据库。
    """
    lines=globals().get('PROPAGATION_LINES') or []
    return '\n'.join(lines) if lines else '未发现可确认的今日（包括夜盘）商品异动/重大事件 → 今日A股受影响板块强传导链路。'

propagation_text=db_propagation_review()


def db_candidate_watchlist():
    """高潜力候选链路、晋升和降级观察。
    用户侧只展示少量有提醒价值的内容：
    - 候选：仍在 watch/proposed、近期出现、规则/LLM理由较强，且未被标记为噪声/剔除；
    - 晋升：近期由 candidate_links 晋升为正式 link_mappings，优先展示当日未被 LLM reject 的链路；
    - 降级：当日规则分较高但被 LLM downgrade/reject，或历史后验精度明显偏弱的链路。
    """
    try:
        import psycopg
        db_password=os.getenv('A_SHARE_DB_PASSWORD') or 'a_share_daily_local'
        dsn='postgresql://' + 'a_share' + ':' + db_password + '@127.0.0.1:15432/a_share_daily'
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT candidate_id, link_name, upstream_hint, downstream_hint, status, seen_count,
                           first_seen_date, last_seen_date, evidence, llm_reason
                    FROM candidate_links
                    WHERE status IN ('watch','proposed')
                      AND last_seen_date >= %s::date - INTERVAL '7 days'
                      AND COALESCE(llm_reason,'') !~ '(噪声|误命中|无产业|无清晰|剔除|已禁用)'
                    ORDER BY last_seen_date DESC, seen_count DESC
                    LIMIT 20
                """, (date,))
                candidate_rows=cur.fetchall()
                cur.execute("""
                    SELECT c.link_name, c.upstream_hint, c.downstream_hint, c.seen_count, c.first_seen_date,
                           c.last_seen_date, c.evidence, c.llm_reason, ls.score, ls.confidence,
                           ls.llm_verdict, ls.llm_adjustment, ls.llm_reason
                    FROM candidate_links c
                    LEFT JOIN link_scores ls
                      ON ls.trade_date=%s AND ls.run_id=%s AND ls.link_id=c.promoted_link_id
                    WHERE c.status='promoted'
                      AND c.last_seen_date >= %s::date - INTERVAL '7 days'
                    ORDER BY c.updated_at DESC, c.seen_count DESC
                    LIMIT 20
                """, (date, os.environ.get('A_SHARE_RUN_ID'), date))
                promoted_rows=cur.fetchall()
                cur.execute("""
                    SELECT ls.link_name, ls.score, ls.confidence, ls.llm_verdict, ls.llm_adjustment,
                           ls.llm_reason, le.confirmed_count, le.failed_count, le.precision_estimate, le.best_lag
                    FROM link_scores ls
                    LEFT JOIN link_experience le ON ls.link_id=le.link_id
                    WHERE ls.trade_date=%s
                      AND ls.run_id=%s
                      AND (
                        COALESCE(ls.llm_verdict,'keep') IN ('downgrade','reject')
                        OR (le.precision_estimate IS NOT NULL AND le.confirmed_count + le.failed_count >= 3 AND le.precision_estimate < 0.4)
                      )
                      AND ls.score >= 45
                    ORDER BY CASE WHEN COALESCE(ls.llm_verdict,'keep')='reject' THEN 1 WHEN COALESCE(ls.llm_verdict,'keep')='downgrade' THEN 2 ELSE 3 END,
                             ls.score DESC
                    LIMIT 10
                """, (date, os.environ.get('A_SHARE_RUN_ID')))
                downgraded_rows=cur.fetchall()
    except Exception as e:
        return f'候选/晋降级观察暂不可用：{type(e).__name__}'

    def _ev_num(ev, key, default=0.0):
        try:
            if isinstance(ev, dict) and ev.get(key) is not None:
                return float(ev.get(key) or 0)
        except Exception:
            pass
        return default

    def _short_reason(*vals):
        for v in vals:
            txt=(v or '').strip()
            if txt:
                return txt[:54]
        return '需继续观察后续T+0/T+1/T+3反馈。'

    def _same_family_link(text):
        txt=str(text or '')
        for cfg in FAMILY_KEYWORDS.values():
            if re.search(cfg['upstream'], txt, re.I) and re.search(cfg['downstream'], txt, re.I):
                return True
        return False

    candidate_items=[]
    displayed_candidate_keys=set()
    def _canon_display_key(*vals):
        txt=''.join(str(v or '') for v in vals)
        txt=re.sub(r'\s+', '', txt)
        for old,new in {'焦煤/焦炭':'煤焦','焦煤焦炭':'煤焦','煤炭开采加工':'煤炭','煤炭行业':'煤炭','煤炭概念':'煤炭','锂矿概念':'锂电材料','锂矿/锂电材料':'锂电材料','电池材料':'锂电材料','石油石化':'石化','化工化纤':'化工/化纤'}.items():
            txt=txt.replace(old,new)
        return re.sub(r'[，,/、|｜]+','/',txt)
    for cid, link_name, up, down, status, seen, first_seen, last_seen, ev, reason in candidate_rows:
        ev=ev or {}
        rule_score=_ev_num(ev, 'rule_score')
        # 只保留“有潜力”的候选：多次出现，或当日规则证据较强，或由LLM提出watch。
        if (seen or 0) < 2 and rule_score < 4.5 and status != 'watch':
            continue
        if not _same_family_link(f"{link_name} {up or ''} {down or ''}"):
            continue
        display_key=_canon_display_key(up, down)
        if display_key in displayed_candidate_keys:
            continue
        displayed_candidate_keys.add(display_key)
        up_ev=ev.get('upstream') if isinstance(ev, dict) else None
        ds_ev=ev.get('downstream') if isinstance(ev, dict) else None
        up_txt=f"{up_ev.get('name')} {float(up_ev.get('pct_chg') or 0):+.2f}%" if isinstance(up_ev, dict) and up_ev.get('name') else (up or '上游待确认')
        ds_txt=f"{ds_ev.get('name')} {float(ds_ev.get('pct_chg') or 0):+.2f}%" if isinstance(ds_ev, dict) and ds_ev.get('name') else (down or 'A股板块待确认')
        watch_basis=[]
        if seen:
            watch_basis.append(f"出现{seen}次")
        if rule_score:
            watch_basis.append(f"候选分{rule_score:.1f}")
        if last_seen:
            watch_basis.append(f"最近{last_seen}")
        basis='，'.join(watch_basis) or '新候选'
        candidate_items.append(f"- 候选观察：{link_name}｜{basis}；证据：{up_txt} → {ds_txt}；关注：{_short_reason(reason)}")
        if len(candidate_items) >= 3:
            break

    promoted_items=[]
    downgrade_from_promoted=[]
    for link_name, up, down, seen, first_seen, last_seen, ev, cand_reason, score, confidence, verdict, adj, score_reason in promoted_rows:
        verdict=(verdict or '待评分')
        if verdict == 'reject':
            downgrade_from_promoted.append((link_name, score, confidence, verdict, adj, score_reason or cand_reason, None, None, None, None))
            continue
        # 晋升观察只展示同产业族、确有潜力的链路；跨行业误晋升留到“剔除/降级提醒”里排雷。
        if not _same_family_link(f"{link_name} {up or ''} {down or ''}"):
            downgrade_from_promoted.append((link_name, score, confidence, 'downgrade', adj, score_reason or cand_reason or '晋升链路跨行业，先作为排雷观察', None, None, None, None))
            continue
        if len(promoted_items) >= 3:
            continue
        score_txt=f"当日{confidence or '待定'}置信/规则分{float(score):.0f}" if score is not None else '等待下一轮评分'
        promoted_items.append(f"- 晋升观察：{link_name}｜候选出现{seen or 0}次后晋升；{score_txt}；下一步看T+0/T+1后验验证。")

    downgraded_items=[]
    for link_name, score, confidence, verdict, adj, reason, confirmed, failed, precision, best_lag in list(downgraded_rows) + downgrade_from_promoted:
        if len(downgraded_items) >= 4:
            break
        verdict_txt='剔除' if (verdict or '') == 'reject' else ('降级' if (verdict or '') == 'downgrade' else '历史表现偏弱')
        score_txt=f"原规则分{float(score):.0f}" if score is not None else '晋升后待复核'
        exp_txt=''
        if precision is not None:
            exp_txt=f"；后验胜率{float(precision):.0%}（有效{confirmed or 0}/失效{failed or 0}）"
        downgraded_items.append(f"- {verdict_txt}提醒：{link_name}｜{score_txt}，调整{float(adj or 0):+.0f}{exp_txt}；原因：{_short_reason(reason)}")

    lines=[]
    lines.extend(candidate_items)
    if promoted_items:
        lines.extend(promoted_items)
    elif promoted_rows:
        lines.append('- 晋升观察：暂无通过同产业族筛选的高潜力晋升链路；本次跨行业/题材误晋升已归入剔除或降级提醒。')
    lines.extend(downgraded_items)
    if not lines:
        return '暂无值得放入正式晚报的高潜力候选、晋升或降级链路；后台候选仍继续观察。'
    intro='说明：本节只筛选近期反复出现、规则/LLM证据较强、或当日被明显上调/下调的链路；不是确认结论，用于提前关注和排雷。'
    return intro + '\n' + '\n'.join(lines[:8])

candidate_watch_text=db_candidate_watchlist()

PREDICTION_EXPERIENCE_PATH=os.path.join(os.environ.get('HERMES_HOME', os.path.expanduser('~/.hermes')), 'a_share_daily_db', 'prediction_experience.json')

def prediction_patterns(name):
    if any(k in name for k in ['焦煤','螺纹','热轧','铁矿']):
        return ['煤炭','钢铁','黑色','机械','基建']
    if any(k in name for k in ['玻璃','纯碱']):
        return ['玻璃','光伏','建筑材料','建材','地产']
    if any(k in name for k in ['甲醇','原油']):
        return ['化工','煤化工','石化','化纤','包装']
    if any(k in name for k in ['铜','铝','镍']):
        return ['有色','金属新材料','电机','电网设备','机器人','汽车零部件']
    return [name.replace('连续','')]

def prediction_sentence(f):
    name=f.get('name','')
    chg=float(f.get('chg_open') or 0)
    amp=float(f.get('amp') or 0)
    n=night_byname.get(name) or {}
    night_chg=n.get('night_chg')
    same_dir = (night_chg is not None and night_chg * chg > 0)
    reverse = (night_chg is not None and night_chg * chg < 0)
    if any(k in name for k in ['焦煤']):
        sign='positive' if chg > 0 else 'negative'
        text='煤炭/焦煤供给端情绪预计偏强，钢铁与机械链更多体现成本压力，需求端传导需单独验证。' if chg > 0 else '黑色链情绪预计偏弱，煤炭和钢铁等供给/材料端板块承压概率更高，需求端传导需单独验证。'
    elif any(k in name for k in ['玻璃','纯碱']):
        sign='mixed'
        text='玻璃/纯碱走弱更可能被解读为需求偏弱；光伏玻璃或玻璃基板若上涨，更多来自题材和成本改善预期，持续性需打折。'
    elif any(k in name for k in ['甲醇','原油']):
        sign='positive' if chg > 0 else 'negative'
        text='能源化工链预计偏强，石化/煤化工/化工品等供给与中游板块存在跟随机会；包装、化纤等制造端若不能提价，会体现成本压力。' if chg > 0 else '能源化工链预计承压，石化/煤化工等供给与中游板块先受价格压力，制造端成本缓和但不必然转化为股价上涨。'
    elif any(k in name for k in ['铜','铝','镍']):
        sign='negative' if chg < 0 else 'positive'
        text='有色资源端预计承压；机器人、电机若继续上涨，应优先归因为题材资金，而不是原材料正向传导。' if chg < 0 else '有色资源和金属新材料预计偏强，电机/线缆/汽车零部件可能受成本预期扰动。'
    else:
        sign='positive' if chg > 0 else ('negative' if chg < 0 else 'mixed')
        text='相关产业链预计跟随商品方向波动，但若A股反向运行，应优先看题材、库存和需求预期。'
    if reverse:
        text+=' 夜盘与日盘方向背离，预测置信度下调。'
    elif same_dir and abs(chg) >= 0.8:
        text+=' 夜盘与日盘同向，短线传导置信度上调。'
    return sign, text

def load_prediction_store():
    try:
        with open(PREDICTION_EXPERIENCE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'records': [], 'experience': {}}

def save_prediction_store(store):
    os.makedirs(os.path.dirname(PREDICTION_EXPERIENCE_PATH), exist_ok=True)
    tmp=PREDICTION_EXPERIENCE_PATH+'.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, PREDICTION_EXPERIENCE_PATH)

def evaluate_due_predictions(store):
    # 今天只评估目标日已经过去的预测；这样“今日预测明日”，后天再沉淀经验，避免用盘中未完整数据。
    try:
        import psycopg
        dsn='postgresql://' + 'a_share' + ':a_share_daily_local@127.0.0.1:15432/a_share_daily'
        today=now.date()
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                for rec in store.get('records', []):
                    out=rec.get('outcome') or {}
                    if out and out.get('method') == '板块组合超额收益验证；mixed不自动确认为有效':
                        continue
                    try:
                        target=datetime.date.fromisoformat(rec['target_date'])
                    except Exception:
                        continue
                    if target > today:
                        continue
                    rows=[]
                    for pat in rec.get('downstream_patterns', [])[:8]:
                        cur.execute("""SELECT name, asset_type, pct_chg
                                      FROM market_quotes
                                      WHERE trade_date=%s AND asset_type IN ('industry','concept','legacy_sector') AND name ILIKE %s""", (target, f'%{pat}%'))
                        rows += cur.fetchall()
                    # Verify the predicted board basket, not the single largest absolute mover.
                    # Use broad-index excess return to avoid treating market beta as a commodity signal.
                    cur.execute("""SELECT pct_chg FROM market_quotes
                                  WHERE trade_date=%s AND asset_type='index'
                                    AND name IN ('上证指数','深证成指','创业板指')
                                  ORDER BY CASE name WHEN '上证指数' THEN 1 WHEN '深证成指' THEN 2 ELSE 3 END
                                  LIMIT 1""", (target,))
                    bench_row=cur.fetchone()
                    benchmark=float(bench_row[0] or 0) if bench_row else 0.0
                    dedup=[]; seen=set()
                    for r in rows:
                        key=(r[0], r[1])
                        if key in seen:
                            continue
                        seen.add(key); dedup.append(r)
                    if not dedup:
                        outcome='inconclusive'; score=0; best=None; avg_excess=None; hit_ratio=None
                    else:
                        excess=[float(r[2] or 0)-benchmark for r in dedup]
                        avg_excess=sum(excess)/len(excess)
                        exp=rec.get('expected_sign')
                        best_idx=max(range(len(dedup)), key=lambda i: abs(excess[i]))
                        best=dedup[best_idx]
                        if exp == 'positive':
                            hit_ratio=sum(1 for x in excess if x >= 0.5)/len(excess)
                            outcome='confirmed' if (avg_excess >= 0.5 and hit_ratio >= 0.5) else ('failed' if avg_excess <= -0.5 and hit_ratio <= 0.25 else 'inconclusive')
                        elif exp == 'negative':
                            hit_ratio=sum(1 for x in excess if x <= -0.5)/len(excess)
                            outcome='confirmed' if (avg_excess <= -0.5 and hit_ratio >= 0.5) else ('failed' if avg_excess >= 0.5 and hit_ratio <= 0.25 else 'inconclusive')
                        else:
                            # mixed is a hypothesis needing directional split; do not mark success just because one board moved.
                            hit_ratio=None
                            outcome='inconclusive'
                        score=avg_excess
                    rec['outcome']={'evaluated_at':str(today),'result':outcome,'best_match':({'name':best[0],'asset_type':best[1],'pct_chg':float(best[2] or 0)} if best else None),'score':score,'avg_excess':avg_excess,'hit_ratio':hit_ratio,'benchmark_pct':benchmark,'method':'板块组合超额收益验证；mixed不自动确认为有效'}
                    key=rec.get('key') or rec.get('upstream') or 'unknown'
                    exp=store.setdefault('experience', {}).setdefault(key, {'confirmed':0,'failed':0,'inconclusive':0,'precision':None,'updated_at':None})
                    exp[outcome]=int(exp.get(outcome,0))+1
                    denom=exp.get('confirmed',0)+exp.get('failed',0)
                    exp['precision']=round((exp.get('confirmed',0)+2)/(denom+4), 3) if denom >= 10 else None
                    exp['updated_at']=str(today)
        # Rebuild morning-prediction experience from records evaluated by the new
        # method so re-runs do not double-count old outcomes or tiny manual tests.
        rebuilt={}
        for rec in store.get('records', []):
            out=rec.get('outcome') or {}
            if out.get('method') != '板块组合超额收益验证；mixed不自动确认为有效':
                continue
            key=rec.get('key') or rec.get('upstream') or 'unknown'
            bucket=rebuilt.setdefault(key, {'confirmed':0,'failed':0,'inconclusive':0,'precision':None,'updated_at':str(today)})
            result=out.get('result') or 'inconclusive'
            if result not in bucket:
                result='inconclusive'
            bucket[result]+=1
        for bucket in rebuilt.values():
            denom=bucket.get('confirmed',0)+bucket.get('failed',0)
            bucket['precision']=round((bucket.get('confirmed',0)+2)/(denom+4), 3) if denom >= 10 else None
        store['experience']=rebuilt
    except Exception:
        return store
    return store

def build_prediction_review():
    store=evaluate_due_predictions(load_prediction_store())
    today=now.date()
    save_prediction_store(store)
    todays_by_upstream={}
    for rec in store.get('records', []):
        if rec.get('target_date') == str(today) and rec.get('report_type') == 'morning_preopen':
            # Only evaluate real pre-open records. Manual reruns after 10:00 are
            # not legitimate opening predictions and should not pollute stats.
            try:
                created=datetime.datetime.fromisoformat(str(rec.get('created_at')).replace('Z',''))
                if created.time() > datetime.time(10,0):
                    continue
            except Exception:
                pass
            key=rec.get('upstream') or rec.get('key') or rec.get('id')
            old=todays_by_upstream.get(key)
            if old is None or str(rec.get('created_at','')) > str(old.get('created_at','')):
                todays_by_upstream[key]=rec
    todays=list(todays_by_upstream.values())
    if not todays:
        return '今日未找到早报预测记录；本次只做收盘传导复盘，不做预测有效性评价。'
    order={'confirmed':0,'failed':1,'inconclusive':2}
    todays.sort(key=lambda r: order.get(((r.get('outcome') or {}).get('result')), 9))
    label={'confirmed':'有效','failed':'失效','inconclusive':'未定'}
    lines=[]
    for rec in todays[:8]:
        out=rec.get('outcome') or {}
        result=out.get('result') or 'inconclusive'
        best=out.get('best_match') or {}
        best_txt='暂无匹配板块数据'
        if best:
            board_move=float(best.get('pct_chg') or 0)
            best_txt=f"{best.get('name')} {board_move:+.2f}%"
        basis=rec.get('basis') or {}
        excess_txt=''
        if out.get('avg_excess') is not None:
            hr=out.get('hit_ratio')
            hit_txt=f"，方向命中率{float(hr):.0%}" if hr is not None else ''
            excess_txt=f"；组合超额{float(out.get('avg_excess') or 0):+.2f}%{hit_txt}"
        lines.append(f"{len(lines)+1}. {rec.get('upstream')}：早报判断{label.get(result,result)}；夜盘依据{pct(basis.get('night_chg'))}、振幅{pct(basis.get('night_amp'))}；A股受影响板块验证：{best_txt}{excess_txt}。原预测：{rec.get('prediction')}")
    counts={k:0 for k in ['confirmed','failed','inconclusive']}
    for rec in todays:
        res=(rec.get('outcome') or {}).get('result') or 'inconclusive'
        counts[res]=counts.get(res,0)+1
    summary=f"早报预测验证：有效{counts.get('confirmed',0)}条，失效{counts.get('failed',0)}条，未定{counts.get('inconclusive',0)}条。"
    return summary + '\n' + '\n'.join(lines)

prediction_review_text=build_prediction_review()

def db_data_health():
    """Human-facing data health summary.

    Be explicit about whether failed sources are live/current-day feeds or
    historical quote refreshes. When historical refresh fails, do not imply old
    link_scores were reused; the scoring code recomputes today's link_scores
    from whatever historical quote samples are already in market_quotes plus
    today's live quotes/news.
    """
    history_sources={'sina_futures_history','akshare_index_history','akshare_board_history'}
    source_names={
        'sina_futures_history':'商品期货历史行情',
        'akshare_index_history':'A股指数历史行情',
        'akshare_board_history':'行业/概念板块历史行情',
        'sina_futures':'商品期货实时行情',
        'sina_index':'A股指数实时行情',
        'akshare_fund_flow_industry':'行业资金流实时数据',
        'akshare_fund_flow_concept':'概念资金流实时数据',
        'akshare_sector_spot':'板块实时行情',
        'eastmoney_news':'东方财富新闻',
        'wscn_livenews':'华尔街见闻快讯',
    }
    try:
        import psycopg
        db_password=os.getenv('A_SHARE_DB_PASSWORD') or 'a_share_daily_local'
        dsn='postgresql://' + 'a_share' + ':' + db_password + '@127.0.0.1:15432/a_share_daily'
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT source,status,rows_count,attempts,latency_ms,error,updated_at FROM source_status WHERE run_id=%s ORDER BY source", (os.environ.get('A_SHARE_RUN_ID'),))
                sources=cur.fetchall()
                cur.execute("""
                    SELECT source, count(*) AS rows, min(trade_date), max(trade_date), max(updated_at)
                    FROM market_quotes
                    WHERE source = ANY(%s)
                    GROUP BY source
                    ORDER BY source
                """, (list(history_sources),))
                hist_rows=cur.fetchall()
                cur.execute("""
                    SELECT count(*), max(created_at), max(llm_reviewed_at),
                           count(*) FILTER (WHERE best_corr IS NOT NULL)
                    FROM link_scores
                    WHERE trade_date=%s AND run_id=%s
                """, (date, os.environ.get('A_SHARE_RUN_ID')))
                score_row=cur.fetchone()
        if not sources:
            return '数据库接口状态暂无记录；本次日报主要依赖脚本内实时接口与已有数据库内容。'

        current_failures=[]; history_failures=[]
        ok_parts=[]
        for source,status,rows,attempts,latency,error,updated_at in sources:
            label=source_names.get(source, source)
            if status == 'ok':
                ok_parts.append(f"{label}{rows}条")
            else:
                item=f"- {label}（{source}）：尝试{attempts}次后失败，返回{rows}条，耗时{latency}ms；错误：{error or '无错误详情'}"
                if source in history_sources:
                    history_failures.append(item)
                else:
                    current_failures.append(item)

        hist_by_source={r[0]: {'rows':r[1], 'min_date':r[2], 'max_date':r[3], 'updated_at':r[4]} for r in hist_rows}
        hist_available=[v for v in hist_by_source.values() if (v.get('rows') or 0) > 0]
        hist_total=sum(int(v.get('rows') or 0) for v in hist_available)
        hist_latest=max((v.get('updated_at') for v in hist_available if v.get('updated_at')), default=None)
        hist_ranges=[]
        for src in sorted(history_sources):
            v=hist_by_source.get(src)
            if v:
                hist_ranges.append(f"{source_names.get(src,src)}{v['rows']}条（{v['min_date']}至{v['max_date']}，最近写入{v['updated_at'].strftime('%H:%M') if v.get('updated_at') else '未知'}）")
        score_count, score_created, score_reviewed, corr_count = score_row or (0,None,None,0)
        score_note = ''
        if score_count:
            score_note=f"今日链路评分已于{score_created.strftime('%H:%M:%S') if score_created else '未知时间'}重新计算{score_count}条，其中{corr_count or 0}条含滞后/相关性结果"
            if score_reviewed:
                score_note += f"，LLM审核于{score_reviewed.strftime('%H:%M:%S')}完成"
            score_note += '。'
        else:
            score_note='今日链路评分暂无数据库记录。'

        parts=[]
        if current_failures:
            parts.append("⚠️ 实时数据源本次有失败，可能影响今日行情/新闻覆盖：\n" + '\n'.join(current_failures))
        if history_failures:
            if hist_total > 0:
                latest_txt=hist_latest.strftime('%Y-%m-%d %H:%M') if hist_latest else '未知时间'
                parts.append("⚠️ 部分历史行情接口本次刷新失败；本次没有复用旧链路评分，而是使用数据库中最近一次成功回补的历史行情样本，结合今日实时行情/新闻重新计算今日链路评分。"
                             f"历史样本合计{hist_total}条，最近写入{latest_txt}。\n" + '\n'.join(history_failures))
            else:
                parts.append("⚠️ 部分历史行情接口本次刷新失败，且数据库未发现可用历史样本；滞后/相关性评分可能缺失或降级。\n" + '\n'.join(history_failures))
        if not current_failures and not history_failures:
            parts.append("全部数据源本次刷新成功。")
        if hist_ranges:
            parts.append("历史行情样本状态：" + '；'.join(hist_ranges) + '。')
        parts.append(score_note)
        if ok_parts and (current_failures or history_failures):
            parts.append("其余成功源：" + '、'.join(ok_parts[:8]) + ('等。' if len(ok_parts)>8 else '。'))
        return '\n'.join(parts)
    except Exception as e:
        return f'数据库接口状态读取失败：{type(e).__name__}'

data_health_text=db_data_health()


report=f"""【A股晚报｜夜盘原材料→A股受影响板块传导复盘｜{date} 15:00】
{close_schedule_note}

一、市场概览
{idx_text}

二、今日（包括夜盘）商品异动/重大事件 → 今日A股受影响板块传导复盘
{propagation_text}

三、潜力候选链路与晋升/降级观察
{candidate_watch_text}

四、今日事件线索（含夜盘）
{event_text}

五、今日商品异动
说明：今日（含夜盘）窗口为{report_window_label}；核心池用于正式主结论，扩展雷达用于发现提醒和候选闭环。扩展品种只有在商品波动、A股同产业族反馈、新闻/逻辑或历史验证增强后，才晋升到正式传导复盘。
{volatile_text}

六、早报预测验证与经验沉淀
{prediction_review_text}

七、数据来源

新浪指数行情、东方财富财经新闻、华尔街见闻快讯、新浪期货实时行情、Sina期货分钟线夜盘数据、Docker/PostgreSQL链路评分库。
数据源状态：{data_health_text}
统计窗口：{report_window_label}；A股09:30-15:00为日盘，其他时间统一归为夜盘/盘前盘后。
生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')}。公开数据自动整理，不构成投资建议。
"""
try:
    import psycopg
    db_password=os.getenv('A_SHARE_DB_PASSWORD') or 'a_share_daily_local'
    dsn=f'postgresql://a_share:{db_password}@127.0.0.1:15432/a_share_daily'
    run_id=os.environ.get('A_SHARE_RUN_ID')
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO report_runs (run_id, trade_date, report_type, trigger, started_at, finished_at, status, metadata)
                VALUES (%s,%s,'evening',%s,now(),now(),'rendered',%s::jsonb)
                ON CONFLICT (run_id) DO UPDATE SET finished_at=now(), status='rendered', report_type='evening'""",
                (run_id, date, os.environ.get('A_SHARE_RUN_TRIGGER','cron'), json.dumps({'renderer': 'a_share_chain_daily.sh'}, ensure_ascii=False)))
            cur.execute("""INSERT INTO report_outputs (run_id, trade_date, report_type, content, metadata)
                VALUES (%s,%s,'evening',%s,%s::jsonb)
                ON CONFLICT (run_id) DO UPDATE SET content=EXCLUDED.content, created_at=now(), metadata=EXCLUDED.metadata""",
                (run_id, date, report, json.dumps({'window': report_window_label}, ensure_ascii=False)))
        conn.commit()
except Exception:
    pass
print(report)
PY
KLINE_VISUAL="$HERMES_HOME/scripts/a_share_chain_kline_visual.py"
KLINE_DATE="$(date +%Y-%m-%d)"
KLINE_OUT="${A_SHARE_KLINE_HTML_OUT:-$HOME/a_share_chain_phase_view_$(date +%Y%m%d).html}"
if [ -f "$KLINE_VISUAL" ]; then
  if A_SHARE_KLINE_DATE="$KLINE_DATE" A_SHARE_KLINE_HTML_OUT="$KLINE_OUT" "$PYTHON" "$KLINE_VISUAL" >/tmp/a_share_chain_kline_visual.log 2>&1; then
    printf '\nHTML相位K线图：\nMEDIA:%s\n' "$KLINE_OUT"
  else
    printf '\nHTML相位K线图生成失败，详见 /tmp/a_share_chain_kline_visual.log\n'
  fi
fi
