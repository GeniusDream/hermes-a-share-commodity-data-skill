# Hermes A股原材料产业链数据包

用于在 Hermes Agent 中部署一套可迁移的 **A股原材料 / 商品夜盘 → 潜在受影响板块** 数据采集、数据库、链路评分、早晚报和 Skill 工作流。

这个仓库从一台已运行的 Hermes 环境导出，目标是让另一台 Hermes 可以通过 `git clone && ./install.sh` 复现同一套数据管线。

## 功能概览

- 采集商品期货、A股指数、A股行业/概念板块、财经新闻和快讯。
- 将行情、新闻、商品窗口涨跌、链路映射、链路评分、LLM 审核结果写入本地 PostgreSQL。
- 生成：
  - **09:30 早报**：夜盘/盘前原材料异动 → 当日A股潜在传导预测。
  - **15:00 晚报**：昨日15:00至今日15:00商品/事件 → 今日A股板块传导复盘。
- 支持历史行情回补、T+N 滞后相关性评分、候选链路观察、候选链路晋升/降级闭环。
- 随仓库导出 Hermes Skill：`a-share-market-data-pipeline`，用于后续让 Hermes 理解和维护这条管线。

## 仓库内容

```text
.
├── install.sh
├── requirements.txt
├── db/
│   ├── docker-compose.yml
│   └── init/
│       ├── 001_schema.sql
│       ├── 002_seed_links.sql
│       ├── 003_llm_audit.sql
│       └── 004_closure_tables.sql
├── scripts/
│   ├── a_share_market_db.py
│   ├── a_share_commodity_universe.py
│   ├── a_share_commodity_signal.py
│   ├── a_share_llm_audit.py
│   ├── a_share_morning_prediction.sh
│   ├── a_share_chain_daily.sh
│   └── a_share_chain_kline_visual.py
├── skills/data-science/a-share-market-data-pipeline/
└── tests/
```

### 核心脚本

| 文件 | 作用 |
|---|---|
| `scripts/a_share_market_db.py` | 主采集器/评分器：schema 初始化、实时采集、历史回补、链路评分、候选链路、验证闭环。 |
| `scripts/a_share_commodity_universe.py` | 商品池、Sina quote/minline 代码、品种族、潜在影响板块映射。 |
| `scripts/a_share_commodity_signal.py` | 商品异动排序：方向性收益、历史分位、趋势质量、研究权重，振幅只作质量修正。 |
| `scripts/a_share_llm_audit.py` | 调用本机 `hermes chat -q` 对候选链路做 LLM 审核，并写回数据库。 |
| `scripts/a_share_morning_prediction.sh` | 09:30 早报入口脚本。 |
| `scripts/a_share_chain_daily.sh` | 15:00 晚报入口脚本。 |
| `scripts/a_share_chain_kline_visual.py` | 生成链路 K 线阶段可视化 HTML。 |

## 数据来源

> 说明：本项目只是采集公开页面/API 返回的数据，并做本地整理、评分和报告生成；请遵守各数据源服务条款和访问频率限制。

### 行情类

| 数据 | 主要来源 | 接口/方式 | 用途 |
|---|---|---|---|
| 国内商品期货实时/夜盘行情 | 新浪财经 | `https://hq.sinajs.cn/list=...` | 商品现价、涨跌、振幅、收盘附近状态。 |
| 国内商品期货分钟线 | 新浪财经 | `InnerFuturesNewService.getMinLine` | 计算报告窗口内夜盘/盘前/日内商品异动。 |
| 国内商品期货日K历史 | 新浪财经 | `InnerFuturesNewService.getDailyKLine` | 历史收益、分位、链路相关性评分。 |
| A股三大指数 | 新浪财经 | `s_sh000001`, `s_sz399001`, `s_sz399006` | 市场基准、市场调整收益。 |
| A股行业/概念资金流 | AKShare 封装 | `stock_fund_flow_industry`, `stock_fund_flow_concept` | 当日板块热度、资金流、板块涨跌快照。 |
| A股板块快照 | AKShare 封装 | `stock_sector_spot` | A股板块当日表现补充。 |
| A股指数历史 | AKShare / 东方财富，腾讯 fallback | `stock_zh_index_daily_em`, `stock_zh_index_daily_tx` | 市场基准历史收益。 |
| A股行业/概念板块历史 | AKShare / 东方财富 | `stock_board_industry_hist_em`, `stock_board_concept_hist_em` | 板块历史收益、链路相关性。 |
| 同花顺行业指数历史 fallback | AKShare / 同花顺 | `stock_board_industry_index_ths` | 当东方财富板块历史接口失败时补充行业板块历史。 |

