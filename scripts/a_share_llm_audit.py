#!/usr/bin/env python3
"""LLM audit/discovery layer for the A-share raw-material affected-board daily report.

Reads deterministic scores and proposed candidate links from PostgreSQL, asks the
LLM to audit evidence quality and discover missed upstream→A-share affected-board paths, then
writes bounded fields to link_scores and durable proposed links to candidate_links.
"""
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from typing import Any

import psycopg

DB_DSN = os.getenv('A_SHARE_DAILY_DSN') or 'postgresql://' + 'a_share' + ':a_share_daily_local@127.0.0.1:15432/a_share_daily'
MODEL = os.getenv('A_SHARE_LLM_MODEL', 'gpt-5.5')
PROVIDER = os.getenv('A_SHARE_LLM_PROVIDER', 'openai-codex')
TRADE_DATE = os.getenv('A_SHARE_TRADE_DATE') or dt.datetime.now().date().isoformat()
RUN_ID = os.getenv('A_SHARE_RUN_ID')
TIMEOUT_SECONDS = int(os.getenv('A_SHARE_LLM_TIMEOUT', '240'))


def fetch_context() -> dict[str, Any]:
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT link_id, link_name, score, confidence, upstream_score,
                       downstream_score, news_score, corr_score, best_lag,
                       best_corr, evidence
                FROM link_scores
                WHERE trade_date=%s
                  AND (%s::text IS NULL OR run_id=%s)
                ORDER BY score DESC
                LIMIT 10
                """,
                (TRADE_DATE, RUN_ID, RUN_ID),
            )
            scored = cur.fetchall()
            cur.execute(
                """
                SELECT candidate_id, link_name, upstream_hint, downstream_hint, evidence, llm_reason, seen_count, status
                FROM candidate_links
                WHERE last_seen_date=%s OR status IN ('proposed','watch')
                ORDER BY last_seen_date DESC, seen_count DESC
                LIMIT 12
                """,
                (TRADE_DATE,),
            )
            candidates = cur.fetchall()
            cur.execute(
                """
                SELECT asset_type, name, pct_chg, amplitude, leading_stock, leading_stock_pct, source
                FROM market_quotes
                WHERE trade_date=%s
                  AND (asset_type='commodity' OR abs(COALESCE(pct_chg,0)) >= 1.0 OR COALESCE(amplitude,0) >= 2.0)
                ORDER BY CASE WHEN asset_type='commodity' THEN 0 ELSE 1 END, abs(COALESCE(pct_chg,0)) DESC NULLS LAST
                LIMIT 80
                """,
                (TRADE_DATE,),
            )
            quotes = cur.fetchall()
            cur.execute(
                """
                SELECT title, source, channel, tags
                FROM news_items
                WHERE published_at::date BETWEEN %s::date - interval '1 day' AND %s::date
                ORDER BY published_at DESC NULLS LAST
                LIMIT 80
                """,
                (TRADE_DATE, TRADE_DATE),
            )
            news = cur.fetchall()
            cur.execute(
                """
                SELECT link_id, link_name, confirmed_count, failed_count, inconclusive_count, precision_estimate, best_lag, notes
                FROM link_experience
                ORDER BY updated_at DESC
                LIMIT 20
                """
            )
            exp = cur.fetchall()
    return {
        'scored_links': [
            {
                'link_id': r[0], 'link_name': r[1], 'score': float(r[2]), 'confidence': r[3],
                'sub_scores': {'upstream': float(r[4]), 'downstream': float(r[5]), 'news': float(r[6]), 'corr': float(r[7])},
                'best_lag': r[8], 'best_corr': float(r[9]) if r[9] is not None else None,
                'upstream': (r[10] or {}).get('upstream', [])[:4],
                'downstream': (r[10] or {}).get('downstream', [])[:6],
                'news': (r[10] or {}).get('news', [])[:6],
                'logic': (r[10] or {}).get('logic', ''),
                'experience': (r[10] or {}).get('experience'),
            }
            for r in scored
        ],
        'proposed_candidates': [
            {'candidate_id': r[0], 'link_name': r[1], 'upstream_hint': r[2], 'downstream_hint': r[3], 'evidence': r[4], 'reason': r[5], 'seen_count': r[6], 'status': r[7]}
            for r in candidates
        ],
        'market_quotes': [
            {'asset_type': r[0], 'name': r[1], 'pct_chg': float(r[2] or 0), 'amplitude': float(r[3] or 0), 'leading_stock': r[4], 'leading_stock_pct': float(r[5] or 0), 'source': r[6]}
            for r in quotes
        ],
        'news': [{'title': r[0], 'source': r[1], 'channel': r[2], 'tags': r[3] or []} for r in news],
        'experience': [
            {'link_id': r[0], 'link_name': r[1], 'confirmed': r[2], 'failed': r[3], 'inconclusive': r[4], 'precision': float(r[5]) if r[5] is not None else None, 'best_lag': r[6], 'notes': r[7]}
            for r in exp
        ],
    }


def build_prompt(ctx: dict[str, Any]) -> str:
    data = json.dumps(ctx, ensure_ascii=False, separators=(',', ':'))
    return f"""你是A股“夜盘原材料→A股受影响板块”日报的产业链审核员，重点是强相关与滞后传导。研究对象不是只看下游制造端，而是所有受夜盘原材料影响的A股板块：上游供给/资源端、中游加工材料、下游制造/消费端、以及受同一商品价格或库存周期影响的概念板块。可以大胆使用产业链经验，但必须锚定输入行情/新闻证据，不能编造不存在的当日数据。

