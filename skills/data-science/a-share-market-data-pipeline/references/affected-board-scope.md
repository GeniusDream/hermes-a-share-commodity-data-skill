# A-share raw-material affected-board scope

Session lesson: the report research object is not only downstream manufacturing. It is all A-share boards materially affected by night-session/raw-material moves.

## Scope

Include and label all of these when evidence supports them:

- Upstream supply/resource feedback: coal mining/coal industry, oil & gas / petroleum & petrochemical, nonferrous resources, rare-earth resources.
- Midstream processing/materials: steel, chemical materials, coal chemicals, glass, metal new materials, electronic chemicals.
- Downstream manufacturing/consumption: machinery, infrastructure equipment, auto parts, home appliances, packaging, chemical fiber, consumer manufacturing.
- Related concept/theme boards when the raw-material move plausibly changes price, inventory, margin, risk appetite, or industry narrative.

## Reporting rule

Do not reject a board just because it is not downstream. Instead, classify the pathway type in the sentence:

- `资源端/供给端同向反馈`
- `中游材料/加工价差`
- `制造端成本压力` or `制造端成本缓和`
- `需求端/题材端验证`
- `宏观/避险/风险偏好传导`

Example correction:

- Bad: `黑色链 → 基建/机械/汽车/家电` followed by `煤炭开采加工` as if coal were downstream evidence.
- Better: `黑色原料 → 煤炭/钢铁/基建机械/制造`; explain coal as `资源端/供给端同向反馈`, steel as `材料端`, and machinery/auto/home appliances as `制造端成本或需求验证`.

## LLM audit/self-evolution rule

- LLM audit prompts should explicitly say supply/resource boards belong in scope and must not be downgraded solely for not being downstream.
- Candidate discovery should still require an industry-family relationship between the commodity and the board/news. Broad keyword matching that only sees the upstream name can produce noise such as `焦煤 → 半导体/其他电子`.
- Candidate promotion should record whether the pathway is resource-side, midstream, manufacturing-side, concept/theme, or macro/risk-sentiment.

## Naming rule

Prefer `夜盘原材料 → A股受影响板块` over `原材料-下游产业链` when the report includes supply-side and midstream boards.
