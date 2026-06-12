#!/usr/bin/env bash
set -euo pipefail
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PYTHON="$HERMES_HOME/venvs/a_share_daily/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON="python3"; fi
: "${A_SHARE_RUN_ID:=morning_$(date +%Y%m%d_%H%M%S)_$$}"
export A_SHARE_RUN_ID
export A_SHARE_RUN_TYPE="${A_SHARE_RUN_TYPE:-morning}"
export A_SHARE_RUN_TRIGGER="${A_SHARE_RUN_TRIGGER:-cron}"
DB_COLLECTOR="$HERMES_HOME/scripts/a_share_market_db.py"
if [ -f "$DB_COLLECTOR" ]; then
  "$PYTHON" "$DB_COLLECTOR" --collect-only --no-history >/tmp/a_share_morning_collect.log 2>&1 || true
fi
"$PYTHON" - <<'PY'
import ast, datetime, hashlib, json, os, urllib.request, sys
SCRIPT_DIR=os.path.join(os.environ.get('HERMES_HOME', os.path.expanduser('~/.hermes')), 'scripts')
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from a_share_commodity_universe import ALL_MINLINE_SYMBOLS, FAMILY_KEYWORDS, impact_for, is_core_name, is_expanded_name
from a_share_commodity_signal import attach_history_percentiles, commodity_signal_score, material_move as commodity_material_move, rank_commodity_moves

