# Fuji Visibility Tool — Phase 3.2
# Recenter on Hourly Visibility Browsing

## 0. Background

The original product problem was simple:

- `fuji-san.info` is useful, but mainly gives coarse AM / PM judgments.
- `Is It Visible` appears to use hourly data, but the user can only conveniently see a small number of "best" hours.
- The goal of this project is therefore to expose the **full hourly picture** for Mt. Fuji viewing, especially morning hours, so the user can compare days and choose a time themselves.

Phase 3.1 added useful multi-model evidence, field-level consensus, confidence states, and `PROMISING` handling.

That work should be kept.

However, Phase 3.2 must correct the product emphasis:

> This service is primarily an hourly Mt. Fuji visibility browser, not an expert system that decides whether the user is allowed to go.

The user should be able to open the dashboard and answer within seconds:

1. Which day looks better?
2. Which hours look best?
3. Are the forecasts getting better or worse?
4. Are the models badly disagreeing?

Everything else is secondary.

---

# 1. Product principle

The dashboard should present evidence first and judgment second.

Primary:

```text
all hourly values
hourly Proxy
best hours
best continuous time block
forecast drift
```

Secondary:

```text
model disagreement
field-level consensus
confidence
diagnostics
```

The decision engine must never hide, suppress, or visually invalidate useful hourly data.

---

# 2. Preserve Phase 3.1 internals

Do NOT remove the Phase 3.1 architecture.

Keep:

```text
field_consensus
proxy agreement
PROMISING
confidence
decision_reasons
model capability handling
FULL_PROXY / partial-useful logic
```

These remain useful for:

- warnings
- diagnostics
- future experiments
- API clients

Phase 3.2 is mainly a **product / presentation / ranking change**.

Avoid another large backend rewrite unless required.

---

# 3. Stop using qualification as the main UI concept

The homepage currently gives too much importance to states such as:

```text
RECOMMENDED
PROMISING
LOW_SCORE
FIELD_CONSENSUS_WEAK
NO QUALIFYING WINDOW
```

These may remain internally, but they should no longer dominate the dashboard.

Do not make the user think:

> "Why is the system refusing to qualify this hour?"

The user's core need is:

> "Show me every hour and tell me which ones look best."

---

# 4. Replace the main decision card

The large primary card should no longer primarily say:

```text
暂无符合条件的观景窗口
```

or:

```text
暂无正式推荐
```

Replace it with a neutral summary card.

Suggested title:

```text
当前最佳时段
```

Example:

```text
8月25日 周二
11:00–12:00

连续 2 小时平均评分：76

11:00  76
12:00  77

模型提示：
12:00 降水风险偏高
```

If every hour is poor, still show the best available block:

```text
当前最佳时段
8月27日 08:00–09:00
平均评分：37

整体条件较差
```

The page should always answer "best among available options", even when the best is not good.

This is ranking, not recommendation.

---

# 5. Always show all requested hours

This is the original reason for the project.

For the configured range:

```text
05:00–12:00
```

show every hour.

Never reduce the normal dashboard to only:

```text
Top 3
qualifying hours
recommended hours
```

The user must be able to see the complete hourly curve.

---

# 6. Primary hourly table

The main table should prioritize the fields the user actually reads.

Recommended desktop order:

```text
时间
综合评分
中层云量
能见度
降水概率
趋势
提示
```

Example:

```text
08:00   61   0%   8.8 km   0%    →
09:00   67   0%  14.9 km   0%    ↑
10:00   72   0%  21.6 km   8%    ↑
11:00   76   2%  28.2 km  20%    ↑    最佳时段
12:00   77   7%  34.9 km  33%    →    降水风险
```

Exact values are live data and must not be hard-coded.

---

# 7. Proxy remains the main summary number

Keep the existing transparent Fuji Proxy.

Do not replace the homepage with a complicated field-consensus score.

The Proxy is useful because it lets the user quickly scan:

```text
61
67
72
76
77
```

and understand the progression.

Field-level model data should explain or warn about the Proxy, not replace it.

---

# 8. Highlight best hours without hiding others

For every selected day:

- visually highlight the highest-scoring reachable hour
- optionally highlight the top 3 reachable hours
- still show every other hour normally

Suggested labels:

```text
最高分
次高
第三
```

or a subtler visual highlight.

Do not reproduce the IsItVisible problem by showing only those hours.

---

# 9. Add "best continuous block"

The user often cares about a usable time window rather than one isolated hour.

Instead of requiring a "qualifying" 2-hour block, calculate the **best continuous block**.

Default:

```text
BEST_BLOCK_HOURS=2
```

For every day:

1. consider reachable hours
2. calculate every contiguous 2-hour rolling window
3. calculate mean Proxy for the window
4. choose the highest mean window
5. always return one if at least two reachable hours exist

Example:

```text
10:00–11:00
mean = 74

11:00–12:00
mean = 76.5

best block:
11:00–12:00
```

This is not a recommendation threshold.

It is simply the best available continuous 2-hour period.

---

# 10. Optional best 3-hour block

If easy to implement, allow:

```text
BEST_BLOCK_HOURS=2
```

as configurable.

No UI selector is required in this phase.

Do not add complexity unless trivial.

---

# 11. Day comparison should use ranking, not qualification

Each upcoming-day card should show:

```text
date
best 2-hour block
average score
peak score
trend
```

Example:

```text
8月25日 周二

最佳连续 2 小时
11:00–12:00

平均 76
最高 77

趋势：改善
```

Another day:

```text
8月26日 周三

最佳连续 2 小时
08:00–09:00

平均 65
最高 66

趋势：恶化
```

This makes Tuesday vs Wednesday immediately comparable.

---

# 12. Rank days explicitly

Add a simple day ranking based primarily on:

```text
best continuous block mean Proxy
```

Example:

```text
1. 周二  76
2. 周三  65
3. 周一  62
```

Do not call this:

```text
推荐排名
```

Use:

```text
观景条件排名
```

or:

```text
当前排名
```

This ranking is evidence, not a guarantee.

---

# 13. Multi-model consensus becomes a warning layer

Phase 3.1 consensus remains useful, but should not block the normal ranking.

Use it to add warnings only when disagreement is meaningful.

Examples:

```text
⚠ 综合评分来源分歧较大
⚠ 能见度预测分歧较大
⚠ 中层云判断不一致
⚠ 降水风险偏高
```

No warning when evidence is broadly consistent.

Do not fill every row with:

```text
强支持
中支持
多数不利
```

unless the user opens details.

---

# 14. Severe disagreement warning

Surface a warning when Phase 3.1 reports:

```text
proxy.agreement == SEVERE
```

Suggested normal UI:

```text
模型分歧大
```

Tooltip / expandable detail:

```text
两个完整评分来源差异较大：
auto 78
GFS 43
```

Do not automatically remove the hour from ranking.

The raw score should remain visible.

---

# 15. Field warnings

Use field-level consensus only for notable conditions.

Examples:

## Mid-cloud

If:

```text
mid_cloud.support == OPPOSED
```

show:

```text
中层云偏多
```

## Precipitation

If:

```text
precipitation.support == OPPOSED
```

show:

```text
降水风险
```

## Visibility

If visibility sources strongly disagree:

```text
能见度分歧
```

Do not show a warning simply because only two visibility sources exist.

That is a known structural limitation and belongs in diagnostics.

---

# 16. Avoid duplicated-source overinterpretation

Phase 3.2 does NOT need to implement model-family deduplication.

Do not add a new JMA / NOAA / ECMWF voting architecture in this phase.

However, UI wording must avoid saying:

```text
5 个独立模型一致
```

Use neutral wording:

```text
5 个预测来源有该字段
```

or:

```text
多数来源支持
```