任务：
1. 审核 scored_links：判断是否应进入“今日传导复盘”，识别同步大盘波动、关键词误命中、方向逻辑弱、只有题材无价格/库存/利润传导等问题。
2. 如果规则分太差或漏掉链路，请从 market_quotes/news/proposed_candidates 中提出 missing_links/proposed_links，优先考虑：夜盘/当日原材料大波动、A股受影响板块异动、新闻催化、T+0/T+1/T+3/T+5可验证路径。
3. 形成“链路经验沉淀”：对候选链路给出可复用的传导逻辑、建议滞后天数、后验验证指标，并标注它是资源端同向反馈、中游加工价差/库存、还是制造端成本/需求传导。
4. 只输出严格 JSON，不要 markdown，不要 JSON 之外的文字。

审核口径：
- 煤炭开采加工、煤炭行业、有色资源、石油石化、钢铁等供给端/资源端板块，属于研究对象；不要因为“不是下游”而降级或剔除。
- 但必须在 reason/note 中说清楚链路性质，例如“资源端同向反馈”“中游材料价差”“制造端成本压力”，避免把供给端误称为下游。
- 只有商品名和板块关键词完全无产业关系、或只是全市场同步涨跌/纯题材噪声时才 downgrade/reject。

verdict 含义：keep=强证据保留；watch=有证据但不够强；downgrade=弱化；reject=剔除。
调整分：-25 到 +15。若规则漏判但输入证据好，可在 proposed_links 中提出，不要硬把无证据的既有链路加分。

输出 schema：
{{
  "reviews": [{{"link_id":"原link_id", "verdict":"keep|watch|downgrade|reject", "adjustment":数字, "reason":"40字以内，说明资源端/中游/制造端性质"}}],
  "missing_links": [{{"link_name":"上游→受影响A股板块", "reason":"40字以内", "evidence":"输入中可见证据"}}],
  "proposed_links": [{{
    "link_name":"上游→受影响A股板块",
    "upstream_hint":"上游品种/行业",
    "downstream_hint":"受影响板块/概念/行业（字段名沿用downstream_hint）",
    "reason":"为什么值得跟踪，60字以内",
    "suggested_lags":[0,1,3,5中的若干个],
    "validation_metrics":["后验验证指标1","指标2"],
    "confidence":"high|medium|low"
  }}],
  "experience_notes": [{{"link_name":"链路名", "note":"可复用产业链经验，80字以内，说明资源端/中游/制造端性质"}}]
}}