PREDICTION_EXPERIENCE_PATH=os.path.join(os.environ.get('HERMES_HOME', os.path.expanduser('~/.hermes')), 'a_share_daily_db', 'prediction_experience.json')
now=datetime.datetime.now(); today=now.date(); date=now.strftime('%Y-%m-%d')
window_start=datetime.datetime.combine(today-datetime.timedelta(days=1), datetime.time(15,0))
window_end=datetime.datetime.combine(today, datetime.time(9,30))
planned_time=datetime.datetime.combine(today, datetime.time(8,50))
late_minutes=max(0, int((now-planned_time).total_seconds()//60))
if late_minutes > 10:
    schedule_note=f"提示：本次生成时间较08:50盘前目标延迟{late_minutes}分钟，开盘交易参考价值下降，更适合做盘中观察。"
else:
    schedule_note="盘前生成正常。"
window_label=f"{window_start.strftime('%m-%d %H:%M')}—{window_end.strftime('%m-%d %H:%M')}"
run_id=os.environ.get('A_SHARE_RUN_ID')

IMPACT_MAP={name: impact_for(name) for _, name in ALL_MINLINE_SYMBOLS}

def pct(x):
    return 'NA' if x is None else f'{float(x):+.2f}%'

def fmt_num(x):
    try: return f'{float(x):.2f}'
    except Exception: return str(x)

def sina_night_moves():
    # 早报窗口固定为昨日15:00—今日09:30；A股09:30-15:00之外归为夜盘/盘前。
    # 国内商品分钟线按该窗口内实际交易活跃段统计：夜盘主段 + 若已返回则纳入09:00—09:30盘前商品分钟线。
    symbols=ALL_MINLINE_SYMBOLS
    out=[]
    for sym,name in symbols:
        try:
            url=f'https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_DATA=/InnerFuturesNewService.getMinLine?symbol={sym}'
            txt=urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn'}), timeout=8).read().decode('utf-8','replace')
            body=txt.split('var _DATA=(',1)[1].rsplit(');',1)[0]
            rows=ast.literal_eval(body)
            window_rows=[]; trade_date=None
            for r in rows:
                if len(r)<2: continue
                tm=str(r[0])
                if len(r)>6 and r[6]: trade_date=r[6]
                # 与早报窗口保持一致：昨日15:00—今日09:30。
                # 国内期货分钟线通常实际覆盖夜盘主段(20:00/21:00-02:30)与日盘开盘后；
                # 若09:00—09:30盘前商品分钟线已返回，也纳入开盘前信号。
                in_window = (tm >= '15:00') or (tm <= '09:30')
                # 排除03:00—08:59这段通常无国内商品连续交易的空窗，避免接口残留异常点。
                active_segment = (tm >= '20:00') or (tm < '03:00') or ('09:00' <= tm <= '09:30')
                if in_window and active_segment:
                    try: window_rows.append((tm, float(r[1])))
                    except Exception: pass
            if len(window_rows)>=2:
                first=window_rows[0][1]; last=window_rows[-1][1]; high=max(x[1] for x in window_rows); low=min(x[1] for x in window_rows)
                out.append({'symbol':sym,'name':name,'night_open':first,'night_close':last,'night_chg':(last-first)/first*100 if first else None,'night_amp':(high-low)/first*100 if first else None,'high_price':high,'low_price':low,'night_start':window_rows[0][0],'night_end':window_rows[-1][0],'date':trade_date,'source':'sina_futures_minline','window':'15:00-09:30_active_segments'})
        except Exception:
            continue
    return out

def prediction_patterns(name):
    if any(k in name for k in ['焦煤','焦炭','螺纹','热轧','铁矿','硅铁','锰硅','不锈钢']): return ['煤炭','钢铁','黑色','机械','基建','特钢']
    if any(k in name for k in ['玻璃','纯碱']): return ['玻璃','光伏','建筑材料','建材','地产']
    if any(k in name for k in ['甲醇','原油','燃料油','沥青','液化石油气','PTA','对二甲苯','乙二醇','苯乙烯','PVC','聚丙烯','塑料','短纤','烧碱']): return ['化工','煤化工','石化','化纤','塑料','包装','交运']
    if any(k in name for k in ['铜','铝','锌','铅','镍','锡','氧化铝']): return ['有色','小金属','金属新材料','电机','电网设备','机器人','汽车零部件']
    if any(k in name for k in ['工业硅','碳酸锂']): return ['锂','电池','新能源','光伏','电力设备','汽车']
    if any(k in name for k in ['黄金','白银']): return ['黄金','贵金属','珠宝','光伏']
    if any(k in name for k in ['尿素']): return ['化肥','农化','农业','煤化工']
    if any(k in name for k in ['橡胶','20号胶','丁二烯']): return ['轮胎','橡胶','汽车零部件','汽车']
    if any(k in name for k in ['豆粕','菜粕','豆油','棕榈油','菜油','豆一','豆二','玉米','淀粉','棉花','白糖','苹果','花生','生猪','鸡蛋']): return ['农业','饲料','养殖','食品','饮料','纺织','服装','种业']
    return [name.replace('连续','')]

def night_prediction_sentence(n):
    name=n.get('name',''); chg=float(n.get('night_chg') or 0); amp=float(n.get('night_amp') or 0)
    if any(k in name for k in ['焦煤','螺纹','热轧','铁矿']):
        sign='positive' if chg > 0 else 'negative'
        text='黑色链开盘前情绪预计偏强，煤炭/钢铁等供给端更容易先反应；工程机械、基建链需看需求预期是否配合。' if chg > 0 else '黑色链开盘前情绪预计偏弱，煤炭、钢铁等供给端与工程机械链承压概率较高。'
    elif any(k in name for k in ['玻璃','纯碱']):
        sign='mixed'
        text='玻璃/纯碱夜盘波动更可能影响建材、光伏玻璃成本预期；若A股反向，应优先看地产/光伏题材。'
    elif any(k in name for k in ['甲醇','原油']):
        sign='positive' if chg > 0 else 'negative'
        text='能源化工链开盘前预计偏强，石化、煤化工等供给/中游板块更易受益；包装、化纤等制造端更多体现成本压力。' if chg > 0 else '能源化工链开盘前预计承压，石化/煤化工等供给与中游板块先受价格压力，制造端成本缓和但不必然形成股价正反馈。'
    elif any(k in name for k in ['铜','铝','镍']):
        sign='positive' if chg > 0 else 'negative'
        text='有色资源和金属新材料开盘前预计偏强，电机/电网/汽车零部件可能受成本预期扰动。' if chg > 0 else '有色资源端开盘前预计承压；机器人、电机若走强，更可能来自题材资金而非原材料正向传导。'
    else:
        sign='positive' if chg > 0 else ('negative' if chg < 0 else 'mixed')
        text='相关产业链预计跟随夜盘方向波动，若A股反向运行，应优先看题材、库存和需求预期。'
    if abs(chg) < 0.3 and amp < 1.0:
        text += ' 夜盘信号偏弱，预测置信度较低。'
    elif abs(chg) >= 1.0 or amp >= 2.0:
        text += ' 夜盘波动较大，开盘传导置信度上调。'
    return sign, text

def load_store():
    try:
        with open(PREDICTION_EXPERIENCE_PATH,'r',encoding='utf-8') as f: return json.load(f)
    except Exception:
        return {'records': [], 'experience': {}}

def save_store(store):
    os.makedirs(os.path.dirname(PREDICTION_EXPERIENCE_PATH), exist_ok=True)
    tmp=PREDICTION_EXPERIENCE_PATH+'.tmp'
    with open(tmp,'w',encoding='utf-8') as f: json.dump(store,f,ensure_ascii=False,indent=2,default=str)
    os.replace(tmp,PREDICTION_EXPERIENCE_PATH)

def db_window_moves(report_type='morning'):
    try:
        import psycopg
        import a_share_market_db as market_db
        dsn=os.getenv('A_SHARE_DAILY_DSN') or market_db.DB_DSN
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol, name, start_price, end_price, pct_chg, amplitude, high_price, low_price, first_ts, last_ts, target_date
                    FROM commodity_window_moves
                    WHERE target_date=%s AND report_type=%s
                    ORDER BY updated_at DESC
                """, (today, report_type))
                rows=cur.fetchall()
        out=[]
        for sym,name,startp,endp,chg,amp,highp,lowp,first_ts,last_ts,tdate in rows:
            out.append({'symbol': sym, 'name': name, 'night_open': float(startp) if startp is not None else None,
                        'night_close': float(endp) if endp is not None else None,
                        'night_chg': float(chg) if chg is not None else None,
                        'night_amp': float(amp) if amp is not None else None,
                        'high_price': float(highp) if highp is not None else None,
                        'low_price': float(lowp) if lowp is not None else None,
                        'night_start': first_ts.strftime('%m-%d %H:%M') if first_ts else '',
                        'night_end': last_ts.strftime('%m-%d %H:%M') if last_ts else '',
                        'date': str(tdate), 'source': 'db:commodity_window_moves', 'window': '15:00-09:30'})
        return out
    except Exception:
        return []

def db_window_history(report_type='morning'):
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
                """, (report_type, today))
                for name, chg in cur.fetchall():
                    out.setdefault(name, []).append(abs(float(chg)))
        return out
    except Exception:
        return {}

night_moves=attach_history_percentiles(db_window_moves('morning'), db_window_history('morning'))
store=load_store(); existing={r.get('id') for r in store.get('records', [])}
def experience_precision(name, min_decided=10):
    exp=(store.get('experience') or {}).get(name) or {}
    confirmed=int(exp.get('confirmed') or 0); failed=int(exp.get('failed') or 0)
    decided=confirmed+failed
    if decided < min_decided:
        return None
    # Beta(2,2) smoothing: avoid overreacting to small samples even after threshold.
    return (confirmed + 2) / (decided + 4)

def selection_score(x):
    return commodity_signal_score(x)
def material_move(x):
    return commodity_material_move(x)
# 排序目标改为“原材料价格信号雷达”：先找商品本身的方向性窗口收益、相对历史显著性与趋势质量；
# 历史早报验证有效率不再参与第一层商品选择，只在后续预测置信度里提示。
selected=rank_commodity_moves(night_moves, core_limit=5, expanded_limit=3, strong_core_limit=8)
if not selected:
    selected=sorted(night_moves, key=selection_score, reverse=True)[:5]
lines=[]; fact_lines=[]

def mechanism_type(name, sign):
    if any(k in name for k in ['焦煤','焦炭','螺纹','热轧','铁矿','硅铁','锰硅']):
        return '黑色/资源端同向反馈' if sign in ('positive','negative') else '黑色链成本/需求再验证'
    if any(k in name for k in ['原油','燃料油','低硫燃料油','沥青','液化石油气','甲醇','PTA','对二甲苯','乙二醇','苯乙烯','PVC','聚丙烯','塑料','短纤']):
        return '能源化工资源端/中游价差'
    if any(k in name for k in ['铜','铝','锌','铅','镍','锡','氧化铝']):
        return '有色资源端同向与制造端成本扰动'
    if any(k in name for k in ['碳酸锂','工业硅']):
        return '新能源材料价格反馈'
    if any(k in name for k in ['玻璃','纯碱']):
        return '建材光伏成本/需求预期'
    return '同产业族价格反馈'

def expected_direction_text(sign):
    if sign == 'positive':
        return '资源/材料端偏正向；制造端需看成本是否可转嫁'
    if sign == 'negative':
        return '资源/材料端偏负向；下游若上涨多按成本缓和或题材处理'
    return '方向分化，必须拆分资源端、成本端和题材端验证'

def counter_evidence(name, sign):
    return '若A股同产业族板块相对大盘方向相反，或涨跌主要来自AI/机器人等非商品题材，则本信号降级。'
for n in selected:
    sign, sentence=night_prediction_sentence(n)
    p=experience_precision(n.get('name'))
    if p is not None:
        if p >= 0.65:
            sentence += f' 历史早报验证有效率{p:.0%}，置信度小幅上调。'
        elif p <= 0.35:
            sentence += f' 历史早报验证有效率{p:.0%}，置信度下调。'
    rec={
        'id': hashlib.sha1(f"morning|{today}|{n.get('name')}|{sign}|{round(float(n.get('night_chg') or 0),2)}".encode()).hexdigest()[:16],
        'report_type': 'morning_preopen',
        'signal_date': str(today),
        'target_date': str(today),
        'created_at': now.isoformat(timespec='seconds'),
        'run_id': run_id,
        'key': n.get('name'),
        'upstream': n.get('name'),
        'expected_sign': sign,
        'downstream_patterns': prediction_patterns(n.get('name','')),
        'affected_patterns': prediction_patterns(n.get('name','')),
        'basis': {'window_start': window_start.isoformat(timespec='minutes'), 'window_end': window_end.isoformat(timespec='minutes'), 'night_chg': n.get('night_chg'), 'night_amp': n.get('night_amp'), 'night_start': n.get('night_start'), 'night_end': n.get('night_end'), 'night_close': n.get('night_close'), 'experience_precision': p},
        'prediction': sentence,
    }
    if rec['id'] not in existing:
        store.setdefault('records', []).append(rec); existing.add(rec['id'])
    impact=IMPACT_MAP.get(n.get('name'),'相关产业链')
    pool_label='核心池' if is_core_name(n.get('name','')) else ('扩展雷达' if is_expanded_name(n.get('name','')) else '观察池')
    fact_lines.append(f"- {n.get('name')}（{pool_label}）：夜盘{pct(n.get('night_chg'))}，振幅{pct(n.get('night_amp'))}，收于{fmt_num(n.get('night_close'))}；潜在受影响板块：{impact}。")
    lines.append(f"{len(lines)+1}. {n.get('name')}（{pool_label}）\n   - 信号：夜盘{pct(n.get('night_chg'))}，振幅{pct(n.get('night_amp'))}，收于{fmt_num(n.get('night_close'))}\n   - 机制：{mechanism_type(n.get('name',''), sign)}\n   - 预计方向：{expected_direction_text(sign)}\n   - 受影响板块：{impact}\n   - 判断：{sentence}\n   - 反证条件：{counter_evidence(n.get('name',''), sign)}")
save_store(store)

if not selected:
    fact_text='暂无可靠夜盘分钟线数据。'
    pred_text='暂无可给出的高质量开盘前传导预测。'
else:
    fact_text='\n'.join(fact_lines)
    pred_text='\n'.join(lines)

report=f"""【A股早报｜夜盘原材料→A股受影响板块传导预测｜{date} 08:50】
{schedule_note}

一、夜盘/盘前重点异动（{window_label}）
{fact_text}

二、今日A股交易时段传导预测
{pred_text}

三、下午复盘口径
15:00收盘后将按“今日（含夜盘）=昨日15:00至今日15:00”的窗口，复盘“今日（包括夜盘）商品异动/重大事件 → 今日A股受影响板块传导”，并验证本次早报预测是否有效，结果写入后台经验库。核心池直接用于主结论；扩展雷达只做发现提醒和候选闭环，需商品波动、A股同产业族反馈、新闻/逻辑或历史验证同时增强后，才晋升为正式传导链路。

数据来源：新浪期货分钟线夜盘数据。生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')}。公开数据自动整理，不构成投资建议。"""
try:
    import psycopg
    db_password=os.getenv('A_SHARE_DB_PASSWORD') or 'a_share_daily_local'
    dsn=f'postgresql://a_share:{db_password}@127.0.0.1:15432/a_share_daily'
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS report_runs (
                run_id text PRIMARY KEY, trade_date date NOT NULL, report_type text NOT NULL DEFAULT 'morning',
                trigger text NOT NULL DEFAULT 'manual', started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
                status text NOT NULL DEFAULT 'running', script_version text, notes text, metadata jsonb NOT NULL DEFAULT '{}'::jsonb)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS report_outputs (
                run_id text PRIMARY KEY REFERENCES report_runs(run_id) ON DELETE CASCADE, trade_date date NOT NULL, report_type text NOT NULL,
                content text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), metadata jsonb NOT NULL DEFAULT '{}'::jsonb)""")
            cur.execute("ALTER TABLE morning_predictions ADD COLUMN IF NOT EXISTS run_id text")
            cur.execute("""INSERT INTO report_runs (run_id, trade_date, report_type, trigger, started_at, finished_at, status, metadata)
                VALUES (%s,%s,'morning',%s,now(),now(),'rendered',%s::jsonb)
                ON CONFLICT (run_id) DO UPDATE SET finished_at=now(), status='rendered', report_type='morning'""",
                (run_id, today, os.environ.get('A_SHARE_RUN_TRIGGER','cron'), json.dumps({'window': window_label}, ensure_ascii=False)))
            cur.execute("""INSERT INTO report_outputs (run_id, trade_date, report_type, content, metadata)
                VALUES (%s,%s,'morning',%s,%s::jsonb)
                ON CONFLICT (run_id) DO UPDATE SET content=EXCLUDED.content, created_at=now(), metadata=EXCLUDED.metadata""",
                (run_id, today, report, json.dumps({'window': window_label, 'late_minutes': late_minutes}, ensure_ascii=False)))
        conn.commit()
except Exception:
    pass
print(report)
PY
