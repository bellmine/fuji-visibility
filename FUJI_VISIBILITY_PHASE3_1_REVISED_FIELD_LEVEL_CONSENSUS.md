# Fuji Visibility Tool — Phase 3.1 Revised
# Field-Level Consensus, Decision Logic Fix & Explainable Status UX

## 0. Why this revision exists

The earlier Phase 3.1 draft focused on improving the explanation of:

```text
数据不足
不符合条件
```

However, before implementing that UX change, a deeper architecture issue was identified.

Current configured models:

```text
auto
jma_seamless
jma_msm
jma_gsm
gfs_seamless
ecmwf_ifs025
```

Current Open-Meteo field availability means that only:

```text
auto
gfs_seamless
```

can normally produce a full Fuji Proxy Score using the current scoring formula.

Other models are structurally partial:

```text
ecmwf_ifs025
    missing visibility

jma_gsm
    missing precipitation_probability
    missing visibility

jma_seamless
    missing precipitation_probability
    missing visibility

jma_msm
    shorter forecast horizon
    and may not expose all fields required by the current Proxy
```

Therefore the current Phase 2 rule:

```text
minimum full models >= 3
```

is effectively impossible to satisfy in normal operation.

This means the current system can become stuck in:

```text
NO QUALIFYING WINDOW
INSUFFICIENT_DATA
```

even when the available evidence is actually strong.

This revision fixes that problem first, then improves the UI explanation.

---

# 1. Main design change

Replace the old decision structure:

```text
Full Proxy consensus
    ->
require >= 3 FULL models
    ->
decision
```

with:

```text
Full Proxy evidence
    +
Field-level consensus
    +
model disagreement checks
    +
reachability
    +
window continuity
    ->
decision
```

The key principle:

> A model does not need to provide every Proxy field to contribute useful evidence.

Examples:

```text
ECMWF may still vote on:
- mid-level cloud
- precipitation
- humidity

JMA may still vote on:
- mid-level cloud
- humidity

GFS / auto may provide:
- full Proxy
- visibility
- cloud
- precipitation
- humidity
```

Partial models must no longer be treated as useless.

---

# 2. Do not weaken the weather standards

This phase must not simply lower thresholds until recommendations appear.

Do not solve the issue by changing:

```text
Proxy threshold 75 -> 60
minimum window 2h -> 1h
```

The fix is:

```text
change evidence aggregation
```

not:

```text
make bad weather qualify
```

---

# 3. Current Proxy formula

Keep the current Fuji Proxy Score.

Current weighting:

```text
visibility              40%
cloud                    30%
precipitation probability 20%
humidity                 10%
```

Do not change the scoring formula in this phase unless required for compatibility.

The Proxy remains a useful summary for models that can compute it.

---

# 4. New evidence layers

For every valid hour, calculate separate evidence groups.

## 4.1 Full Proxy evidence

Models that provide all fields necessary to calculate Proxy.

Current likely members:

```text
auto
gfs_seamless
```

Expose:

```text
full_proxy_model_count
proxy_values
proxy_median
proxy_min
proxy_max
proxy_spread
proxy_stddev
```

---

## 4.2 Mid-cloud consensus

Use all models that provide:

```text
cloud_cover_mid
```

Expose:

```text
mid_cloud_model_count
mid_cloud_values
mid_cloud_median
mid_cloud_min
mid_cloud_max
mid_cloud_stddev
mid_cloud_good_votes
```

This is one of the most important cross-model signals because Mt. Fuji summit elevation intersects the mid-cloud layer.

---

## 4.3 Visibility consensus

Use all models that provide:

```text
visibility
```

Expose:

```text
visibility_model_count
visibility_values_km
visibility_median_km
visibility_min_km
visibility_max_km
visibility_stddev_km
visibility_good_votes
```

It is acceptable if this group currently contains only:

```text
auto
gfs_seamless
```

Do not pretend other models provide visibility.

---

## 4.4 Precipitation consensus

Use all models that provide:

```text
precipitation_probability
```

Expose:

```text
precip_model_count
precip_values
precip_median
precip_max
precip_good_votes
```

Likely members:

```text
auto
gfs_seamless
ecmwf_ifs025
```

---

## 4.5 Humidity consensus

Use all models that provide:

```text
relative_humidity_2m
```

Expose:

```text
humidity_model_count
humidity_values
humidity_median
humidity_max
humidity_good_votes
```

---

# 5. Model capability must remain runtime-driven

Do not hard-code current Open-Meteo limitations as permanent facts.

At runtime:

1. request the model
2. inspect returned variables
3. classify field capabilities
4. let that model contribute wherever valid

A model can be:

```text
FULL_PROXY
PARTIAL_USEFUL
UNAVAILABLE
```

Avoid using only:

```text
FULL
PARTIAL
```

as the main decision meaning.

---

# 6. New model capability output

Suggested structured representation:

```json
{
  "model": "ecmwf_ifs025",
  "status": "PARTIAL_USEFUL",
  "supports": {
    "proxy": false,
    "mid_cloud": true,
    "visibility": false,
    "precipitation": true,
    "humidity": true
  }
}
```

For JMA:

```json
{
  "model": "jma_gsm",
  "status": "PARTIAL_USEFUL",
  "supports": {
    "proxy": false,
    "mid_cloud": true,
    "visibility": false,
    "precipitation": false,
    "humidity": true
  }
}
```

Do not call these models simply "数据不足" in normal UI.

---

# 7. Remove the impossible hard rule

Remove the rule:

```text
full_model_count >= 3
```

as a universal hard gate.

Replace it with:

```text
minimum full Proxy models >= 2
```

because the currently available data source realistically supports two full-score models.

This threshold must remain configurable:

```text
MIN_FULL_PROXY_MODELS=2
```

Do not hard-code it in templates.

---

# 8. Full Proxy disagreement rule

Two full Proxy models are enough only if they are not in serious conflict.

Add configurable thresholds.

Suggested initial values:

```text
MAX_PROXY_SPREAD_FOR_STRONG_SUPPORT = 15
MAX_PROXY_SPREAD_FOR_WEAK_SUPPORT = 25
```

Example:

```text
auto 78
GFS 73
spread 5
```

=> good agreement.

Example:

```text
auto 88
GFS 52
spread 36
```

=> severe disagreement.

Severe disagreement should block a formal recommendation even if the median is high.

---

# 9. Field-level support thresholds

Use field-specific thresholds.

Initial defaults may reuse existing scoring concepts.

Suggested configuration:

```text
GOOD_MID_CLOUD_MAX = 25%
GOOD_VISIBILITY_MIN_KM = 25
GOOD_PRECIP_MAX = 30%
GOOD_HUMIDITY_MAX = 80%
```

These values must be configurable.

Do not hide them in decision.py.

---

# 10. Field consensus labels

For each field produce:

```text
STRONG_SUPPORT
MODERATE_SUPPORT
MIXED
OPPOSED
INSUFFICIENT
```

Suggested generic voting logic:

## STRONG_SUPPORT

```text
at least 3 models available
>= 75% satisfy the good threshold
```

## MODERATE_SUPPORT

```text
at least 2 models available
>= 60% satisfy the good threshold
```

## MIXED

```text
available models disagree materially
```

## OPPOSED

```text
majority fails the good threshold
```

## INSUFFICIENT

```text
too few models for meaningful field consensus
```

Keep thresholds configurable by field if necessary.

---

# 11. Mid-cloud consensus should be especially important

Mt. Fuji visibility can fail even when general weather looks fine if mountain-level cloud blocks the summit.

Therefore decision logic should treat:

```text
mid_cloud consensus
```

as a core evidence dimension.

A candidate should normally not become a strong recommendation when:

```text
mid-cloud consensus = OPPOSED
```

even if the full Proxy median is high.

---

# 12. New hourly decision logic

A reachable hour can be classified as a qualifying candidate when:

```text
reachable == true
AND
full_proxy_model_count >= MIN_FULL_PROXY_MODELS
AND
proxy_median >= MIN_PROXY
AND
full Proxy disagreement is not severe
AND
mid-cloud consensus is not OPPOSED
AND
precipitation consensus is not OPPOSED
```

Visibility support is valuable but may only have two models.

Do not require 3+ visibility models if Open-Meteo structurally cannot provide them.

---

# 13. Recommended confidence logic

Separate:

```text
weather quality
```

from:

```text
evidence confidence
```

Suggested confidence levels:

```text
HIGH
MEDIUM
LOW
INSUFFICIENT
```

## HIGH confidence

Example conditions:

```text
>= 2 full Proxy models
small Proxy spread
mid-cloud STRONG_SUPPORT
precipitation STRONG or MODERATE_SUPPORT
humidity not strongly opposed
forecast stability HIGH or MEDIUM
```

## MEDIUM confidence

Example:

```text
2 full Proxy models
acceptable Proxy agreement
field-level support generally positive
but one or more dimensions have limited model count
```

## LOW confidence

Example:

```text
full Proxy models disagree substantially
or field consensus is mixed
or forecast history is volatile
```

## INSUFFICIENT

Example:

```text
fewer than 2 full Proxy models
or core field data unavailable
```

---

# 14. Recommendation states

The engine should support:

```text
RECOMMENDED
PROMISING
NO CLEAR WINNER
NO QUALIFYING WINDOW
INSUFFICIENT EVIDENCE
```

## RECOMMENDED

A candidate meets weather quality and has adequate evidence.

## PROMISING

Weather signal is good, but confidence is only medium or some evidence is limited.

Chinese:

```text
值得关注
```

or:

```text
有希望
```

Preferred normal UI:

```text
值得关注
```

## NO CLEAR WINNER

Multiple days are too close.

## NO QUALIFYING WINDOW

Weather itself does not meet thresholds.

## INSUFFICIENT EVIDENCE

Not enough core data to make a meaningful judgment.

This should be distinct from bad weather.

---

# 15. Important semantic correction

Do not use:

```text
NO QUALIFYING WINDOW
```

when the actual reason is only:

```text
not enough full models
```

That state should become:

```text
INSUFFICIENT EVIDENCE
```

or:

```text
PROMISING
```

depending on the available field-level evidence.

This is a key behavioral correction.

---

# 16. Example: Tuesday 11:00

Using a state similar to the current live data:

```text
Proxy median:
75.8

Full Proxy models:
2

auto:
78.5

gfs_seamless:
73.2

mid-cloud:
5 models mostly low

precipitation:
3 models available
risk acceptable

visibility:
2 models available
moderate/good
```

Old engine:

```text
INSUFFICIENT_DATA
NO QUALIFYING WINDOW
```

New engine should consider something like:

```text
Weather quality:
GOOD

Full Proxy agreement:
GOOD

Mid-cloud support:
STRONG

Precipitation support:
MODERATE

Confidence:
MEDIUM

Status:
PROMISING / 值得关注
```

Do not automatically promote this to HIGH confidence.

---

# 17. Example: disagreement case

```text
auto Proxy:
88

GFS Proxy:
52

mid-cloud:
models split

precipitation:
mixed
```

Expected:

```text
Weather signal:
mixed

Confidence:
LOW

Status:
NO CLEAR WINNER / not recommended
```

The median alone must not hide disagreement.

---

# 18. Example: clearly bad weather

```text
Proxy median:
55

mid-cloud:
70%

precipitation:
50%

visibility:
8 km
```

Expected:

```text
NO QUALIFYING WINDOW
```

This is genuine weather failure.

---

# 19. Window logic

Keep the existing:

```text
minimum continuous window >= 2 hours
```

for a full recommendation.

But support near-miss / promising windows separately.

Example:

```text
11:00 promising
12:00 promising
```

group as:

```text
11:00–12:00
```

This can be shown as:

```text
值得关注的窗口
```

without calling it formally recommended.

---

# 20. Revised hour status model

Suggested enum:

```text
BEFORE_ARRIVAL
LOW_SCORE
MODEL_DISAGREEMENT
FIELD_CONSENSUS_WEAK
INSUFFICIENT_CORE_DATA
PROMISING
QUALIFIES
OTHER
```

---

# 21. Structured qualification reasons

Each hour should expose reasons.

Example:

```json
{
  "qualification_reasons": [
    "PROXY_OK",
    "FULL_PROXY_MODELS_OK",
    "MID_CLOUD_SUPPORTED",
    "PRECIP_SUPPORTED",
    "CONFIDENCE_MEDIUM"
  ]
}
```

Failure example:

```json
{
  "qualification_reasons": [
    "LOW_PROXY",
    "MID_CLOUD_OPPOSED"
  ]
}
```

Do not reconstruct reasoning from rendered strings.

---

# 22. Chinese user-facing statuses

Use:

```text
BEFORE_ARRIVAL
-> 到达前

LOW_SCORE
-> 评分不足

MODEL_DISAGREEMENT
-> 模型分歧较大

FIELD_CONSENSUS_WEAK
-> 多模型支持不足

INSUFFICIENT_CORE_DATA
-> 核心数据不足

PROMISING
-> 值得关注

QUALIFIES
-> 符合条件
```

For a promising but not fully recommended hour:

```text
值得关注 · 置信度中
```

This is clearer than:

```text
有潜力 · 证据不足
```

because field-level evidence may actually be reasonably strong.

---

# 23. Change normal UI terminology

Replace generic:

```text
数据不足
```

with specific meanings.

Examples:

```text
核心数据不足
模型分歧较大
字段支持不足
```

Do not call every partial model "数据不足".

Use:

```text
部分可用
```

for useful partial models.

---

# 24. Model diagnostics UX

Change model status from:

```text
完整
部分数据
```

to:

```text
完整评分
部分可用
不可用
```

Example:

```text
auto
完整评分

gfs_seamless
完整评分

ecmwf_ifs025
部分可用
可用于：中层云 / 降水 / 湿度
缺少：能见度

jma_gsm
部分可用
可用于：中层云 / 湿度
缺少：降水概率 / 能见度
```

This better reflects actual value.

---

# 25. Add field support matrix

Diagnostics should show a capability matrix.

Example:

```text
模型             综合评分   中层云   能见度   降水   湿度
auto               ✓        ✓       ✓       ✓      ✓
gfs_seamless       ✓        ✓       ✓       ✓      ✓
ecmwf_ifs025       —        ✓       —       ✓      ✓
jma_gsm            —        ✓       —       —      ✓
jma_msm            —        ✓*      —       —      ✓*
jma_seamless       —        ✓       —       —      ✓
```

Use:

```text
*
```

for forecast-horizon-dependent availability if needed.

---

# 26. Hourly table changes

Recommended columns:

```text
时间
综合评分
状态
中层云共识
降水共识
能见度
完整评分模型
```

Example:

```text
10:00  72  评分不足       强支持   强支持   21.6 km   2
11:00  76  值得关注       强支持   中支持   28.2 km   2
12:00  77  值得关注       强支持   边缘     34.9 km   2
```

Do not require the user to infer evidence from raw model counts.

---

# 27. Expandable hour detail

Example:

```text
11:00

综合评分：
76

完整评分模型：
2
auto 78
GFS 73

综合评分模型分歧：
小

中层云：
5 个模型可用
5 个模型支持低云量
强支持

降水：
3 个模型可用
中等支持

能见度：
2 个模型可用
中位数 28.2 km

结论：
值得关注
置信度：中
```

---

# 28. Decision card changes

If there is no formal recommendation but a promising window exists:

```text
暂无正式推荐

值得关注：
8月25日 11:00–12:00

原因：
综合评分达到门槛，
完整评分模型一致性良好，
多模型中层云判断一致偏低，
但整体证据置信度目前仅为中等。
```

Do not display:

```text
暂无符合条件的观景窗口
```

if the real situation is a promising evidence-supported near miss.

