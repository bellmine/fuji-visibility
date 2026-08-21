"""Simplified Chinese labels used by the web dashboard."""

from __future__ import annotations

import re
from datetime import date, datetime

from ..time_utils import parse_datetime, to_jst

DECISION_LABELS = {
    "RECOMMENDED": "推荐",
    "PROMISING": "值得关注",
    "NO CLEAR WINNER": "暂无明确优选",
    "NO QUALIFYING WINDOW": "暂无理想窗口",
    "INSUFFICIENT EVIDENCE": "核心数据不足",
}

CONSENSUS_LABELS = {
    "HIGH": "高",
    "MEDIUM": "中",
    "LOW": "低",
    "INSUFFICIENT_DATA": "数据不足",
}

TREND_LABELS = {
    "IMPROVING": "改善中",
    "WORSENING": "恶化中",
    "STABLE": "稳定",
    "VOLATILE": "波动较大",
    "UNKNOWN": "未知",
}

# Short labels used inline in the hourly browser. Keep TREND_LABELS as the
# longer compatibility wording used by the trend panel and API.
TREND_SHORT_LABELS = {
    "IMPROVING": "改善",
    "WORSENING": "恶化",
    "STABLE": "稳定",
    "VOLATILE": "波动大",
    "UNKNOWN": "暂无趋势",
}

STABILITY_LABELS = {
    "HIGH": "高",
    "MEDIUM": "中",
    "LOW": "低",
    "UNKNOWN": "未知",
}

FRESHNESS_LABELS = {
    "FRESH": "最新",
    "WARNING": "需注意",
    "STALE": "数据过旧",
    "UNKNOWN": "未知",
}

MODEL_STATUS_LABELS = {
    "FULL_PROXY": "综合评分可用",
    "PARTIAL_USEFUL": "按字段提供",
    "UNAVAILABLE": "暂无当前数据",
    # Compatibility labels for Phase 2 metadata.
    "FULL": "综合评分可用",
    "PARTIAL": "按字段提供",
}

FIELD_SUPPORT_LABELS = {
    "STRONG_SUPPORT": "强支持",
    "MODERATE_SUPPORT": "中支持",
    "MIXED": "支持不一",
    "OPPOSED": "多数不利",
    "INSUFFICIENT": "数据不足",
}

HOUR_STATUS_LABELS = {
    "BEFORE_ARRIVAL": "到达前",
    "LOW_SCORE": "评分不足",
    "MODEL_DISAGREEMENT": "预报来源分歧较大",
    "FIELD_CONSENSUS_WEAK": "预报来源支持不足",
    "INSUFFICIENT_CORE_DATA": "核心数据不足",
    "PROMISING": "值得关注",
    "QUALIFIES": "符合条件",
    "OTHER": "暂无法判断",
}

PROXY_AGREEMENT_LABELS = {
    "GOOD": "一致性良好",
    "MIXED": "存在分歧",
    "SEVERE": "分歧较大",
    "INSUFFICIENT": "数据不足",
}

WARNING_LABELS = {
    "MODEL_DISAGREEMENT": "预报来源分歧大",
    "MID_CLOUD_RISK": "中层云偏多",
    "PRECIPITATION_RISK": "降水风险",
    "VISIBILITY_DISAGREEMENT": "能见度分歧",
}

DECISION_REASON_LABELS = {
    "BEFORE_ARRIVAL": "到达时间尚未满足",
    "FULL_PROXY_MODELS_INSUFFICIENT": "参与综合评分的预报来源数量不足",
    "INSUFFICIENT_CORE_DATA": "核心数据不足",
    "PROXY_UNAVAILABLE": "暂无综合评分",
    "LOW_PROXY": "综合评分低于门槛",
    "PROXY_BELOW_THRESHOLD": "综合评分未达到门槛",
    "PROXY_OK": "综合评分达到门槛",
    "PROXY_ABOVE_THRESHOLD": "综合评分达到门槛",
    "FULL_PROXY_MODELS_OK": "参与综合评分的预报来源数量满足要求",
    "PROXY_MODELS_AGREE": "参与综合评分的预报来源一致性良好",
    "PROXY_DISAGREEMENT_LIMITED": "参与综合评分的预报来源存在一定分歧",
    "PROXY_DISAGREEMENT": "参与综合评分的预报来源分歧较大",
    "PROXY_DISAGREEMENT_SEVERE": "参与综合评分的预报来源严重分歧",
    "MID_CLOUD_INSUFFICIENT": "中层云数据不足",
    "MID_CLOUD_OPPOSED": "多数预报来源认为中层云条件不利",
    "MID_CLOUD_STRONGLY_SUPPORTED": "多个预报来源一致支持中层云量较低",
    "MID_CLOUD_SUPPORTED": "多个预报来源支持中层云条件可接受",
    "PRECIP_INSUFFICIENT": "降水数据不足",
    "PRECIP_OPPOSED": "多数预报来源认为降水风险偏高",
    "PRECIP_SUPPORTED": "多个预报来源支持降水风险可接受",
    "VISIBILITY_SUPPORTED": "能见度达到支持条件",
    "LIMITED_VISIBILITY_MODEL_COUNT": "能见度可用预报来源较少",
    "HUMIDITY_OPPOSED": "湿度条件偏不利",
    "HUMIDITY_SUPPORTED": "湿度条件可接受",
    "CONFIDENCE_HIGH": "置信度高",
    "CONFIDENCE_MEDIUM": "置信度中",
    "CONFIDENCE_LOW": "置信度低",
    "CONFIDENCE_INSUFFICIENT": "置信度不足",
}

