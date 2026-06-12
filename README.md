# A 股数据采集 Skill

面向 Hermes 用户的 A 股与商品数据采集 skill，支持公开行情和新闻数据采集，输出 JSON / JSONL / CSV。

## 安装

```bash
git clone https://github.com/GeniusDream/hermes-a-share-market-data-pack.git
cd hermes-a-share-market-data-pack
./install.sh --test
```

指定 Hermes profile：

```bash
HERMES_HOME=~/.hermes/profiles/your-profile ./install.sh --test
```

安装路径：

```text
$HERMES_HOME/scripts/a_share_data_collector.py
$HERMES_HOME/venvs/a_share_data/bin/python
$HERMES_HOME/skills/data-science/a-share-data-collection/SKILL.md
```

## 数据源

| 类型 | 来源 | 参数 |
|---|---|---|
| 商品期货快照 | 新浪财经 | `--source commodity-quotes` |
| 商品期货分钟线 | 新浪财经 | `--source commodity-minline` |
| 商品期货日 K | 新浪财经 | `--source commodity-daily` |
| A 股指数快照 | 新浪财经 | `--source index-quotes` |
| A 股行业 / 概念板块日线 | AKShare / 同花顺 | `--source board-history` |
| 东方财富新闻 | 东方财富 | `--source news-eastmoney` |
| 华尔街见闻快讯 | 华尔街见闻 | `--source news-wscn` |

## 默认商品池

默认覆盖新浪可取到快照的 74 个国内商品连续合约：

```text
沪铜、沪铝、沪锌、沪铅、沪镍、沪锡、氧化铝、螺纹钢、线材、热卷、不锈钢、黄金、白银、燃油、沥青、橡胶、纸浆、丁二烯橡胶、铸造铝合金、胶版印刷纸、原油、20号胶、低硫燃料油、国际铜、集运指数欧线、工业硅、碳酸锂、多晶硅、铂、钯、豆一、豆二、豆粕、豆油、棕榈油、玉米、玉米淀粉、鸡蛋、生猪、粳米、纤维板、胶合板、塑料、PP、PVC、焦炭、焦煤、铁矿石、乙二醇、苯乙烯、液化石油气、原木、纯苯、白糖、棉花、PTA、菜油、甲醇、玻璃、菜粕、油菜籽、硅铁、锰硅、棉纱、苹果、红枣、尿素、纯碱、短纤、花生、烧碱、对二甲苯、瓶片、丙烯
```

不传 `--symbols` 时使用这个默认商品池；传 `--symbols` 时只采指定品种。

## 命令

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source commodity-quotes|commodity-minline|commodity-daily|index-quotes|board-history|news-eastmoney|news-wscn|all \
  [--symbols 白银连续,nf_PG0,自定义=自定义代码] \
  [--boards 电池,锂电池概念] \
  [--board-type auto|industry|concept] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--format json|jsonl|csv] \
  [--output /path/to/file]
```

## 示例

商品快照：

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source commodity-quotes \
  --symbols 白银连续,液化石油气连续,碳酸锂连续 \
  --format json
```

商品分钟线：

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source commodity-minline \
  --symbols 白银连续,液化石油气连续 \
  --format jsonl \
  --output /tmp/commodity_minline.jsonl
```

商品日 K：

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source commodity-daily \
  --symbols 碳酸锂连续,鸡蛋连续 \
  --format csv \
  --output /tmp/commodity_daily.csv
```

板块日线：

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source board-history \
  --boards 电池,锂电池概念,贵金属,养鸡 \
  --start-date 2026-06-08 \
  --end-date 2026-06-10 \
  --format json
```

指数快照：

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source index-quotes \
  --format json
```

新闻：

```bash
~/.hermes/venvs/a_share_data/bin/python \
  ~/.hermes/scripts/a_share_data_collector.py \
  --source news-eastmoney \
  --format jsonl
```

## 输出字段

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

## 测试

```bash
bash -n install.sh
python3 -m py_compile scripts/a_share_data_collector.py
PYTHONPATH=scripts python3 -m pytest tests -q
```

```bash
tmp=$(mktemp -d)
HERMES_HOME="$tmp" ./install.sh --test
```

## License

MIT