输入数据：
{data}
"""


def extract_json(text: str) -> dict[str, Any]:
    text = re.sub(r'^session_id:.*$', '', text, flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r'\{.*\}', text, flags=re.S)
    if not m:
        raise ValueError('no JSON object found in LLM output')
    return json.loads(m.group(0))


def call_llm(prompt: str) -> dict[str, Any]:
    cmd = ['hermes', 'chat', '-q', prompt, '-m', MODEL, '--provider', PROVIDER, '-Q', '--source', 'a-share-llm-audit']
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise RuntimeError(f'hermes chat failed: {proc.stderr[-1000:]} {proc.stdout[-1000:]}')
    return extract_json(proc.stdout)


def _canonical_link_key(link_name: str, upstream: str = '', downstream: str = '') -> str:
    text=' '.join([upstream or '', downstream or '', link_name or ''])
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
    return re.sub(r'[，,/、|｜]+', '/', text)[:220]


def _candidate_id(link_name: str, upstream: str = '', downstream: str = '') -> str:
    return hashlib.sha1(_canonical_link_key(link_name, upstream, downstream).encode()).hexdigest()[:16]


def write_reviews(result: dict[str, Any]) -> None:
    reviews = result.get('reviews') or []
    missing = result.get('missing_links') or []
    proposed = result.get('proposed_links') or []
    notes = result.get('experience_notes') or []
    missing_json = json.dumps(missing[:8], ensure_ascii=False)
    allowed = {'keep', 'watch', 'downgrade', 'reject'}
    with psycopg.connect(DB_DSN) as conn:
        with conn.cursor() as cur:
            for rv in reviews:
                link_id = rv.get('link_id')
                if not link_id:
                    continue
                verdict = rv.get('verdict') if rv.get('verdict') in allowed else 'watch'
                try:
                    adjustment = float(rv.get('adjustment') or 0)
                except Exception:
                    adjustment = 0.0
                adjustment = max(-25.0, min(15.0, adjustment))
                reason = str(rv.get('reason') or '')[:100]
                cur.execute(
                    """
                    UPDATE link_scores
                    SET llm_model=%s, llm_verdict=%s, llm_adjustment=%s, llm_reason=%s,
                        llm_missing_links=%s::jsonb, llm_reviewed_at=now()
                    WHERE trade_date=%s AND link_id=%s AND (%s::text IS NULL OR run_id=%s)
                    """,
                    (MODEL, verdict, adjustment, reason, missing_json, TRADE_DATE, link_id, RUN_ID, RUN_ID),
                )
            for item in proposed + missing:
                link_name = str(item.get('link_name') or '').strip()[:160]
                if not link_name:
                    continue
                upstream = str(item.get('upstream_hint') or link_name.split('→')[0]).strip()[:80]
                downstream = str(item.get('downstream_hint') or (link_name.split('→')[-1] if '→' in link_name else '')).strip()[:120]
                cid = _candidate_id(link_name, upstream, downstream)
                evidence = {
                    'llm_model': MODEL,
                    'llm_date': TRADE_DATE,
                    'evidence': item.get('evidence'),
                    'suggested_lags': item.get('suggested_lags') or [0,1,3,5],
                    'validation_metrics': item.get('validation_metrics') or [],
                    'confidence': item.get('confidence') or 'medium',
                }
                cur.execute(
                    """
                    INSERT INTO candidate_links (candidate_id, first_seen_date, last_seen_date, link_name, upstream_hint, downstream_hint, evidence, llm_reason, seen_count, status, first_run_id, last_run_id, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,1,'watch',%s,%s,now())
                    ON CONFLICT (candidate_id) DO UPDATE SET last_seen_date=EXCLUDED.last_seen_date, evidence=EXCLUDED.evidence,
                      llm_reason=EXCLUDED.llm_reason,
                      seen_count=CASE WHEN candidate_links.last_run_id IS DISTINCT FROM EXCLUDED.last_run_id THEN candidate_links.seen_count+1 ELSE candidate_links.seen_count END,
                      last_run_id=EXCLUDED.last_run_id,
                      status=CASE WHEN candidate_links.status='promoted' THEN 'promoted' ELSE 'watch' END, updated_at=now()
                    """,
                    (cid, TRADE_DATE, TRADE_DATE, link_name, upstream, downstream, json.dumps(evidence, ensure_ascii=False, default=str), str(item.get('reason') or '')[:240], RUN_ID, RUN_ID),
                )
            for item in notes:
                link_name = str(item.get('link_name') or '').strip()[:160]
                note = str(item.get('note') or '').strip()[:240]
                if not link_name or not note:
                    continue
                note_id = 'llmnote_' + hashlib.sha1((TRADE_DATE + '|' + link_name + '|' + note).encode()).hexdigest()[:16]
                cur.execute(
                    """
                    INSERT INTO link_hypothesis_notes (note_id, link_name, note_date, note, source, evidence, updated_at)
                    VALUES (%s,%s,%s,%s,'llm',%s::jsonb,now())
                    ON CONFLICT (note_id) DO UPDATE SET note=EXCLUDED.note, evidence=EXCLUDED.evidence, updated_at=now()
                    """,
                    (note_id, link_name, TRADE_DATE, note, json.dumps(item, ensure_ascii=False, default=str)),
                )
        conn.commit()


def main() -> int:
    ctx = fetch_context()
    if not ctx['scored_links'] and not ctx['market_quotes']:
        print(json.dumps({'ok': False, 'reason': 'no context', 'trade_date': TRADE_DATE}, ensure_ascii=False))
        return 0
    prompt = build_prompt(ctx)
    result = call_llm(prompt)
    write_reviews(result)
    print(json.dumps({
        'ok': True, 'run_id': RUN_ID, 'model': MODEL, 'trade_date': TRADE_DATE,
        'reviews': len(result.get('reviews') or []),
        'missing_links': len(result.get('missing_links') or []),
        'proposed_links': len(result.get('proposed_links') or []),
        'experience_notes': len(result.get('experience_notes') or []),
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as e:
        print(json.dumps({'ok': False, 'error': type(e).__name__, 'message': str(e)[:500]}, ensure_ascii=False))
        raise SystemExit(1)