---

# 29. Upcoming day cards

Possible states:

## Recommended

```text
推荐
08:00–10:00
置信度：高
```

## Promising

```text
值得关注
11:00–12:00
置信度：中
```

## Bad

```text
暂无理想窗口
```

## Insufficient core data

```text
核心数据不足
暂无法判断
```

---

# 30. Decision ranking

Suggested order:

```text
RECOMMENDED + HIGH confidence
>
RECOMMENDED + MEDIUM confidence
>
PROMISING + MEDIUM confidence
>
PROMISING + LOW confidence
>
NO CLEAR WINNER
>
NO QUALIFYING WINDOW
>
INSUFFICIENT EVIDENCE
```

Exact implementation can remain rules-based.

Do not create a hidden arbitrary mega-score unless necessary.

---

# 31. Stability integration

Keep existing forecast history / drift logic.

Confidence should be reduced when:

```text
trend = VOLATILE
```

or:

```text
recent forecast standard deviation is high
```

Example:

```text
Weather quality:
GOOD

Field consensus:
STRONG

Forecast stability:
LOW

Final confidence:
MEDIUM
```

Do not let a volatile forecast become HIGH confidence.

---

# 32. `auto` model caveat

Open-Meteo `auto` may select or blend underlying models.

Therefore:

```text
auto
```

must not automatically be treated as statistically independent from every explicit model.

For this phase:

- keep `auto` as a full Proxy source
- document the dependency caveat
- do not overstate "2 independent models"

UI wording should say:

```text
2 个完整评分来源
```

rather than:

```text
2 个独立模型
```

unless independence is actually established.

---

# 33. Optional voting configuration

Add:

```text
COUNT_AUTO_IN_FULL_PROXY=true
```

default:

```text
true
```

Future experimentation may set:

```text
false
```

if auto is found to duplicate GFS too heavily.

No need to solve that now.

---

# 34. API additions

Hourly JSON should expose something like:

```json
{
  "proxy": {
    "model_count": 2,
    "median": 75.8,
    "min": 73.2,
    "max": 78.5,
    "spread": 5.3,
    "agreement": "GOOD"
  },

  "field_consensus": {
    "mid_cloud": {
      "model_count": 5,
      "median": 2,
      "support": "STRONG_SUPPORT"
    },
    "precipitation": {
      "model_count": 3,
      "median": 20,
      "support": "MODERATE_SUPPORT"
    },
    "visibility": {
      "model_count": 2,
      "median_km": 28.2,
      "support": "MODERATE_SUPPORT"
    },
    "humidity": {
      "model_count": 5,
      "median": 62,
      "support": "STRONG_SUPPORT"
    }
  },

  "decision_status": "PROMISING",
  "confidence": "MEDIUM",
  "decision_reasons": [
    "PROXY_ABOVE_THRESHOLD",
    "PROXY_MODELS_AGREE",
    "MID_CLOUD_STRONGLY_SUPPORTED",
    "PRECIP_ACCEPTABLE",
    "LIMITED_VISIBILITY_MODEL_COUNT"
  ]
}
```

Preserve existing API fields for backward compatibility.

---

# 35. Decision API compatibility

Do not remove:

```text
status
winner_date
days
best_window
```

Add:

```text
promising_windows
confidence
field_consensus_summary
```

Existing consumers should not break.

---

# 36. CLI updates

CLI output should also benefit from the architecture fix.

Example:

```text
Tue Aug 25

11:00
Proxy: 76
Status: PROMISING
Confidence: MEDIUM

Full Proxy sources: 2
Mid-cloud support: STRONG
Precip support: MODERATE
Visibility sources: 2
```

The CLI and web must use the same domain result.

---

# 37. Revised threshold configuration

Suggested config:

```text
MIN_PROXY=75

MIN_FULL_PROXY_MODELS=2

MAX_PROXY_SPREAD_STRONG=15
MAX_PROXY_SPREAD_WEAK=25

GOOD_MID_CLOUD_MAX=25
GOOD_VISIBILITY_MIN_KM=25
GOOD_PRECIP_MAX=30
GOOD_HUMIDITY_MAX=80

MIN_WINDOW_HOURS=2
```

