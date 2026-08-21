"""Simplified Chinese labels used by the web dashboard."""

from __future__ import annotations

import re
from datetime import date, datetime

from ..time_utils import parse_datetime, to_jst

DECISION_LABELS = {
    "RECOMMENDED": "推荐",
    "NO CLEAR WINNER": "暂无明确优选",
    "NO QUALIFYING WINDOW": "暂无符合条件的观景窗口",
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
    "FULL": "完整",
    "PARTIAL": "部分数据",
}

REFRESH_STATUS_LABELS = {
    "success": "成功",
    "partial": "部分完成",
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
    "Only one candidate day has a reachable qualifying window.": "目前只有一个日期具备符合条件的可到达观景窗口。",
    "Recheck after the next model cycle.": "建议在下一轮模型更新后再次查看。",
    "longer reachable window": "可到达窗口更长",
    "stronger multi-model agreement": "多模型一致性更强",
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


def localized_coverage(full_models: int, configured_models: int) -> str:
    """Describe model completeness in the wording used by the dashboard."""

    return f"{configured_models} 个模型中 {full_models} 个数据完整"
