# A 股与商品数据采集 Skill

Hermes skill for collecting Chinese commodity futures, A-share index, A-share board, and market news data for raw-material-to-equity research workflows.

## 支持的数据

| 研究对象 | 当前支持 | 覆盖范围 |
|---|---|---|
| 国内商品期货 | 74 个国内商品连续合约 | 国内商品连续合约快照、分钟线、日 K |
| 商品行情 | 快照、分钟线、日 K | 来自新浪公开接口，分钟线可用性依赖源站 |
| A 股板块 | 同花顺行业板块、同花顺概念板块 | 板块名称列表、关键词搜索、日线行情 |
| A 股指数 | 上证指数、深证成指、创业板指 | 三个主要宽基指数快照 |
| 新闻 / 快讯 | 东方财富财经新闻、华尔街见闻快讯 | 标题、正文摘要、URL、时间戳和原始载荷 |

## 数据源

| 数据 | 来源 |
|---|---|
| 商品期货快照 | 新浪财经 |
| 商品期货分钟线 | 新浪财经 |
| 商品期货日 K | 新浪财经 |
| A 股指数快照 | 新浪财经 |
| A 股行业 / 概念板块日线 | AKShare / 同花顺 |
| A 股行业 / 概念板块名称列表 | AKShare / 同花顺 |
| 财经新闻 | 东方财富 |
| 实时快讯 | 华尔街见闻 |

## 能力示例

```text
采集白银连续、碳酸锂连续、液化石油气连续的最新快照，输出 JSON。
```

```text
搜索包含“锂”的 A 股行业和概念板块。
```

```text
采集电池、锂电池概念、贵金属最近一周的板块日线，保存成 CSV。
```

```text
采集碳酸锂连续日 K 和锂电池概念板块日线，用来研究商品和 A 股板块关系。
```

```text
列出当前支持的同花顺行业板块。
```

## 默认商品池

默认覆盖新浪可取到快照的 74 个国内商品连续合约。

| 类别 | 品种 |
|---|---|
| 有色 / 贵金属 | 沪铜、沪铝、沪锌、沪铅、沪镍、沪锡、氧化铝、黄金、白银、国际铜、铂、钯 |
| 黑色 | 螺纹钢、线材、热卷、不锈钢、铁矿石、焦炭、焦煤、硅铁、锰硅 |
| 能源 / 化工 | 原油、燃油、低硫燃料油、液化石油气、沥青、甲醇、PTA、PVC、PP、塑料、乙二醇、苯乙烯、纯苯、尿素、纯碱、短纤、烧碱、对二甲苯、瓶片、丙烯、橡胶、20号胶、丁二烯橡胶、纸浆 |
| 新能源材料 | 碳酸锂、工业硅、多晶硅 |
| 农产品 / 消费原料 | 豆一、豆二、豆粕、豆油、棕榈油、玉米、玉米淀粉、鸡蛋、生猪、粳米、白糖、棉花、棉纱、菜油、菜粕、油菜籽、苹果、红枣、花生 |
| 其他 | 纤维板、胶合板、原木、铸造铝合金、胶版印刷纸、玻璃、集运指数欧线 |

## A 股板块覆盖

当前 A 股板块数据基于同花顺行业 / 概念板块。

建议流程：

1. 搜索板块名。
2. 采集对应板块日线。
3. 结合商品日 K / 分钟线进行后续研究。

板块名称需要与同花顺 / AKShare 返回名称一致。该 skill 支持板块名搜索，可用于确认准确名称。

## 输出字段

采集结果统一输出为 JSON、JSONL 或 CSV，常见字段包括：

| 字段 | 含义 |
|---|---|
| `source` | 数据源 |
| `dataset` | 数据集类型 |
| `name` | 商品、指数、板块或新闻名称 |
| `code` | 数据源代码 |
| `trade_date` | 交易日 |
| `timestamp` | 时间戳 |
| `open` / `high` / `low` / `close` | 行情价格字段 |
| `pct_chg` | 涨跌幅 |
| `amplitude` | 振幅 |
| `amount` / `volume` | 成交额 / 成交量 |
| `title` / `body` / `url` | 新闻字段 |
| `raw` | 源站原始载荷 |

## 功能范围

该 skill 提供以下数据采集能力：

- 采集国内商品连续合约快照、分钟线和日 K；
- 采集 A 股指数快照；
- 搜索同花顺行业 / 概念板块名称；
- 采集同花顺行业 / 概念板块日线；
- 采集东方财富财经新闻；
- 采集华尔街见闻实时快讯；
- 输出 JSON、JSONL 或 CSV。

## 安装

```bash
git clone https://github.com/GeniusDream/hermes-a-share-commodity-data-skill.git
cd hermes-a-share-commodity-data-skill
./install.sh --test
```

指定 Hermes profile：

```bash
HERMES_HOME=~/.hermes/profiles/your-profile ./install.sh --test
```

安装后会写入：

```text
$HERMES_HOME/scripts/a_share_data_collector.py
$HERMES_HOME/venvs/a_share_data/bin/python
$HERMES_HOME/skills/data-science/a-share-data-collection/SKILL.md
```

## License

MIT