All should live in existing configuration architecture.

---

# 38. Test cases

## Case A — good full Proxy + strong field support

```text
Proxy:
78, 73

mid-cloud:
5 models all <= 20%

precip:
3 models <= 30%

visibility:
2 models >= 25 km
```

Expected:

```text
PROMISING or QUALIFIES
confidence MEDIUM/HIGH depending stability
```

---

## Case B — good Proxy but severe disagreement

```text
Proxy:
88, 52
```

Expected:

```text
MODEL_DISAGREEMENT
not formally recommended
confidence LOW
```

---

## Case C — low Proxy

```text
Proxy median:
68
```

Expected:

```text
LOW_SCORE
NO QUALIFYING WINDOW
```

even if cloud consensus is good.

---

## Case D — only one full Proxy model

```text
full_proxy_model_count = 1
```

Expected:

```text
INSUFFICIENT_CORE_DATA
```

Do not recommend.

---

## Case E — good Proxy, mid-cloud opposed

```text
Proxy median:
82

mid-cloud:
4/5 models > 60%
```

Expected:

```text
not recommended
```

---

## Case F — good Proxy, field support, volatile history

Expected:

```text
weather quality good
confidence reduced
```

---

## Case G — adjacent promising hours

```text
11:00 PROMISING
12:00 PROMISING
```

Expected:

```text
promising window 11:00–12:00
```

---

# 39. Migration requirement

This phase changes derived decision logic only.

Do not discard existing:

```text
SQLite snapshots
raw JSON
forecast history
```

Historical snapshots should be re-usable under the new consensus calculation where possible.

Consensus and decisions should remain derived data.

---

# 40. UI status mapping

Normal Chinese UI:

```text
RECOMMENDED
-> 推荐

PROMISING
-> 值得关注

NO CLEAR WINNER
-> 暂无明确优选

NO QUALIFYING WINDOW
-> 暂无理想窗口

INSUFFICIENT EVIDENCE
-> 核心数据不足

HIGH confidence
-> 高

MEDIUM confidence
-> 中

LOW confidence
-> 低
```

---

# 41. Do not overstate certainty

The dashboard must not say:

```text
一定能看到富士山
```

Use:

```text
推荐
值得关注
置信度高/中/低
```

This remains forecast evidence, not a guarantee.

---

# 42. Update the original Phase 3.1 UX requirement

Retain the useful explanation improvements from the earlier Phase 3.1 draft:

- specific hour statuses
- no generic `不符合条件` everywhere
- no raw `INSUFFICIENT_DATA` in normal UI
- mobile-friendly explanations
- grouped promising windows
- threshold context
- diagnostics field support matrix

But base all of them on the new field-level consensus architecture.

---

# 43. Implementation order

## Milestone 1 — capability refactor

Deliver:

```text
per-model field capability map
FULL_PROXY / PARTIAL_USEFUL / UNAVAILABLE
```

Acceptance:

ECMWF/JMA partial data remains visible and usable.

---

## Milestone 2 — field-level consensus

Deliver:

```text
mid-cloud consensus
visibility consensus
precipitation consensus
humidity consensus
```

Acceptance:

Each field uses only models that actually provide that variable.

---

## Milestone 3 — replace impossible full-model gate

Deliver:

```text
MIN_FULL_PROXY_MODELS=2
```

and Proxy disagreement logic.

Acceptance:

The engine no longer requires an impossible 3 full models.

---

## Milestone 4 — new confidence and decision states

Deliver:

```text
RECOMMENDED
PROMISING
NO CLEAR WINNER
NO QUALIFYING WINDOW
INSUFFICIENT EVIDENCE
```

Acceptance:

Bad weather and insufficient evidence are distinct states.

---

## Milestone 5 — promising window grouping

Deliver:

```text
adjacent PROMISING hours -> promising window
```

---

## Milestone 6 — web UX update