REFRESH_STATUS_LABELS = {
    "success": "成功",
    "partial": "部分来源失败",
    "failed": "失败",
    "unknown": "未知",
}

LOCATION_LABELS = {
    "kawaguchiko": "河口湖",
    "oishi": "大石公园",
    "shojiko": "精进湖",
}

WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

_PROXY_THRESHOLD_RE = re.compile(
    r"^Peak Proxy difference \((?P<difference>-?\d+(?:\.\d+)?)\) is below the "
    r"(?P<threshold>-?\d+(?:\.\d+)?)-point decision threshold\."
)

_RATIONALE_LABELS = {
    "No day has a reachable qualifying window。": "目前没有符合条件的可到达观景窗口。",
    "No day has a reachable qualifying window.": "目前没有符合条件的可到达观景窗口。",
    "No day has a reachable promising window.": "目前没有可到达的值得关注时段。",
    "Not enough core forecast evidence is currently available.": "目前缺少足够的核心预报数据，暂时无法做出可靠判断。",
    "A reachable evidence-supported promising window is available.": "目前有一个可到达、且有数据支持的值得关注时段。",
    "Only one candidate day has a reachable qualifying window.": "目前只有一个日期具备符合条件的可到达观景窗口。",
    "Only one candidate day has a reachable promising window.": "目前只有一个日期具备可到达的值得关注时段。",
    "Recheck after the next model cycle.": "建议在下一轮预报更新后再次查看。",
    "longer reachable window": "可到达窗口更长",
    "stronger multi-model agreement": "预报来源一致性更强",
    "more stable recent forecast": "近期预报更稳定",
    "higher Proxy median": "综合评分中位数更高",
    "more favorable trend direction": "趋势方向更有利",
    "higher rules-based decision rank": "规则判断排名更高",
}


def label(mapping: dict[str, str], value: str | None, default: str = "未知") -> str:
    """Translate a known domain state while keeping unknown states readable."""

    if value is None:
        return default
    return mapping.get(value, default)


def localized_date(value: date) -> str:
    """Render a short date such as ``8月25日 周二``."""

    return f"{value.month}月{value.day}日 {WEEKDAY_LABELS[value.weekday()]}"


def localized_datetime(value: datetime | str | None) -> str:
    """Render a JST date/time with a compact Chinese date and explicit zone."""

    if not value:
        return "—"
    try:
        parsed = parse_datetime(value) if isinstance(value, str) else value
        local = to_jst(parsed)
    except (AttributeError, TypeError, ValueError):
        return str(value)
    return f"{local.month}月{local.day}日 {local:%H:%M} JST"


def localized_rationale(items: list[str] | tuple[str, ...]) -> list[str]:
    """Translate decision explanations without changing the decision engine's API text."""

    translated: list[str] = []
    for item in items:
        match = _PROXY_THRESHOLD_RE.match(item)
        if match:
            translated.append(
                f"评分峰值差异为 {match.group('difference')} 分，低于 "
                f"{match.group('threshold')} 分的决策阈值。"
            )
            continue
        translated.append(_RATIONALE_LABELS.get(item, "暂无更多判断说明。"))
    return translated


def localized_coverage(_full_models: int, configured_models: int) -> str:
    """Describe the number of configured forecast sources neutrally."""

    return f"汇总 {configured_models} 个预报来源"