Keep the more technical caveat in Diagnostics.

---

# 17. Forecast drift becomes first-class

Forecast history is one of the most useful features that external sites do not expose clearly.

For each hour, show a compact trend based on stored snapshots.

Suggested display:

```text
↑ 改善
→ 稳定
↓ 恶化
? 数据不足
```

Use existing stability / trend data.

Do not introduce a new complex forecasting algorithm.

---

# 18. Trend should be visible in the hourly table

The user should not need to scroll to a separate chart just to learn whether a forecast is changing.

Example:

```text
11:00   76   ↑ 改善
12:00   77   → 稳定
```

The detailed drift chart can remain below.

---

# 19. Improve trend wording

Normal UI:

```text
IMPROVING -> 改善
STABLE -> 稳定
WORSENING -> 恶化
VOLATILE -> 波动大
UNKNOWN -> 暂无趋势
```

If current backend uses a different enum set, map accordingly.

---

# 20. Preserve detailed drift chart

Keep the existing forecast drift panel.

It remains valuable for answering:

> "Tuesday looked good yesterday. Is it still holding?"

The chart is a secondary deep-dive feature, not the first thing on the page.

---

# 21. Mobile-first information hierarchy

On mobile, every hourly card should be compact.

Suggested card:

```text
11:00                 76
                      ↑ 改善

中层云      2%
能见度      28.2 km
降水        20%

最佳时段
```

Warnings appear only if needed:

```text
⚠ 能见度分歧
```

Do not place long consensus prose inside every card.

---

# 22. Remove noisy normal-view fields

Normal hourly view should not prominently show:

```text
FULL / PARTIAL
2/6
INSUFFICIENT
decision_reasons
field support enum
```

These remain in:

```text
details
diagnostics
API
```

The user does not need to debug Open-Meteo while checking Tuesday weather.

---

# 23. Diagnostics stays technical

Diagnostics should retain:

```text
model capability matrix
FULL_PROXY / PARTIAL_USEFUL
missing variables
field support
raw model values
API errors
```

This is where technical depth belongs.

Do not delete Phase 3.1 diagnostics.

---

# 24. Simplify normal status labels

The normal dashboard does not need a large taxonomy.

Recommended visible labels are limited to:

```text
最佳时段
较好
一般
较差
到达前
```

These may be derived from score ranges or relative day ranking.

If using absolute bands, keep them simple and configurable.

Suggested initial bands:

```text
>= 75   较好
60–74   一般
< 60    较差
```

However:

- the numeric Proxy remains primary
- labels are secondary
- do not let labels hide the score

---

# 25. Recommended alternative: relative highlights

If avoiding new absolute labels is easier, simply use:

```text
最高分
Top 3
最佳连续2小时
```

and leave all other rows unlabeled.

This is acceptable and may be preferable.

Do not over-engineer another classification layer.

---

# 26. Arrival time remains a filter, not a weather judgment

Keep:

```text
arrival_after
```

Before-arrival rows may remain visible but muted.

Example:

```text
05:00   80   到达前
```

Do not remove them entirely.

Reason:

The user may still want to know what conditions looked like earlier.

---

# 27. Selected-day header

For the selected day, show a concise summary.

Example:

```text
8月25日 周二

最佳连续2小时：11:00–12:00
平均评分：76
最高评分：77
趋势：改善
```

Below that:

```text
完整 hourly table
```

No large red "NO QUALIFYING WINDOW" banner.

---

# 28. Homepage default selected date

Keep existing selection behavior unless clearly broken.

If no date is explicitly selected:

1. prefer the highest-ranked future day among the displayed date range
2. otherwise select today

This helps the user land directly on the most interesting candidate.

Do not make the ranking invisible; clearly show which date is selected.

---

# 29. Do not let `qualifies` control visibility

Existing API field:

```text
qualifies
```

may remain for compatibility.

But normal homepage logic must not do:

```python
if not qualifies:
    mark as invalid
```