Deliver:

- `状态` column
- field consensus summaries
- model capability matrix
- promising status
- Chinese explanations
- mobile card updates

---

## Milestone 7 — CLI/API compatibility

Deliver:

- old fields preserved
- new structured evidence fields added
- CLI updated to use same decision logic

---

## Milestone 8 — tests and live validation

Run full offline suite and live dashboard validation.

---

# 44. Definition of Done

Phase 3.1 Revised is complete when:

- [ ] Partial models can contribute field-level evidence.
- [ ] Full Proxy models are no longer the only source of consensus.
- [ ] The impossible universal `>=3 full models` gate is removed.
- [ ] Minimum full Proxy sources is configurable and defaults to 2.
- [ ] Proxy disagreement is explicitly checked.
- [ ] Mid-cloud consensus is calculated independently.
- [ ] Precipitation consensus is calculated independently.
- [ ] Visibility consensus is calculated independently.
- [ ] Humidity consensus is calculated independently.
- [ ] Confidence is separate from weather quality.
- [ ] `PROMISING` exists as a first-class state.
- [ ] `INSUFFICIENT EVIDENCE` is distinct from bad weather.
- [ ] Adjacent promising hours can form a promising window.
- [ ] Normal UI no longer uses generic `数据不足` for useful partial models.
- [ ] Model diagnostics show which fields each model contributes.
- [ ] Desktop and mobile show field-level support clearly.
- [ ] Existing SQLite history is preserved.
- [ ] Existing API fields remain backward compatible.
- [ ] CLI and web use the same domain logic.
- [ ] All offline tests pass.
- [ ] Live validation confirms the system can produce a meaningful result under the current Open-Meteo field structure.

---

# 45. Required live validation scenario

Use current real dates:

```text
2026-08-25
2026-08-26
```

Validate that the system can distinguish cases like:

```text
Tue 11:00
Proxy ~76
2 full Proxy sources
strong mid-cloud support
acceptable precipitation support
```

from:

```text
Tue 08:00
Proxy ~61
```

Expected conceptual difference:

```text
Tue 08:00
评分不足

Tue 11:00
值得关注
置信度：中
```

Do not hard-code these outputs if live data changes.

The point is that the architecture must allow the distinction.

---

# 46. Codex working instructions

1. Read the current consensus.py, decision.py, stability.py, scoring.py, CLI and web view models before changing anything.
2. Do not rewrite the project from scratch.
3. Preserve Phase 1/2 data collection and SQLite history.
4. Replace the impossible full-model gate at the domain layer, not in templates.
5. Treat partial model fields as valid evidence where available.
6. Never synthesize missing visibility or precipitation values.
7. Never assign a Proxy Score to a model missing required Proxy inputs.
8. Keep full Proxy evidence and field-level consensus separate.
9. Add explicit Proxy disagreement logic.
10. Keep weather quality and confidence separate.
11. Add `PROMISING` as a real structured state.
12. Keep normal UI Simplified Chinese.
13. Keep technical model IDs unchanged.
14. Preserve existing API fields and add new ones.
15. Update CLI and web to use the same structured result.
16. Add unit tests for each new evidence path.
17. Run the full existing test suite.
18. Run live consensus/decision/dashboard checks.
19. At completion report:
    - files changed
    - config changes
    - old rule removed
    - new evidence groups
    - new decision states
    - test results
    - live result for Aug 25 / Aug 26
    - whether Tuesday 11:00-like conditions now become PROMISING rather than permanently blocked
    - unresolved model/data limitations

---

# 47. Expected end state

The dashboard should no longer behave like:

```text
4 models are partial
therefore no recommendation can ever exist
```

Instead it should behave like:

```text
2 sources can calculate the full Proxy
5 sources can judge mid-cloud
3 sources can judge precipitation
5 sources can judge humidity
2 sources can judge visibility

These pieces of evidence mostly agree
-> this window is worth watching

or

these pieces conflict
-> confidence is low
```

That is the intended decision model for the actual Open-Meteo data structure.
