# Hermes A 股数据采集 Skill

这是一个面向中国 A 股 / 原材料研究流程的 Hermes skill 与脚本包，定位是：只做数据采集。

本仓库刻意不包含：

- 早报生成；
- 晚报生成；
- 商品 → 板块链路评分；
- LLM 审核；
- 预测验证；
- 自进化 / 候选链路晋升；
- 投资结论。

它只安装一个可复用的 Hermes skill，以及一个原始数据采集脚本，用于从公开行情 / 新闻接口抓取数据，并导出标准化的 JSON、JSONL 或 CSV 行数据。

## 仓库内容

```text
.
├── install.sh
├── requirements.txt
├── scripts/
│   └── a_share_data_collector.py
├── skills/data-science/a-share-data-collection/
│   └── SKILL.md
└── tests/
    └── test_collector_core.py
```

安装后会写入：

```text
$HERMES_HOME/scripts/a_share_data_collector.py
$HERMES_HOME/venvs/a_share_data/bin/python
$HERMES_HOME/skills/data-science/a-share-data-collection/SKILL.md
```

## 数据来源

| 数据类型 | 来源 | 接口 / 封装 | 说明 |
|---|---|---|---|
| 国内商品期货快照 | 新浪财经 | `https://hq.sinajs.cn/list=...` | 采集连续合约快照，如 `nf_AG0`、`nf_PG0`、`nf_LC0`。 |
| 国内商品期货分钟线 | 新浪财经 | `InnerFuturesNewService.getMinLine` | 采集分钟级价格 / 成交量原始行。 |
| 国内商品期货日 K | 新浪财经 | `InnerFuturesNewService.getDailyKLine` | 采集日线 OHLCV；如果有前收盘价，脚本会计算涨跌幅和振幅。 |
| A 股指数快照 | 新浪财经 | `s_sh000001`、`s_sz399001`、`s_sz399006` | 上证指数、深证成指、创业板指。 |
| A 股行业板块日线 | AKShare / 同花顺 | `stock_board_industry_index_ths` | 需要传入准确的同花顺行业板块名称。 |
| A 股概念板块日线 | AKShare / 同花顺 | `stock_board_concept_index_ths` | 需要传入准确的同花顺概念板块名称。 |
| 财经新闻 | 东方财富 | `np-listapi.eastmoney.com/comm/web/getNewsByColumns` | 采集新闻标题、正文、URL 等原始行。 |
| 实时快讯 | 华尔街见闻 | `api-prod.wallstreetcn.com/apiv1/content/lives` | 按配置频道采集实时快讯原始行。 |

## 建议采集频率

本仓库不会自动创建定时任务。你可以接入系统 cron、Hermes cron、Airflow 或其他调度器。常见频率如下：

| 数据集 | 建议频率 |
|---|---:|
| 商品期货快照 | 期货交易时段内每 1-5 分钟一次。 |
| 商品期货分钟线 | 每 5-15 分钟一次，或在目标窗口结束后立即采集一次。 |
| 商品期货日 K | 每日结算 / 收盘后一次，或按需回补历史。 |
| A 股指数快照 | A 股交易时段内每 1-5 分钟一次。 |
| A 股板块日线 | A 股收盘后一次，或按历史区间按需采集。 |
| 东方财富 / 华尔街见闻新闻 | 事件监控场景下每 5-15 分钟一次。 |

使用公开数据源时，请遵守对应网站的服务条款和访问频率限制。

## 安装

```bash
git clone https://github.com/GeniusDream/hermes-a-share-market-data-pack.git
cd hermes-a-share-market-data-pack
./install.sh --test
```

安装到其他 Hermes profile：

```bash
HERMES_HOME=~/.hermes/profiles/your-profile ./install.sh --test
```

## 使用示例

### 采集商品期货快照

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source commodity-quotes \
  --symbols 白银连续,液化石油气连续,碳酸锂连续 \
  --format json
```

### 采集商品期货分钟线

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source commodity-minline \
  --symbols 白银连续,液化石油气连续 \
  --format jsonl \
  --output /tmp/commodity_minline.jsonl
```

### 采集商品期货日 K

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source commodity-daily \
  --symbols 碳酸锂连续,鸡蛋连续 \
  --format csv \
  --output /tmp/commodity_daily.csv
```

### 采集 A 股板块日线 / 当日变化

建议至少包含前一个交易日，这样脚本才能根据前收盘价计算 `pct_chg` 和 `amplitude`。

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source board-history \
  --boards 电池,锂电池概念,贵金属,养鸡 \
  --start-date 2026-06-08 \
  --end-date 2026-06-10 \
  --format json
```

如果自动判断行业 / 概念板块失败，可以显式指定板块类型：

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source board-history \
  --board-type concept \
  --boards 锂电池概念,养鸡 \
  --start-date 2026-06-08 \
  --end-date 2026-06-10
```

### 采集 A 股指数快照

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source index-quotes \
  --format json
```

### 采集新闻

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source news-eastmoney \
  --format jsonl

~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source news-wscn \
  --format jsonl
```

## 命令行参数

```bash
python a_share_data_collector.py \
  --source commodity-quotes|commodity-minline|commodity-daily|index-quotes|board-history|news-eastmoney|news-wscn|all \
  [--symbols 白银连续,nf_PG0,自定义=自定义代码] \
  [--boards 电池,锂电池概念] \
  [--board-type auto|industry|concept] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--format json|jsonl|csv] \
  [--output /path/to/file]
```

## 输出结构

每一行数据会被标准化为同一结构：

```json
{
  "source": "sina",
  "dataset": "commodity_quote",
  "name": "白银连续",
  "code": "nf_AG0",
  "trade_date": "2026-06-11",
  "timestamp": null,
  "open": 123.0,
  "high": 125.0,
  "low": 121.0,
  "close": 124.0,
  "pct_chg": 1.23,
  "amplitude": 3.21,
  "amount": null,
  "volume": null,
  "title": null,
  "body": null,
  "url": null,
  "raw": {}
}
```

其中 `raw` 会保留数据源的原始字段，方便排查接口变化或做下游解析。

## 测试

```bash
bash -n install.sh
python3 -m py_compile scripts/a_share_data_collector.py
PYTHONPATH=scripts python3 -m pytest tests -q
```

也可以用临时 Hermes home 跑安装器自测：

```bash
tmp=$(mktemp -d)
HERMES_HOME="$tmp" ./install.sh --test
```

## 说明

- `nf_AG0` 这类连续合约代码用于连续行情 / 图表数据，不是实际可交易合约代码。
- 公开网页接口可能失败或变更；建议保留 `raw` 原始载荷，并对采集请求做保守重试。
- 本仓库只是数据采集工具，不是投资建议系统。

## License

MIT
