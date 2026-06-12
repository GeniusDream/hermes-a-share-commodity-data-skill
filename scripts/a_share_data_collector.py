#!/usr/bin/env python3
"""Collect A-share, commodity futures, index, and news data as JSON/JSONL/CSV."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Iterable

DEFAULT_COMMODITY_CODES = {
    # Sina domestic continuous futures symbols verified via hq.sinajs.cn.
    # SHFE / INE
    "沪铜连续": "nf_CU0",
    "沪铝连续": "nf_AL0",
    "沪锌连续": "nf_ZN0",
    "沪铅连续": "nf_PB0",
    "沪镍连续": "nf_NI0",
    "沪锡连续": "nf_SN0",
    "氧化铝连续": "nf_AO0",
    "螺纹钢连续": "nf_RB0",
    "线材连续": "nf_WR0",
    "热卷连续": "nf_HC0",
    "不锈钢连续": "nf_SS0",
    "黄金连续": "nf_AU0",
    "白银连续": "nf_AG0",
    "燃油连续": "nf_FU0",
    "沥青连续": "nf_BU0",
    "橡胶连续": "nf_RU0",
    "纸浆连续": "nf_SP0",
    "丁二烯橡胶连续": "nf_BR0",
    "铸造铝合金连续": "nf_AD0",
    "胶版印刷纸连续": "nf_OP0",
    "原油连续": "nf_SC0",
    "20号胶连续": "nf_NR0",
    "低硫燃料油连续": "nf_LU0",
    "国际铜连续": "nf_BC0",
    "集运指数欧线连续": "nf_EC0",

    # GFEX
    "工业硅连续": "nf_SI0",
    "碳酸锂连续": "nf_LC0",
    "多晶硅连续": "nf_PS0",
    "铂连续": "nf_PT0",
    "钯连续": "nf_PD0",

    # DCE
    "豆一连续": "nf_A0",
    "豆二连续": "nf_B0",
    "豆粕连续": "nf_M0",
    "豆油连续": "nf_Y0",
    "棕榈油连续": "nf_P0",
    "玉米连续": "nf_C0",
    "玉米淀粉连续": "nf_CS0",
    "鸡蛋连续": "nf_JD0",
    "生猪连续": "nf_LH0",
    "粳米连续": "nf_RR0",
    "纤维板连续": "nf_FB0",
    "胶合板连续": "nf_BB0",
    "塑料连续": "nf_L0",
    "PP连续": "nf_PP0",
    "PVC连续": "nf_V0",
    "焦炭连续": "nf_J0",
    "焦煤连续": "nf_JM0",
    "铁矿石连续": "nf_I0",
    "乙二醇连续": "nf_EG0",
    "苯乙烯连续": "nf_EB0",
    "液化石油气连续": "nf_PG0",
    "原木连续": "nf_LG0",
    "纯苯连续": "nf_BZ0",

    # CZCE
    "白糖连续": "nf_SR0",
    "棉花连续": "nf_CF0",
    "PTA连续": "nf_TA0",
    "菜油连续": "nf_OI0",
    "甲醇连续": "nf_MA0",
    "玻璃连续": "nf_FG0",
    "菜粕连续": "nf_RM0",
    "油菜籽连续": "nf_RS0",
    "硅铁连续": "nf_SF0",
    "锰硅连续": "nf_SM0",
    "棉纱连续": "nf_CY0",
    "苹果连续": "nf_AP0",
    "红枣连续": "nf_CJ0",
    "尿素连续": "nf_UR0",
    "纯碱连续": "nf_SA0",
    "短纤连续": "nf_PF0",
    "花生连续": "nf_PK0",
    "烧碱连续": "nf_SH0",
    "对二甲苯连续": "nf_PX0",
    "瓶片连续": "nf_PR0",
    "丙烯连续": "nf_PL0",
}

DEFAULT_INDEX_CODES = {
    "上证指数": "s_sh000001",
    "深证成指": "s_sz399001",
    "创业板指": "s_sz399006",
}


@dataclass
class Row:
    source: str
    dataset: str
    name: str | None = None
    code: str | None = None
    trade_date: str | None = None
    timestamp: str | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    pct_chg: float | None = None
    amplitude: float | None = None
    amount: float | None = None
    volume: float | None = None
    title: str | None = None
    body: str | None = None
    url: str | None = None
    raw: dict[str, Any] | None = None


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace(",", ""))
    except Exception:
        return None


def http_get(url: str, *, headers: dict[str, str] | None = None, timeout: int = 15, encoding: str = "utf-8") -> str:
    headers = headers or {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout).read().decode(encoding, errors="replace")


def parse_symbols(text: str | None, defaults: dict[str, str]) -> dict[str, str]:
    """Parse 'name=code,name2=code2' or comma-separated known names/codes."""
    if not text:
        return dict(defaults)
    out: dict[str, str] = {}
    for item in [x.strip() for x in text.split(",") if x.strip()]:
        if "=" in item:
            name, code = item.split("=", 1)
            out[name.strip()] = code.strip()
        elif item in defaults:
            out[item] = defaults[item]
        else:
            out[item] = item
    return out


def collect_sina_commodity_quotes(symbols: dict[str, str]) -> list[Row]:
    codes = list(symbols.values())
    reverse = {v: k for k, v in symbols.items()}
    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    text = http_get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}, encoding="gbk")
    rows: list[Row] = []
    for match in re.finditer(r'var hq_str_([^=]+)="([^"]*)";', text):
        code = match.group(1)
        parts = match.group(2).split(",")
        if len(parts) < 8:
            continue
        name = parts[0] or reverse.get(code) or code
        open_ = _to_float(parts[2])
        high = _to_float(parts[3])
        low = _to_float(parts[4])
        close = _to_float(parts[8] if len(parts) > 8 else parts[6])
        ref = _to_float(parts[7] if len(parts) > 7 else None) or open_
        pct = (close / ref - 1) * 100 if close is not None and ref else None
        amp = (high - low) / ref * 100 if high is not None and low is not None and ref else None
        rows.append(Row(
            source="sina", dataset="commodity_quote", name=name, code=code,
            trade_date=dt.date.today().isoformat(), open=open_, high=high, low=low, close=close,
            pct_chg=pct, amplitude=amp, raw={"parts": parts},
        ))
    return rows


def collect_sina_minline(symbols: dict[str, str]) -> list[Row]:
    rows: list[Row] = []
    for name, code in symbols.items():
        sym = code.replace("nf_", "")
        url = f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_DATA=/InnerFuturesNewService.getMinLine?symbol={sym}"
        try:
            text = http_get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
            payload = text[text.find("(") + 1:text.rfind(")")]
            data = json.loads(payload)
        except Exception as exc:
            rows.append(Row(source="sina", dataset="commodity_minline_error", name=name, code=code, raw={"error": repr(exc)}))
            continue
        for item in data:
            ts = item.get("d") or item.get("date") or item.get("time")
            rows.append(Row(
                source="sina", dataset="commodity_minline", name=name, code=code,
                timestamp=str(ts) if ts else None, close=_to_float(item.get("p") or item.get("price")),
                volume=_to_float(item.get("v") or item.get("volume")), raw=item,
            ))
    return rows


def collect_sina_daily(symbols: dict[str, str]) -> list[Row]:
    rows: list[Row] = []
    for name, code in symbols.items():
        sym = code.replace("nf_", "")
        url = "https://stock2.finance.sina.com.cn/futures/api/json.php/InnerFuturesNewService.getDailyKLine?" + urllib.parse.urlencode({"symbol": sym})
        try:
            data = json.loads(http_get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}))
        except Exception as exc:
            rows.append(Row(source="sina", dataset="commodity_daily_error", name=name, code=code, raw={"error": repr(exc)}))
            continue
        prev_close: float | None = None
        for item in data:
            close = _to_float(item.get("c"))
            high = _to_float(item.get("h"))
            low = _to_float(item.get("l"))
            pct = (close / prev_close - 1) * 100 if close is not None and prev_close else None
            amp = (high - low) / prev_close * 100 if high is not None and low is not None and prev_close else None
            rows.append(Row(
                source="sina", dataset="commodity_daily", name=name, code=code,
                trade_date=str(item.get("d") or item.get("date") or ""), open=_to_float(item.get("o")),
                high=high, low=low, close=close, pct_chg=pct, amplitude=amp,
                volume=_to_float(item.get("v")), raw=item,
            ))
            if close is not None:
                prev_close = close
    return rows


def collect_sina_indices(symbols: dict[str, str]) -> list[Row]:
    reverse = {v: k for k, v in symbols.items()}
    url = "https://hq.sinajs.cn/list=" + ",".join(symbols.values())
    text = http_get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}, encoding="gbk")
    rows: list[Row] = []
    for match in re.finditer(r'var hq_str_([^=]+)="([^"]*)";', text):
        code = match.group(1)
        parts = match.group(2).split(",")
        if len(parts) >= 6:
            rows.append(Row(
                source="sina", dataset="a_share_index_quote", name=parts[0] or reverse.get(code), code=code,
                trade_date=dt.date.today().isoformat(), close=_to_float(parts[1]), pct_chg=_to_float(parts[3]),
                amount=(_to_float(parts[5]) or 0) * 10000 if _to_float(parts[5]) is not None else None,
                raw={"parts": parts},
            ))
    return rows


def collect_board_history(boards: list[str], start_date: str, end_date: str, board_type: str = "auto") -> list[Row]:
    import akshare as ak  # lazy import: only required for board history
    import pandas as pd

    rows: list[Row] = []
    for board in boards:
        attempts: list[tuple[str, Any]] = []
        if board_type in ("industry", "auto"):
            attempts.append(("industry", ak.stock_board_industry_index_ths))
        if board_type in ("concept", "auto"):
            attempts.append(("concept", ak.stock_board_concept_index_ths))
        last_error: Exception | None = None
        for actual_type, fn in attempts:
            try:
                df = fn(symbol=board, start_date=start_date.replace("-", ""), end_date=end_date.replace("-", ""))
                if df is None or df.empty:
                    continue
                df = df.copy().sort_values("日期")
                df["prev_close"] = df["收盘价"].shift(1)
                for _, r in df.iterrows():
                    prev = _to_float(r.get("prev_close"))
                    close = _to_float(r.get("收盘价"))
                    high = _to_float(r.get("最高价"))
                    low = _to_float(r.get("最低价"))
                    rows.append(Row(
                        source="akshare_ths", dataset="a_share_board_daily", name=board, code=actual_type,
                        trade_date=str(pd.to_datetime(r.get("日期")).date()), open=_to_float(r.get("开盘价")),
                        high=high, low=low, close=close,
                        pct_chg=(close / prev - 1) * 100 if close is not None and prev else None,
                        amplitude=(high - low) / prev * 100 if high is not None and low is not None and prev else None,
                        amount=_to_float(r.get("成交额")), volume=_to_float(r.get("成交量")),
                        raw={k: (v.item() if hasattr(v, "item") else v) for k, v in r.to_dict().items()},
                    ))
                last_error = None
                break
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            rows.append(Row(source="akshare_ths", dataset="a_share_board_daily_error", name=board, raw={"error": repr(last_error)}))
    return rows


def collect_eastmoney_news(page_size: int = 50, max_pages: int = 5) -> list[Row]:
    rows: list[Row] = []
    for page in range(1, max_pages + 1):
        url = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?" + urllib.parse.urlencode({
            "client": "web", "biz": "web_news_col", "column": "345", "order": "1",
            "needInteractData": "0", "page_index": str(page), "page_size": str(page_size),
        })
        try:
            data = json.loads(http_get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.eastmoney.com/"}))
            items = data.get("data", {}).get("list", []) or []
        except Exception as exc:
            rows.append(Row(source="eastmoney", dataset="news_error", raw={"page": page, "error": repr(exc)}))
            break
        if not items:
            break
        for item in items:
            rows.append(Row(
                source="eastmoney", dataset="news", timestamp=item.get("showTime"), title=item.get("title"),
                body=item.get("summary"), url=item.get("url"), raw=item,
            ))
    return rows


def collect_wallstreetcn_livenews(channels: Iterable[str] = ("a-stock-channel", "commodity-channel", "oil-channel", "global-channel"), limit_each: int = 30) -> list[Row]:
    rows: list[Row] = []
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*", "Referer": "https://wallstreetcn.com/", "Origin": "https://wallstreetcn.com"}
    for channel in channels:
        url = "https://api-prod.wallstreetcn.com/apiv1/content/lives?" + urllib.parse.urlencode({"channel": channel, "client": "pc", "cursor": "0", "limit": str(limit_each)})
        try:
            data = json.loads(http_get(url, headers=headers))
            items = data.get("data", {}).get("items", []) or []
        except Exception as exc:
            rows.append(Row(source="wallstreetcn", dataset="livenews_error", raw={"channel": channel, "error": repr(exc)}))
            continue
        for item in items:
            ts = item.get("display_time") or 0
            rows.append(Row(
                source="wallstreetcn", dataset="livenews", timestamp=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else None,
                title=(item.get("title") or "").strip() or None, body=(item.get("content_text") or "").strip() or None,
                url=f"https://wallstreetcn.com/livenews/{item.get('id')}", raw=item,
            ))
    return rows


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            pass
    return value


def emit(rows: list[Row], fmt: str, output: str | None) -> None:
    records = [json_safe(asdict(r)) for r in rows]
    if fmt == "json":
        text = json.dumps(records, ensure_ascii=False, indent=2)
    elif fmt == "jsonl":
        text = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + ("\n" if records else "")
    elif fmt == "csv":
        import io
        buf = io.StringIO()
        fieldnames = list(asdict(Row(source="", dataset="")).keys())
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        text = buf.getvalue()
    else:
        raise ValueError(f"unsupported format: {fmt}")
    if output:
        with open(output, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect A-share, commodity futures, index, and news data as JSON/JSONL/CSV.")
    parser.add_argument("--source", choices=["commodity-quotes", "commodity-minline", "commodity-daily", "index-quotes", "board-history", "news-eastmoney", "news-wscn", "all"], default="commodity-quotes")
    parser.add_argument("--symbols", help="Comma-separated known commodity names/codes, or name=code pairs. Defaults to built-in commodity universe.")
    parser.add_argument("--boards", help="Comma-separated A-share board names for --source board-history, e.g. 电池,贵金属,养鸡")
    parser.add_argument("--board-type", choices=["auto", "industry", "concept"], default="auto")
    parser.add_argument("--start-date", default=(dt.date.today() - dt.timedelta(days=5)).isoformat())
    parser.add_argument("--end-date", default=dt.date.today().isoformat())
    parser.add_argument("--format", choices=["json", "jsonl", "csv"], default="json")
    parser.add_argument("--output", help="Output file. Defaults to stdout.")
    args = parser.parse_args(argv)

    rows: list[Row] = []
    commodity_symbols = parse_symbols(args.symbols, DEFAULT_COMMODITY_CODES)
    if args.source in ("commodity-quotes", "all"):
        rows += collect_sina_commodity_quotes(commodity_symbols)
    if args.source in ("commodity-minline", "all"):
        rows += collect_sina_minline(commodity_symbols)
    if args.source in ("commodity-daily", "all"):
        rows += collect_sina_daily(commodity_symbols)
    if args.source in ("index-quotes", "all"):
        rows += collect_sina_indices(DEFAULT_INDEX_CODES)
    if args.source in ("board-history", "all"):
        boards = [x.strip() for x in (args.boards or "").split(",") if x.strip()]
        if not boards and args.source == "board-history":
            parser.error("--boards is required for --source board-history")
        if boards:
            rows += collect_board_history(boards, args.start_date, args.end_date, args.board_type)
    if args.source in ("news-eastmoney", "all"):
        rows += collect_eastmoney_news()
    if args.source in ("news-wscn", "all"):
        rows += collect_wallstreetcn_livenews()

    emit(rows, args.format, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