or:

```python
hide hour
```

or:

```python
exclude from best-hour ranking
```

Ranking should use all reachable hours with valid Proxy values.

---

# 30. New derived best-block structure

Add a lightweight derived object.

Suggested:

```json
{
  "best_block": {
    "start": "2026-08-25T11:00:00+09:00",
    "end": "2026-08-25T12:00:00+09:00",
    "duration_hours": 2,
    "mean_proxy": 76.2,
    "peak_proxy": 77.0,
    "peak_time": "2026-08-25T12:00:00+09:00",
    "warnings": [
      "PRECIPITATION_RISK"
    ]
  }
}
```

This should be independent of:

```text
qualifies
PROMISING
RECOMMENDED
```

---

# 31. Daily summary structure

Suggested addition:

```json
{
  "date": "2026-08-25",
  "best_block": {...},
  "top_hours": [
    {...},
    {...},
    {...}
  ],
  "day_rank_score": 76.2
}
```

Keep existing fields.

Do not break Phase 3.1 API clients.

---

# 32. Ranking tie handling

If two days are nearly equal, do not create false precision.

Suggested:

```text
difference < 3 Proxy points
```

may display:

```text
接近
```

Example:

```text
周二 76
周三 74
→ 条件接近
```

This is optional but useful.

---

# 33. Normal page example

The intended normal experience is roughly:

```text
富士山能见度

当前排名
1 周二  最佳 11:00–12:00  平均 76  ↑
2 周三  最佳 08:00–09:00  平均 65  ↓


8月25日 周二
最佳连续2小时：11:00–12:00

时间   评分  中层云  能见度   降水  趋势  提示
05    61     ...
06    61     ...
07    58     ...
08    61    0%      8.8     0%   →
09    67    0%     14.9     0%   ↑
10    72    0%     21.6     8%   ↑
11    76    2%     28.2    20%   ↑    最佳时段
12    77    7%     34.9    33%   →    降水风险
```

Then below:

```text
预测变化趋势
模型详情
Diagnostics
```

This is the target hierarchy.

---

# 34. What Phase 3.2 explicitly does NOT do

Do NOT add:

```text
600 hPa / 700 hPa analysis
new meteorological variables
new external data providers
satellite imagery
webcams
ECMWF HRES migration
model-family deduplication
machine learning
new mega-score
more complex consensus thresholds
```

These may be future experiments.

They are outside the original product problem.

---

# 35. Do not remove useful Phase 3.1 work

Even though normal UI becomes simpler, keep existing structured evidence.

This allows a warning like:

```text
⚠ 模型分歧大
```

to be backed by actual Phase 3.1 logic.

Do not regress to a single-model-only system.

---

# 36. Current live-state sanity check

At the time this Phase 3.2 spec was written, Phase 3.1 already successfully distinguished cases such as:

```text
2026-08-25 11:00
status = PROMISING
Proxy median ≈ 76
Proxy agreement = GOOD
mid-cloud support = STRONG
precipitation support = STRONG
```

and:

```text
2026-08-25 12:00
Proxy median ≈ 77
field consensus weaker because precipitation is above the configured good threshold
```

This proves Phase 3.1 evidence logic is functioning.

Phase 3.2 should use that information as a warning / explanation layer while still letting both hours remain visible and rankable.

Live values will change; do not hard-code them.

---

# 37. Tests

Add tests focused on product behavior.

## Case A — all hours remain visible

Given:

```text
8 valid hourly points
only 1 qualifies
```

Expected:

```text
all 8 appear in dashboard data
```

---

## Case B — best block ignores qualification gate

Given reachable Proxy:

```text
08 61
09 67
10 72
11 76
12 77
```

Expected 2-hour best block:

```text
11–12
mean 76.5
```

even if one or both hours are not formally `qualifies`.

---

## Case C — severe disagreement does not hide hour

Given:

```text
Proxy median 75
agreement SEVERE
```

