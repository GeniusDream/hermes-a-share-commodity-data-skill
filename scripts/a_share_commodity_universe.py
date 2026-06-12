#!/usr/bin/env python3
"""Commodity universe for A-share raw-material transmission reports.

Design:
- core=True: main morning/evening conclusion pool.
- core=False: expanded anomaly radar / candidate discovery pool. These can enter
  formal transmission review only after same-family A-share feedback, LLM review,
  and later validation make the chain strong enough.
"""

CORE_DOMESTIC = [
    {'symbol':'CU0','code':'nf_CU0','name':'铜连续','family':'有色','impact':'有色资源、金属新材料、电力设备、机器人电机、线缆、汽车零部件','core':True},
    {'symbol':'AL0','code':'nf_AL0','name':'铝连续','family':'有色','impact':'有色资源、汽车轻量化、家电、光伏边框','core':True},
    {'symbol':'RB0','code':'nf_RB0','name':'螺纹钢连续','family':'黑色','impact':'钢铁/黑色供给端、基建、地产链、工程机械','core':True},
    {'symbol':'HC0','code':'nf_HC0','name':'热轧卷板连续','family':'黑色','impact':'钢铁/黑色供给端、汽车板材、家电、机械','core':True},
    {'symbol':'I0','code':'nf_I0','name':'铁矿石连续','family':'黑色','impact':'钢铁成本、黑色链利润','core':True},
    {'symbol':'JM0','code':'nf_JM0','name':'焦煤连续','family':'黑色','impact':'煤炭供给端、钢铁成本、黑色链情绪','core':True},
    {'symbol':'SA0','code':'nf_SA0','name':'纯碱连续','family':'建材光伏','impact':'光伏玻璃、玻璃基板、浮法玻璃成本','core':True},
    {'symbol':'FG0','code':'nf_FG0','name':'玻璃连续','family':'建材光伏','impact':'玻璃基板、光伏玻璃、地产竣工链','core':True},
    {'symbol':'SC0','code':'nf_SC0','name':'上海原油连续','family':'能源化工','impact':'石化、化工、交运、消费制造成本','core':True},
    {'symbol':'MA0','code':'nf_MA0','name':'甲醇连续','family':'能源化工','impact':'煤化工、化纤、包装、化工品成本','core':True},
]

