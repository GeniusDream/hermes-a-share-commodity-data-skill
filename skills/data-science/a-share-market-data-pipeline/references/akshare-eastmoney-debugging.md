# AKShare / Eastmoney debugging notes

## Context

This reference captures a tested debugging pattern for A-share data collection where AKShare historical endpoints appeared unreliable during a daily-report pipeline check.

## Observed environment pattern

Global proxy variables may be present:

```text
ALL_PROXY=socks5://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897
HTTP_PROXY=http://127.0.0.1:7897
```

AKShare uses `requests`, so these variables are inherited unless bypassed. Through the proxy, Eastmoney historical endpoints can fail with:

```text
requests.exceptions.ProxyError
RemoteDisconnected('Remote end closed connection without response')
```

## Root-cause split

Do not summarize this as simply "AKShare is broken." In the tested case, the failures split into:

1. Proxy path instability for Eastmoney `push2` / `push2his` endpoints.
2. AKShare wrapper defaults requesting too much historical data, e.g. `beg=19900101&end=20500101`.
3. Board name lookup instability when using Chinese names that require live BK-code mapping.
4. Endpoint-specific parameter differences inside AKShare.

## Working patterns verified

### Index history

Use explicit recent dates:

```python
ak.stock_zh_index_daily_em(
    symbol="sh000001",
    start_date="20260508",
    end_date="20260608",
)
```

This returned 22 rows in the test window from 2026-05-08 to 2026-06-08.

Avoid relying on the default all-history range when only recent data is needed.

### Industry board history

Prefer BK code over Chinese board name:

```python
ak.stock_board_industry_hist_em(
    symbol="BK0437",
    start_date="20260508",
    end_date="20260608",
    period="日k",
    adjust="",
)
```

This returned 22 rows in the test window.

### Concept board history

For AKShare 1.18.64, concept board history uses `daily`, not `日k`:

```python
ak.stock_board_concept_hist_em(
    symbol="BK1408",
    start_date="20260508",
    end_date="20260608",
    period="daily",
    adjust="",
)
```

This returned 22 rows in the test window.

## Direct/no-proxy probe

When proxy variables may interfere, run probes with bypass variables:

```bash
NO_PROXY='*' no_proxy='*' python your_probe.py
```

Also compare with curl:

```bash
curl --noproxy '*' --max-time 15 'https://push2his.eastmoney.com/api/qt/stock/kline/get?...'
```

## Script design recommendations

- Add an Eastmoney no-proxy path for historical data pulls.
- Always pass bounded `start_date` / `end_date` for history.
- Keep local Chinese board name -> BK code mappings for tracked sectors/concepts.
- Add direct Eastmoney `requests` fallback for critical historical endpoints.
- In diagnostics, report rows, date range, attempts, latency, and exact error class.
