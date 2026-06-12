# Hermes A股原材料产业链数据包

把当前 Hermes 上用于 **A股原材料/商品夜盘 → 潜在受影响板块** 的数据采集、数据库、报告脚本和技能文档导出成可迁移包。

## 包含内容

- `scripts/`
  - `a_share_market_db.py`：PostgreSQL 数据采集、历史回补、链路评分、候选链路闭环。
  - `a_share_commodity_universe.py`：商品池、品种族、潜在影响板块映射。
  - `a_share_commodity_signal.py`：商品异动排序/历史分位/信号质量评分。
  - `a_share_llm_audit.py`：调用 Hermes 对候选链路做 LLM 审核。
  - `a_share_morning_prediction.sh`：09:30 早报脚本。
  - `a_share_chain_daily.sh`：15:00 晚报脚本。
  - `a_share_chain_kline_visual.py`：链路 K 线阶段可视化 HTML。
- `db/`
  - Docker PostgreSQL compose 文件。
  - 初始化 SQL：schema、seed links、LLM audit、closure tables。
- `skills/data-science/a-share-market-data-pipeline/`
  - Hermes skill 文档和 references。
- `install.sh`
  - 一键复制到目标 `$HERMES_HOME`、创建 venv、安装 Python 依赖。

## 一键安装

```bash
git clone <this-repo-url> hermes-a-share-market-data-pack
cd hermes-a-share-market-data-pack
./install.sh --start-db --test
```

如果只是从本机目录安装：

```bash
cd /path/to/hermes-a-share-market-data-pack
./install.sh --start-db --test
```

默认安装到 `~/.hermes`。安装到其他 Hermes profile：

```bash
HERMES_HOME=~/.hermes/profiles/your-profile ./install.sh --start-db --test
```

## 运行

```bash
# 启动数据库
docker compose -f ~/.hermes/a_share_daily_db/docker-compose.yml up -d

# 采集/历史接口 smoke test
~/.hermes/venvs/a_share_daily/bin/python ~/.hermes/scripts/a_share_market_db.py --test-history --history-days 3

# 早报
~/.hermes/scripts/a_share_morning_prediction.sh

# 晚报
~/.hermes/scripts/a_share_chain_daily.sh
```

## 环境变量

- `HERMES_HOME`：目标 Hermes home，默认 `~/.hermes`。
- `A_SHARE_DAILY_DSN`：PostgreSQL DSN；默认匹配 bundled docker compose。
- `A_SHARE_RUN_TYPE`：`morning` / `evening` / `collector`。
- `A_SHARE_RUN_TRIGGER`：`manual` / `cron`。
- `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`：如果目标机器访问 LLM 或部分外网接口需要代理，可按本机习惯设置。
- `NO_PROXY='*'`：部分 Eastmoney/AKShare 历史接口在代理下不稳定，脚本内部已有若干 no-proxy 处理；必要时运行命令前显式设置。

## Hermes cron 示例

安装后可在目标 Hermes 里创建定时任务，例如：

```bash
hermes cron create '30 9 * * 1-5'   --name 'A股原材料早报'   --script a_share_morning_prediction.sh   --no-agent

hermes cron create '0 15 * * 1-5'   --name 'A股原材料晚报'   --script a_share_chain_daily.sh   --no-agent
```

如果 CLI 参数随 Hermes 版本不同，可用 `hermes cron create` 交互式创建，脚本路径填：

- `~/.hermes/scripts/a_share_morning_prediction.sh`
- `~/.hermes/scripts/a_share_chain_daily.sh`

## 注意

- 本包不导出本机数据库历史数据和报告备份，只导出 schema、seed links、脚本和 skill。
- 若需要迁移历史行情样本，可另外用 `pg_dump` / `pg_restore` 迁移 PostgreSQL 数据库。
- 目标机需要 Docker（用于 PostgreSQL）和 Python 3.9+。