### 新闻/事件类

| 数据 | 来源 | 接口/方式 | 用途 |
|---|---|---|---|
| 财经新闻 | 东方财富 | `np-listapi.eastmoney.com/comm/web/getNewsByColumns` | 产业链事件、商品和板块逻辑验证。 |
| 快讯 | 华尔街见闻 | `api-prod.wallstreetcn.com/apiv1/content/lives` | 夜盘/盘前/日内突发事件和产业新闻。 |

### LLM 审核

| 数据 | 来源 | 用途 |
|---|---|---|
| 候选链路审核 | 本机 Hermes CLI / 当前 Hermes 默认模型 | 对候选商品→板块链路做同产业族、逻辑方向、证据强弱审核。 |

## 采集窗口与频率

### 推荐定时频率

| 任务 | 建议时间 | 说明 |
|---|---:|---|
| 早报 | A股交易日 09:30 | 分析 **上一A股交易日15:00至当日09:30** 的夜盘/盘前商品异动，输出当日潜在影响板块。 |
| 晚报 | A股交易日 15:00 | 分析 **上一A股交易日15:00至当日15:00** 的商品/新闻/板块反馈，复盘传导链路并验证早报。 |
| 历史回补 | 每次早/晚报前自动触发；也可手动 | 默认回补近约 31 个自然日，用于相关性、历史分位和滞后评分。 |
| LLM 审核 | 晚报流程中自动触发，需本机有 `hermes` CLI | 审核候选链路，避免把无关主题板块误判为商品传导。 |

### 窗口定义

- **早报窗口**：上一A股交易日 `15:00` → 当日 `09:30`。
- **晚报窗口**：上一A股交易日 `15:00` → 当日 `15:00`。
- **A股日盘**：`09:30` → `15:00`。
- 其他时间统一视为夜盘/盘前/盘后窗口，用于商品传导研究。

### 采集方式

`a_share_market_db.py` 支持拆分采集和分析：

```bash
# 只采集入库：行情、新闻、窗口商品异动
python ~/.hermes/scripts/a_share_market_db.py --collect-only

# 只基于数据库已有数据做分析/评分
python ~/.hermes/scripts/a_share_market_db.py --analyze-only

# 测试历史接口健康度
python ~/.hermes/scripts/a_share_market_db.py --test-history --history-days 31

# 回补历史行情
python ~/.hermes/scripts/a_share_market_db.py --backfill-history --history-days 31

# 当日验证 + 候选链路晋升
python ~/.hermes/scripts/a_share_market_db.py --validate-today --promote-candidates
```

## 安装

### 依赖

- macOS / Linux / WSL
- Python 3.9+
- Docker + Docker Compose
- Hermes Agent CLI：可选，但如果要用 Skill、LLM 审核和定时投递，建议安装。

### 一键安装到默认 Hermes

```bash
git clone https://github.com/GeniusDream/hermes-a-share-market-data-pack.git
cd hermes-a-share-market-data-pack
./install.sh --start-db --test
```

### 安装到指定 Hermes profile

```bash
HERMES_HOME=~/.hermes/profiles/your-profile ./install.sh --start-db --test
```

`install.sh` 会执行：

1. 创建 `$HERMES_HOME/venvs/a_share_daily` Python venv。
2. 安装 `requirements.txt`。
3. 复制脚本到 `$HERMES_HOME/scripts/`。
4. 复制数据库 compose 和初始化 SQL 到 `$HERMES_HOME/a_share_daily_db/`。
5. 复制 Skill 到 `$HERMES_HOME/skills/data-science/a-share-market-data-pipeline/`。
6. 可选启动 PostgreSQL。
7. 可选运行单元测试。

## 运行

```bash
# 启动数据库
docker compose -f ~/.hermes/a_share_daily_db/docker-compose.yml up -d

# 历史接口 smoke test
~/.hermes/venvs/a_share_daily/bin/python ~/.hermes/scripts/a_share_market_db.py --test-history --history-days 3

# 早报
~/.hermes/scripts/a_share_morning_prediction.sh

# 晚报
~/.hermes/scripts/a_share_chain_daily.sh
```