EXPANDED_DOMESTIC = [
    # 有色/新能源金属/贵金属
    {'symbol':'ZN0','code':'nf_ZN0','name':'沪锌连续','family':'有色','impact':'有色资源、镀锌钢材、汽车/家电金属件','core':False},
    {'symbol':'PB0','code':'nf_PB0','name':'铅连续','family':'有色','impact':'有色资源、铅酸电池、再生金属','core':False},
    {'symbol':'NI0','code':'nf_NI0','name':'镍连续','family':'有色','impact':'不锈钢、新能源电池、合金材料','core':False},
    {'symbol':'SN0','code':'nf_SN0','name':'锡连续','family':'有色','impact':'小金属、电子焊料、半导体材料','core':False},
    {'symbol':'AO0','code':'nf_AO0','name':'氧化铝连续','family':'有色','impact':'铝产业链、电解铝成本','core':False},
    {'symbol':'SS0','code':'nf_SS0','name':'不锈钢连续','family':'黑色','impact':'不锈钢、特钢、家电/机械金属件','core':False},
    {'symbol':'SI0','code':'nf_SI0','name':'工业硅连续','family':'新能源材料','impact':'多晶硅、有机硅、光伏材料','core':False},
    {'symbol':'LC0','code':'nf_LC0','name':'碳酸锂连续','family':'新能源材料','impact':'锂电材料、新能源车、电池产业链','core':False},
    {'symbol':'AU0','code':'nf_AU0','name':'黄金连续','family':'贵金属','impact':'贵金属、避险情绪、黄金珠宝','core':False},
    {'symbol':'AG0','code':'nf_AG0','name':'白银连续','family':'贵金属','impact':'贵金属、光伏银浆、工业金属情绪','core':False},
    # 黑色/铁合金
    {'symbol':'J0','code':'nf_J0','name':'焦炭连续','family':'黑色','impact':'煤焦钢、钢铁成本、煤化工','core':False},
    {'symbol':'SF0','code':'nf_SF0','name':'硅铁连续','family':'黑色','impact':'铁合金、钢铁辅料、硅基材料','core':False},
    {'symbol':'SM0','code':'nf_SM0','name':'锰硅连续','family':'黑色','impact':'铁合金、钢铁辅料、锰系材料','core':False},
    # 能源/化工
    {'symbol':'FU0','code':'nf_FU0','name':'燃料油连续','family':'能源化工','impact':'炼化、航运燃料、石化成本','core':False},
    {'symbol':'LU0','code':'nf_LU0','name':'低硫燃料油连续','family':'能源化工','impact':'低硫燃料油、航运、炼化价差','core':False},
    {'symbol':'BU0','code':'nf_BU0','name':'沥青连续','family':'能源化工','impact':'道路基建、防水材料、石化库存','core':False},
    {'symbol':'PG0','code':'nf_PG0','name':'液化石油气连续','family':'能源化工','impact':'LPG、燃气、PDH化工、民用能源','core':False},
    {'symbol':'TA0','code':'nf_TA0','name':'PTA连续','family':'能源化工','impact':'涤纶长丝、化纤、纺织服装','core':False},
    {'symbol':'PX0','code':'nf_PX0','name':'对二甲苯连续','family':'能源化工','impact':'PTA、聚酯、化纤产业链','core':False},
    {'symbol':'EG0','code':'nf_EG0','name':'乙二醇连续','family':'能源化工','impact':'聚酯、化纤、包装材料','core':False},
    {'symbol':'EB0','code':'nf_EB0','name':'苯乙烯连续','family':'能源化工','impact':'塑料制品、家电外壳、化工新材料','core':False},
    {'symbol':'V0','code':'nf_V0','name':'PVC连续','family':'能源化工','impact':'PVC、建材管材、地产竣工链','core':False},
    {'symbol':'PP0','code':'nf_PP0','name':'聚丙烯连续','family':'能源化工','impact':'塑料制品、包装、汽车内饰','core':False},
    {'symbol':'L0','code':'nf_L0','name':'塑料连续','family':'能源化工','impact':'塑料制品、包装、家电消费','core':False},
    {'symbol':'PF0','code':'nf_PF0','name':'短纤连续','family':'能源化工','impact':'化纤、纺织服装、无纺布','core':False},
    {'symbol':'UR0','code':'nf_UR0','name':'尿素连续','family':'农化','impact':'化肥、农业种植、煤化工','core':False},
    {'symbol':'SH0','code':'nf_SH0','name':'烧碱连续','family':'能源化工','impact':'氯碱、氧化铝、化工原料','core':False},
    {'symbol':'BR0','code':'nf_BR0','name':'丁二烯橡胶连续','family':'橡胶','impact':'轮胎、汽车零部件、合成橡胶','core':False},
    {'symbol':'RU0','code':'nf_RU0','name':'天然橡胶连续','family':'橡胶','impact':'轮胎、汽车零部件、橡胶制品','core':False},
    {'symbol':'NR0','code':'nf_NR0','name':'20号胶连续','family':'橡胶','impact':'轮胎、橡胶制品、汽车链','core':False},
    # 农产品/消费原料
    {'symbol':'M0','code':'nf_M0','name':'豆粕连续','family':'农产品','impact':'饲料、养殖、猪鸡产业链','core':False},
    {'symbol':'RM0','code':'nf_RM0','name':'菜粕连续','family':'农产品','impact':'饲料、水产养殖、油脂油料','core':False},
    {'symbol':'Y0','code':'nf_Y0','name':'豆油连续','family':'农产品','impact':'食用油、食品加工、油脂油料','core':False},
    {'symbol':'P0','code':'nf_P0','name':'棕榈油连续','family':'农产品','impact':'食用油、食品加工、日化油脂','core':False},
    {'symbol':'OI0','code':'nf_OI0','name':'菜油连续','family':'农产品','impact':'食用油、食品加工、油脂油料','core':False},
    {'symbol':'A0','code':'nf_A0','name':'豆一连续','family':'农产品','impact':'大豆种植、食品加工、油脂油料','core':False},
    {'symbol':'B0','code':'nf_B0','name':'豆二连续','family':'农产品','impact':'进口大豆、饲料、油脂油料','core':False},
    {'symbol':'C0','code':'nf_C0','name':'玉米连续','family':'农产品','impact':'种业、饲料、淀粉加工','core':False},
    {'symbol':'CS0','code':'nf_CS0','name':'淀粉连续','family':'农产品','impact':'玉米深加工、食品配料、造纸包装','core':False},
    {'symbol':'CF0','code':'nf_CF0','name':'棉花连续','family':'农产品','impact':'纺织服装、棉纺、消费原料','core':False},
    {'symbol':'SR0','code':'nf_SR0','name':'白糖连续','family':'农产品','impact':'糖业、食品饮料、消费原料','core':False},
    {'symbol':'AP0','code':'nf_AP0','name':'苹果连续','family':'农产品','impact':'水果消费、食品加工','core':False},
    {'symbol':'PK0','code':'nf_PK0','name':'花生连续','family':'农产品','impact':'油脂油料、休闲食品','core':False},
    {'symbol':'LH0','code':'nf_LH0','name':'生猪连续','family':'农产品','impact':'猪养殖、肉制品、饲料','core':False},
    {'symbol':'JD0','code':'nf_JD0','name':'鸡蛋连续','family':'农产品','impact':'蛋鸡养殖、食品消费','core':False},
]

