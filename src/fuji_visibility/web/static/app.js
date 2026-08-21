(function () {
  "use strict";

  const dashboard = window.__FUJI_DASHBOARD__ || null;
  const query = (selector) => document.querySelector(selector);
  const TREND_LABELS = {
    IMPROVING: "改善中",
    WORSENING: "恶化中",
    STABLE: "稳定",
    VOLATILE: "波动较大",
    UNKNOWN: "未知"
  };
  const CONFIDENCE_LABELS = { HIGH: "高", MEDIUM: "中", LOW: "低", UNKNOWN: "未知" };

  function setRefreshMessage(message, kind) {
    const target = query("[data-refresh-message]");
    if (!target) return;
    target.textContent = message;
    target.classList.toggle("error-text", kind === "error");
  }

  function setupRefresh() {
    const button = query("[data-refresh]");
    if (!button) return;
    const label = button.querySelector("[data-refresh-label]");
    button.addEventListener("click", async function () {
      button.disabled = true;
      if (label) label.textContent = "刷新中…";
      setRefreshMessage("正在获取已配置的模型并保存新的预报快照…");
      try {
        const response = await fetch("/api/refresh", {
          method: "POST",
          headers: { "Accept": "application/json" },
          credentials: "same-origin"
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
          const retry = body.retry_after_seconds ? `请在 ${body.retry_after_seconds} 秒后再试。` : "";
          throw new Error((body.message || "预报刷新失败，请稍后重试。") + retry);
        }
        setRefreshMessage(body.message || "预报刷新完成，正在重新加载…");
        window.setTimeout(() => window.location.reload(), 500);
      } catch (error) {
        button.disabled = false;
        if (label) label.textContent = "刷新预报";
        setRefreshMessage(error instanceof Error ? error.message : "预报刷新失败，请稍后重试。", "error");
      }
    });
  }

  function selectedDay(dateValue) {
    if (!dashboard || !Array.isArray(dashboard.days)) return null;
    return dashboard.days.find((day) => day.date === dateValue) || null;
  }

  function updateHourOptions(day, hourSelect) {
    if (!hourSelect) return;
    const current = hourSelect.value;
    hourSelect.replaceChildren();
    (day && day.hours ? day.hours : []).forEach((hour) => {
      const option = document.createElement("option");
      option.value = hour.local_time;
      option.textContent = hour.local_time;
      hourSelect.appendChild(option);
    });
    if ([...hourSelect.options].some((option) => option.value === current)) {
      hourSelect.value = current;
    }
  }

  function formatJstDateTime(value) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    const parts = new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Tokyo",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    }).formatToParts(parsed);
    const part = (type) => (parts.find((item) => item.type === type) || {}).value || "";
    return `${part("month")}月${part("day")}日 ${part("hour")}:${part("minute")}`;
  }

  function svgElement(name, attributes) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }

  function renderChart(payload, svg) {
    svg.replaceChildren();
    const points = (payload.points || []).filter((point) => typeof point.value === "number");
    if (!points.length) {
      const empty = svgElement("text", { x: 280, y: 92, "text-anchor": "middle", class: "chart-empty" });
      empty.textContent = "暂时没有已保存的变化趋势数据";
      svg.appendChild(empty);
      return;
    }
    const width = 560;
    const height = 180;
    const left = 34;
    const right = 16;
    const top = 18;
    const bottom = 28;
    const values = points.map((point) => point.value);
    let min = Math.min(...values);
    let max = Math.max(...values);
    if (min === max) {
      min -= 1;
      max += 1;
    } else {
      const padding = Math.max(2, (max - min) * 0.12);
      min -= padding;
      max += padding;
    }
    const x = (index) => left + (index * (width - left - right)) / Math.max(1, points.length - 1);
    const y = (value) => top + ((max - value) * (height - top - bottom)) / (max - min);
    [0, .5, 1].forEach((ratio) => {
      const yPosition = top + ratio * (height - top - bottom);
      svg.appendChild(svgElement("line", { x1: left, y1: yPosition, x2: width - right, y2: yPosition, class: "chart-grid" }));
      const label = svgElement("text", { x: 0, y: yPosition + 4, class: "chart-label" });
      label.textContent = String(Math.round(max - ratio * (max - min)));
      svg.appendChild(label);
    });
    const path = points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(" ");
    svg.appendChild(svgElement("path", { d: path, class: "chart-line" }));
    points.forEach((point, index) => {
      const circle = svgElement("circle", { cx: x(index), cy: y(point.value), r: 4, class: "chart-point" });
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = `${formatJstDateTime(point.retrieved_at)} JST：${point.value.toFixed(1)}`;
      circle.appendChild(title);
      svg.appendChild(circle);
    });
    const first = svgElement("text", { x: left, y: height - 7, class: "chart-label" });
    first.textContent = formatJstDateTime(points[0].retrieved_at);
    svg.appendChild(first);
    if (points.length > 1) {
      const last = svgElement("text", { x: width - right, y: height - 7, "text-anchor": "end", class: "chart-label" });
      last.textContent = formatJstDateTime(points[points.length - 1].retrieved_at);
      svg.appendChild(last);
    }
  }

  async function loadTrend(dateSelect, hourSelect, variableSelect, summary, svg) {
    const dateValue = dateSelect && dateSelect.value;
    const hourValue = hourSelect && hourSelect.value;
    if (!dateValue || !hourValue || !svg) {
      if (summary) summary.textContent = "请选择已有数据的日期和时段以查看趋势。";
      if (svg) renderChart({ points: [] }, svg);
      return;
    }
    const variable = variableSelect ? variableSelect.value : "proxy";
    const location = dashboard && dashboard.status ? dashboard.status.location : "";
    if (summary) summary.textContent = "正在加载已保存的趋势…";
    try {
      const params = new URLSearchParams({ date: dateValue, hour: hourValue, variable });
      if (location) params.set("location", location);
      const response = await fetch(`/api/trend?${params.toString()}`, { credentials: "same-origin" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || "趋势数据暂时无法获取。");
      const latest = payload.points && payload.points.length ? payload.points[payload.points.length - 1].value : null;
      if (summary) {
        const trend = payload.trend_label || TREND_LABELS[payload.trend] || "未知";
        const confidence = payload.confidence_label || CONFIDENCE_LABELS[payload.confidence] || "未知";
        const latestText = typeof latest === "number" ? ` 最新值：${latest.toFixed(1)}。` : "";
        summary.textContent = `${trend} · ${confidence}可信度 · ${payload.samples} 次已保存采集。${latestText}`;
      }
      renderChart(payload, svg);
    } catch (error) {
      if (summary) summary.textContent = error instanceof Error ? error.message : "趋势数据暂时无法获取。";
      renderChart({ points: [] }, svg);
    }
  }

  function setupTrend() {
    if (!dashboard) return;
    const dateSelect = query("[data-trend-date]");
    const hourSelect = query("[data-trend-hour]");
    const variableSelect = query("[data-trend-variable]");
    const summary = query("[data-trend-summary]");
    const svg = query("[data-trend-chart]");
    if (!dateSelect || !hourSelect || !variableSelect || !summary || !svg) return;
    dateSelect.addEventListener("change", () => {
      updateHourOptions(selectedDay(dateSelect.value), hourSelect);
      loadTrend(dateSelect, hourSelect, variableSelect, summary, svg);
    });
    hourSelect.addEventListener("change", () => loadTrend(dateSelect, hourSelect, variableSelect, summary, svg));
    variableSelect.addEventListener("change", () => loadTrend(dateSelect, hourSelect, variableSelect, summary, svg));
    loadTrend(dateSelect, hourSelect, variableSelect, summary, svg);
  }

  document.addEventListener("DOMContentLoaded", function () {
    setupRefresh();
    setupTrend();
  });
}());