Expected:

```text
hour still visible
hour remains rankable
warning = model disagreement
```

---

## Case D — before-arrival remains visible but muted

Expected:

```text
row visible
excluded from reachable best-block calculation
```

---

## Case E — bad day still gets a best block

Given all scores:

```text
30–45
```

Expected:

```text
best block returned
summary says overall conditions poor
```

Do not return "nothing" merely because weather is bad.

---

## Case F — trend inline

If stored snapshots provide trend:

```text
IMPROVING
```

Expected normal hourly UI:

```text
改善
```

---

# 38. Implementation order

## Milestone 1 — best-block service

Add:

```text
best continuous 2-hour block
top 3 reachable hours
day ranking score
```

No qualification gate.

---

## Milestone 2 — summary API/view model

Expose:

```text
best_block
top_hours
day_rank_score
warnings
```

Preserve existing Phase 3.1 fields.

---

## Milestone 3 — homepage hierarchy

Replace large decision-first presentation with:

```text
current ranking
best block
hourly browser
```

---

## Milestone 4 — inline trend

Add compact trend display to hourly rows/cards.

---

## Milestone 5 — warning layer

Convert Phase 3.1 consensus into concise warnings only when notable.

---

## Milestone 6 — mobile cleanup

Ensure the same information hierarchy works on phone.

---

## Milestone 7 — regression tests

Confirm:

```text
Phase 3.1 API remains backward compatible
diagnostics remain available
all hours remain visible
ranking does not depend on qualifies
```

---

# 39. Definition of Done

Phase 3.2 is complete when:

- [ ] The homepage clearly behaves as an hourly forecast browser.
- [ ] Every requested hour is always visible.
- [ ] Proxy is still the primary scan metric.
- [ ] A best reachable hour is highlighted.
- [ ] A best continuous 2-hour block is always calculated when possible.
- [ ] Days are comparable by best-block score.
- [ ] Forecast drift is visible inline.
- [ ] Multi-model logic appears mainly as concise warnings.
- [ ] Severe model disagreement does not hide useful data.
- [ ] Bad weather still produces a "best available" block.
- [ ] `qualifies` no longer controls normal hourly visibility or ranking.
- [ ] Phase 3.1 field consensus and diagnostics remain intact.
- [ ] No new pressure-level or meteorological research features are added.
- [ ] Desktop and mobile both allow a user to answer "which day and which hour?" within seconds.
- [ ] Existing tests still pass.
- [ ] New Phase 3.2 tests pass.

---

# 40. Codex working instructions

1. Treat this as a focused product re-centering, not a rewrite.
2. Read the completed Phase 3.1 implementation first.
3. Preserve its evidence structures and diagnostics.
4. Do not delete `PROMISING`, field consensus, confidence, or decision reasons from APIs.
5. Stop making those states the homepage's primary organizing principle.
6. Implement best-hour and best-contiguous-block ranking independently of `qualifies`.
7. Keep all hourly rows visible.
8. Keep before-arrival rows visible but exclude them from reachable ranking.
9. Surface only meaningful model/field warnings in the normal dashboard.
10. Keep detailed evidence in expandable details and Diagnostics.
11. Make forecast drift visible inline.
12. Do not add new meteorological variables or external services.
13. Keep Simplified Chinese as the normal UI language.
14. Preserve API backward compatibility.
15. Run the complete existing test suite.
16. At completion report:
    - files changed
    - best-block implementation
    - ranking logic
    - normal-UI changes
    - warning mapping
    - inline trend behavior
    - test results
    - current top day / best block from live data
    - confirmation that no Phase 3.1 evidence logic was deleted

---

# 41. One-sentence acceptance criterion

When the user opens `fuji.wangdi.store`, the page should primarily answer:

> 周二还是周三更好、具体几点最好、预报是在变好还是变差？

—not ask the user to understand why a multi-model expert system did or did not "qualify" the weather.