INTERNATIONAL = [
    {'code':'hf_CAD','name':'伦铜','family':'有色','impact':'有色资源、全球制造业风险偏好、铜加工','core':True},
    {'code':'hf_AHD','name':'伦铝','family':'有色','impact':'有色资源、汽车轻量化、家电','core':True},
    {'code':'hf_NID','name':'伦镍','family':'有色','impact':'不锈钢、新能源材料、合金','core':True},
    {'code':'hf_CL','name':'纽约原油','family':'能源化工','impact':'石化、化工、全球风险偏好','core':True},
    {'code':'hf_GC','name':'黄金','family':'贵金属','impact':'贵金属、避险情绪','core':True},
]

DOMESTIC = CORE_DOMESTIC + EXPANDED_DOMESTIC
ALL_QUOTE_CODES = [x['code'] for x in DOMESTIC] + [x['code'] for x in INTERNATIONAL]
ALL_MINLINE_SYMBOLS = [(x['symbol'], x['name']) for x in DOMESTIC]
CORE_MINLINE_SYMBOLS = [(x['symbol'], x['name']) for x in CORE_DOMESTIC]
IMPACT_MAP = {x['name']: x['impact'] for x in DOMESTIC + INTERNATIONAL}
FAMILY_MAP = {x['name']: x['family'] for x in DOMESTIC + INTERNATIONAL}
CORE_NAMES = {x['name'] for x in CORE_DOMESTIC} | {x['name'] for x in INTERNATIONAL if x.get('core')}
EXPANDED_NAMES = {x['name'] for x in EXPANDED_DOMESTIC}

# Sina occasionally returns slightly different display names for the same symbols.
ALIASES = {
    '沪铜连续':'铜连续',
    '沪铝连续':'铝连续',
    '原油连续':'上海原油连续',
    '热卷连续':'热轧卷板连续',
    '菜油连续':'菜籽油连续',
}

def normalize_name(name: str) -> str:
    return ALIASES.get(name, name)

def impact_for(name: str) -> str:
    return IMPACT_MAP.get(normalize_name(name), IMPACT_MAP.get(name, '相关产业链'))

def family_for(name: str) -> str:
    return FAMILY_MAP.get(normalize_name(name), FAMILY_MAP.get(name, '其他'))

def is_core_name(name: str) -> bool:
    return normalize_name(name) in CORE_NAMES

def is_expanded_name(name: str) -> bool:
    return normalize_name(name) in EXPANDED_NAMES

FAMILY_KEYWORDS = {
    '有色': {
        'upstream': r'铜|铝|锌|铅|镍|锡|氧化铝|不锈钢|有色|金属',
        'downstream': r'有色|小金属|稀土|金属|电力设备|电机|电网|机器人|汽车|线缆|不锈钢|合金|电池|新能源',
    },
    '新能源材料': {
        'upstream': r'工业硅|碳酸锂|锂|硅',
        'downstream': r'锂|电池|新能源|光伏|多晶硅|有机硅|电力设备|汽车|储能',
    },
    '贵金属': {
        'upstream': r'黄金|白银|贵金属',
        'downstream': r'黄金|贵金属|珠宝|白银|光伏银浆|避险',
    },
    '黑色': {
        'upstream': r'焦煤|焦炭|铁矿|螺纹|热轧|热卷|钢|硅铁|锰硅|不锈钢',
        'downstream': r'煤炭|钢铁|黑色|基建|工程机械|机械|汽车|家电|建材|地产|铁合金|特钢',
    },
    '建材光伏': {
        'upstream': r'玻璃|纯碱',
        'downstream': r'玻璃|建材|光伏|地产|装修|建筑材料',
    },
    '能源化工': {
        'upstream': r'原油|燃料油|低硫燃料油|沥青|液化石油气|LPG|甲醇|PTA|对二甲苯|PX|乙二醇|苯乙烯|PVC|聚丙烯|塑料|短纤|烧碱|化工|石化',
        'downstream': r'石油|油气|化工|石化|化纤|塑料|包装|交运|煤化工|磷化工|氟化工|涤纶|纺织|建材|管材|炼化|燃气|航运',
    },
    '农化': {
        'upstream': r'尿素|化肥|农化',
        'downstream': r'化肥|农化|农业|种植|煤化工|农资',
    },
    '橡胶': {
        'upstream': r'橡胶|20号胶|丁二烯',
        'downstream': r'轮胎|橡胶|汽车零部件|汽车|合成橡胶',
    },
    '农产品': {
        'upstream': r'豆粕|菜粕|豆油|棕榈油|菜油|豆一|豆二|玉米|淀粉|棉花|白糖|苹果|花生|生猪|鸡蛋|农产品',
        'downstream': r'农业|种植|饲料|养殖|猪|鸡|食品|饮料|食用油|油脂|糖|棉|纺织|服装|种业|肉制品',
    },
}
