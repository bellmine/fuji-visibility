(function () {
  "use strict";

  const dashboard = window.__FUJI_DASHBOARD__ || null;
  const query = (selector) => document.querySelector(selector);

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
      if (label) label.textContent = "Refreshing…";
      setRefreshMessage("Fetching the configured models and saving a new snapshot…");
      try {
        const response = await fetch("/api/refresh", {
          method: "POST",
          headers: { "Accept": "application/json" },
          credentials: "same-origin"
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
          const retry = body.retry_after_seconds ? ` Try again in ${body.retry_after_seconds}s.` : "";
          throw new Error((body.message || body.detail || "Refresh failed.") + retry);
        }
        setRefreshMessage(body.message || "Refresh complete. Reloading…");
        window.setTimeout(() => window.location.reload(), 500);
      } catch (error) {
        button.disabled = false;
        if (label) label.textContent = "Refresh forecast";
        setRefreshMessage(error instanceof Error ? error.message : "Refresh failed.", "error");
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
      empty.textContent = "No stored drift points yet";
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
      title.textContent = `${point.retrieved_at}: ${point.value.toFixed(1)}`;
      circle.appendChild(title);
      svg.appendChild(circle);
    });
    const first = svgElement("text", { x: left, y: height - 7, class: "chart-label" });
    first.textContent = points[0].retrieved_at.slice(5, 16).replace("T", " ");
    svg.appendChild(first);
    if (points.length > 1) {
      const last = svgElement("text", { x: width - right, y: height - 7, "text-anchor": "end", class: "chart-label" });
      last.textContent = points[points.length - 1].retrieved_at.slice(5, 16).replace("T", " ");
      svg.appendChild(last);
    }
  }

  async function loadTrend(dateSelect, hourSelect, variableSelect, summary, svg) {
    const dateValue = dateSelect && dateSelect.value;
    const hourValue = hourSelect && hourSelect.value;
    if (!dateValue || !hourValue || !svg) {
      if (summary) summary.textContent = "Select a stored day and hour to inspect drift.";
      if (svg) renderChart({ points: [] }, svg);
      return;
    }
    const variable = variableSelect ? variableSelect.value : "proxy";
    const location = dashboard && dashboard.status ? dashboard.status.location : "";
    if (summary) summary.textContent = "Loading stored drift…";
    try {
      const params = new URLSearchParams({ date: dateValue, hour: hourValue, variable });
      if (location) params.set("location", location);
      const response = await fetch(`/api/trend?${params.toString()}`, { credentials: "same-origin" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Trend unavailable");
      const latest = payload.points && payload.points.length ? payload.points[payload.points.length - 1].value : null;
      if (summary) {
        const latestText = typeof latest === "number" ? ` Latest: ${latest.toFixed(1)}.` : "";
        summary.textContent = `${payload.trend} · ${payload.confidence} confidence · ${payload.samples} stored collections.${latestText}`;
      }
      renderChart(payload, svg);
    } catch (error) {
      if (summary) summary.textContent = error instanceof Error ? error.message : "Trend unavailable";
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