## Hermes Cron 示例

可以用 Hermes 自带 cron 做定时投递。不同 Hermes 版本 CLI 参数可能略有差异，若命令不兼容，可运行 `hermes cron create` 交互式创建。

```bash
hermes cron create '30 9 * * 1-5' \
  --name 'A股原材料早报' \
  --script ~/.hermes/scripts/a_share_morning_prediction.sh \
  --no-agent

hermes cron create '0 15 * * 1-5' \
  --name 'A股原材料晚报' \
  --script ~/.hermes/scripts/a_share_chain_daily.sh \
  --no-agent
```

如果通过 Hermes Agent 工具创建，推荐：

- schedule：`30 9 * * 1-5` / `0 15 * * 1-5`
- script：`~/.hermes/scripts/a_share_morning_prediction.sh` / `~/.hermes/scripts/a_share_chain_daily.sh`
- `no_agent=True`
- deliver：按你的 Feishu / Weixin / Telegram / local 目标配置。

## 数据库

默认 DSN：

```text
postgresql://a_share:a_share_daily_local@127.0.0.1:15432/a_share_daily
```

默认 Docker 服务：

```bash
docker compose -f ~/.hermes/a_share_daily_db/docker-compose.yml up -d
```

主要表：

| 表 | 内容 |
|---|---|
| `market_quotes` | 商品、指数、行业/概念板块行情与历史行情。 |
| `commodity_window_moves` | 按早报/晚报窗口固化的商品异动。 |
| `news_items` | 东方财富新闻、华尔街见闻快讯。 |
| `link_mappings` | 官方商品→板块链路映射。 |
| `link_scores` | 当日链路评分、历史相关倾向、LLM 审核字段。 |
| `candidate_links` | 候选链路、观察、晋升/降级状态。 |
| `link_validations` / `link_experience` | 传导验证和经验统计。 |
| `source_status` | 每个数据源的成功/失败、行数、耗时、错误信息。 |

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `HERMES_HOME` | `~/.hermes` | 目标 Hermes home/profile 目录。 |
| `A_SHARE_DAILY_DSN` | bundled PostgreSQL DSN | 自定义 PostgreSQL 连接串。 |
| `A_SHARE_RUN_TYPE` | 脚本设置 | `morning` / `evening` / `collector`。 |
| `A_SHARE_RUN_TRIGGER` | `manual` 或脚本设置 | `manual` / `cron` 等。 |
| `A_SHARE_FETCH_RETRIES` | `3` | 数据源请求重试次数。 |
| `A_SHARE_BOARD_HISTORY_RETRIES` | `2` | 板块历史接口重试次数。 |
| `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` | 空 | 目标环境需要代理时设置。 |
| `NO_PROXY` | 空 | 若 Eastmoney/AKShare 经代理不稳定，可运行时设 `NO_PROXY='*'`。 |

## 迁移说明

本仓库默认不包含本机历史数据库、报告备份或 cron job 配置，只包含：

- schema / seed SQL
- 脚本
- Hermes Skill
- 安装器
- 测试

如果要迁移已有历史样本：

```bash
# 源机器
pg_dump 'postgresql://a_share:a_share_daily_local@127.0.0.1:15432/a_share_daily' > a_share_daily.sql

# 目标机器
psql 'postgresql://a_share:a_share_daily_local@127.0.0.1:15432/a_share_daily' < a_share_daily.sql
```

## 测试

```bash
# 语法检查
bash -n install.sh scripts/*.sh
python3 -m py_compile scripts/*.py

# 单元测试
PYTHONPATH=scripts python3 -m pytest tests -q
```

## 注意事项

- 公开接口可能限流、改版或临时失败；管线会把各源状态写入 `source_status`，报告也应区分实时源失败和历史源失败。
- Eastmoney 历史接口在代理或 IPv6/CDN 路径下可能出现 `RemoteDisconnected` / empty reply；脚本内置 no-proxy 和 fallback，但目标环境仍需实测。
- 报告研究对象是 **板块/行业/概念层级**，不是个股推荐。
- 商品连续合约用于观察长期/窗口走势，不等于真实可交易合约。
- 本项目不构成投资建议。

## License

MIT
