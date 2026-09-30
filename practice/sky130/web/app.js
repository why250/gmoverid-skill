"use strict";

const DATA_URL = "../data/sky130_nfet_01v8_characterization.tsv";
const SVG_NS = "http://www.w3.org/2000/svg";
const CONDITION_FIELDS = ["corner", "temperature_c", "length_um", "vds_v", "vbs_v"];
const NUMERIC_FIELDS = new Set([
  "temperature_c", "width_um", "length_um", "vds_v", "vbs_v", "vgs_v",
  "vth_v", "vov_v", "vdsat_v", "id_a", "id_w_ua_per_um", "gm_s",
  "gds_s", "gmb_s", "gmb_over_gm", "cgg_f", "cgs_f", "cgd_f",
  "cgb_f", "cdb_f", "gmid_per_v", "gmro", "ft_hz",
]);

const FIELD_META = {
  corner: { label: "Corner", format: value => String(value).toUpperCase() },
  temperature_c: { label: "Temperature", format: value => `${formatNumber(value, 0)} °C` },
  length_um: { label: "L", format: value => `${formatNumber(value, 2)} µm` },
  vds_v: { label: "VDS", format: value => `${formatNumber(value, 2)} V` },
  vbs_v: { label: "VBS", format: value => `${formatNumber(value, 2)} V` },
};

const CHARTS = [
  { id: "chart-idw", valueId: "value-idw", key: "id_w_ua_per_um", unit: "µA/µm", yLabel: "ID/W [µA/µm]", log: true },
  { id: "chart-gmro", valueId: "value-gmro", key: "gmro", unit: "", yLabel: "gm/gds", log: false },
  { id: "chart-ft", valueId: "value-ft", key: "ft_hz", unit: "GHz", yLabel: "fT [GHz]", scale: 1e-9, log: false },
  { id: "chart-vgs", valueId: "value-vgs", key: "vgs_v", unit: "V", yLabel: "VGS [V]", log: false },
];

const DETAIL_METRICS = [
  ["VGS", "vgs_v", "V", 4],
  ["VTH", "vth_v", "V", 4],
  ["VOV", "vov_v", "V", 4],
  ["VDSAT", "vdsat_v", "V", 4],
  ["ID/W", "id_w_ua_per_um", "µA/µm", 4],
  ["gm", "gm_s", "mS", 4, 1e3],
  ["gds", "gds_s", "µS", 4, 1e6],
  ["gmb", "gmb_s", "µS", 4, 1e6],
  ["gmb/gm", "gmb_over_gm", "", 4],
  ["gm/gds", "gmro", "", 4],
  ["fT", "ft_hz", "GHz", 4, 1e-9],
  ["Cgg", "cgg_f", "fF", 4, 1e15],
  ["Cgs", "cgs_f", "fF", 4, 1e15],
  ["Cgd", "cgd_f", "fF", 4, 1e15],
  ["Cgb", "cgb_f", "fF", 4, 1e15],
  ["Cdb", "cdb_f", "fF", 4, 1e15],
];

const state = {
  mode: "explore",
  gmid: 15,
  conditions: [],
  explore: null,
  compareDimension: "length_um",
  selectedCompareKeys: new Set(),
  renderPending: false,
};

const dom = {};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  bindDom();
  bindEvents();
  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const text = await response.text();
    const rows = parseTsv(text);
    state.conditions = buildConditions(rows);
    if (!state.conditions.length) throw new Error("数据表中没有可用工作点");
    state.explore = findNominalCondition();
    setCompareDefaults();
    renderAll();
    dom.workspace.setAttribute("aria-busy", "false");
    dom.datasetStatus.textContent = "数据已载入";
    dom.datasetStatus.classList.add("is-ready");
    dom.datasetCount.textContent = `${state.conditions.length} conditions · ${rows.length.toLocaleString()} points`;
    new ResizeObserver(() => scheduleVisualRender()).observe(document.querySelector(".chart-grid"));
  } catch (error) {
    showLoadError(error);
  }
}

function bindDom() {
  const ids = [
    "workspace", "dataset-status", "dataset-count", "tab-explore", "tab-compare",
    "panel-explore", "panel-compare", "filter-corner", "filter-temperature",
    "filter-length", "filter-vds", "filter-vbs", "compare-dimension",
    "compare-fixed", "series-options", "gmid-slider", "gmid-input", "gmid-output",
    "reset-explore", "reset-compare", "copy-point", "download-slice", "action-status",
    "error-banner", "selection-description", "explore-profile-note", "availability",
    "op-primary", "op-table",
  ];
  ids.forEach(id => { dom[toCamel(id)] = document.getElementById(id); });
}

function bindEvents() {
  dom.tabExplore.addEventListener("click", () => setMode("explore"));
  dom.tabCompare.addEventListener("click", () => setMode("compare"));
  document.querySelector(".mode-tabs").addEventListener("keydown", event => {
    if (!new Set(["ArrowLeft", "ArrowRight"]).has(event.key)) return;
    event.preventDefault();
    setMode(state.mode === "explore" ? "compare" : "explore");
    (state.mode === "explore" ? dom.tabExplore : dom.tabCompare).focus();
  });

  const filters = {
    corner: dom.filterCorner,
    temperature_c: dom.filterTemperature,
    length_um: dom.filterLength,
    vds_v: dom.filterVds,
    vbs_v: dom.filterVbs,
  };
  Object.entries(filters).forEach(([field, element]) => {
    element.addEventListener("change", () => {
      const value = field === "corner" ? element.value : Number(element.value);
      const next = state.conditions.find(condition =>
        CONDITION_FIELDS.every(candidate => candidate === field
          ? equalValue(condition[candidate], value)
          : equalValue(condition[candidate], state.explore[candidate]))
      );
      if (next) state.explore = next;
      renderAll();
    });
  });

  dom.compareDimension.addEventListener("change", () => {
    state.compareDimension = dom.compareDimension.value;
    setCompareDefaults();
    renderAll();
  });
  dom.seriesOptions.addEventListener("change", event => {
    if (!event.target.matches("input[type='checkbox']")) return;
    if (event.target.checked) state.selectedCompareKeys.add(event.target.value);
    else state.selectedCompareKeys.delete(event.target.value);
    if (!state.selectedCompareKeys.size) {
      event.target.checked = true;
      state.selectedCompareKeys.add(event.target.value);
      setActionStatus("至少保留一条比较曲线");
    }
    renderVisualsAndDetails();
  });

  dom.gmidSlider.addEventListener("input", () => setGmid(Number(dom.gmidSlider.value)));
  dom.gmidInput.addEventListener("input", () => {
    const value = Number(dom.gmidInput.value);
    if (value >= 4 && value <= 24) setGmid(value);
  });
  dom.gmidInput.addEventListener("change", () => setGmid(Number(dom.gmidInput.value)));
  dom.resetExplore.addEventListener("click", () => {
    state.explore = findNominalCondition();
    setGmid(15, false);
    renderAll();
  });
  dom.resetCompare.addEventListener("click", () => {
    state.compareDimension = "length_um";
    dom.compareDimension.value = state.compareDimension;
    setCompareDefaults();
    setGmid(15, false);
    renderAll();
  });
  dom.copyPoint.addEventListener("click", copyCurrentPoint);
  dom.downloadSlice.addEventListener("click", downloadCurrentSlice);
}

function parseTsv(text) {
  const lines = text.replace(/\r/g, "").trim().split("\n");
  const headers = lines.shift().split("\t");
  return lines.filter(Boolean).map(line => {
    const values = line.split("\t");
    const row = {};
    headers.forEach((header, index) => {
      const value = values[index] ?? "";
      row[header] = NUMERIC_FIELDS.has(header) ? Number(value) : value;
    });
    return row;
  });
}

function buildConditions(rows) {
  const groups = new Map();
  rows.forEach(row => {
    const key = conditionKey(row);
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        profiles: row.profiles,
        device: row.device,
        corner: row.corner,
        temperature_c: row.temperature_c,
        width_um: row.width_um,
        length_um: row.length_um,
        vds_v: row.vds_v,
        vbs_v: row.vbs_v,
        rawPoints: [],
      });
    }
    groups.get(key).rawPoints.push(row);
  });
  return [...groups.values()].map(condition => {
    condition.points = inversionBranch(condition.rawPoints);
    delete condition.rawPoints;
    return condition;
  });
}

function inversionBranch(points) {
  const valid = points.filter(point => Number.isFinite(point.gmid_per_v) && point.id_a > 1e-12);
  if (!valid.length) return [];
  let peakIndex = 0;
  valid.forEach((point, index) => {
    if (point.gmid_per_v > valid[peakIndex].gmid_per_v) peakIndex = index;
  });
  return valid.slice(peakIndex)
    .filter(point => point.gmid_per_v >= 3 && point.gmid_per_v <= 30)
    .sort((a, b) => a.gmid_per_v - b.gmid_per_v);
}

function renderAll() {
  renderFilters();
  renderCompareControls();
  renderSelection();
  renderVisualsAndDetails();
}

function renderFilters() {
  if (!state.explore) return;
  const elementByField = {
    corner: dom.filterCorner,
    temperature_c: dom.filterTemperature,
    length_um: dom.filterLength,
    vds_v: dom.filterVds,
    vbs_v: dom.filterVbs,
  };
  CONDITION_FIELDS.forEach(field => {
    const values = uniqueSorted(state.conditions
      .filter(condition => CONDITION_FIELDS.every(other =>
        other === field || equalValue(condition[other], state.explore[other])))
      .map(condition => condition[field]));
    const element = elementByField[field];
    element.innerHTML = values.map(value =>
      `<option value="${escapeHtml(value)}">${escapeHtml(FIELD_META[field].format(value))}</option>`
    ).join("");
    element.value = String(state.explore[field]);
  });
  const profile = state.explore.profiles.includes("core") && state.explore.profiles.includes("pvt")
    ? "core + PVT overlap"
    : state.explore.profiles.toUpperCase();
  dom.exploreProfileNote.textContent = `当前点来自 ${profile} profile。选项会自动限制为数据库中真实存在的组合。`;
}

function renderCompareControls() {
  dom.compareDimension.value = state.compareDimension;
  const conditions = compareCandidates();
  const fixed = fixedDescription(state.compareDimension, conditions[0]);
  dom.compareFixed.textContent = fixed;
  dom.seriesOptions.innerHTML = conditions.map((condition, index) => {
    const checked = state.selectedCompareKeys.has(condition.key);
    const color = seriesColor(index);
    return `<label><input type="checkbox" value="${condition.key}" ${checked ? "checked" : ""}>
      <span class="series-swatch" style="display:inline-block;width:18px;height:3px;background:${color};border-radius:3px"></span>
      ${escapeHtml(seriesLabel(condition, state.compareDimension))}</label>`;
  }).join("");
}

function setCompareDefaults() {
  const conditions = compareCandidates();
  state.selectedCompareKeys = new Set(conditions.map(condition => condition.key));
}

function compareCandidates() {
  const dimension = state.compareDimension;
  let candidates;
  if (["length_um", "vds_v", "vbs_v"].includes(dimension)) {
    candidates = state.conditions.filter(condition =>
      condition.corner === "tt" && equalValue(condition.temperature_c, 27)
      && (dimension === "length_um" || equalValue(condition.length_um, 0.15))
      && (dimension === "vds_v" || equalValue(condition.vds_v, 0.9))
      && (dimension === "vbs_v" || equalValue(condition.vbs_v, 0)));
  } else {
    candidates = state.conditions.filter(condition =>
      equalValue(condition.length_um, 0.15) && equalValue(condition.vds_v, 0.9)
      && equalValue(condition.vbs_v, 0)
      && (dimension === "corner" ? equalValue(condition.temperature_c, 27) : condition.corner === "tt"));
  }
  return candidates.sort((a, b) => compareValues(a[dimension], b[dimension]));
}

function getVisibleSeries() {
  if (state.mode === "explore") return [state.explore];
  return compareCandidates().filter(condition => state.selectedCompareKeys.has(condition.key));
}

function renderSelection() {
  const series = getVisibleSeries();
  if (state.mode === "explore") {
    const c = series[0];
    dom.selectionDescription.textContent = `${c.corner.toUpperCase()} · ${formatNumber(c.temperature_c, 0)} °C · L=${formatNumber(c.length_um, 2)} µm · VDS=${formatNumber(c.vds_v, 2)} V · VBS=${formatNumber(c.vbs_v, 2)} V`;
  } else {
    dom.selectionDescription.textContent = `${FIELD_META[state.compareDimension].label} comparison · ${series.length} visible series`;
  }
}

function renderVisualsAndDetails() {
  renderSelection();
  CHARTS.forEach(config => renderChart(config));
  renderOperatingPoint();
}

function scheduleVisualRender() {
  if (state.renderPending || !state.conditions.length) return;
  state.renderPending = true;
  requestAnimationFrame(() => {
    state.renderPending = false;
    renderVisualsAndDetails();
  });
}

function renderChart(config) {
  const svg = document.getElementById(config.id);
  const width = Math.max(320, Math.floor(svg.getBoundingClientRect().width || 560));
  const height = Math.max(260, Math.floor(svg.getBoundingClientRect().height || 310));
  const margin = { top: 12, right: 14, bottom: 46, left: 64 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const series = getVisibleSeries();
  const observations = series.flatMap(condition => condition.points
    .filter(point => point.gmid_per_v >= 4 && point.gmid_per_v <= 24)
    .map(point => ({ x: point.gmid_per_v, y: point[config.key] * (config.scale || 1) }))
    .filter(point => Number.isFinite(point.y) && (!config.log || point.y > 0)));

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.replaceChildren();
  if (!observations.length) return;

  const xMin = 4;
  const xMax = 24;
  const yValues = observations.map(point => point.y);
  const [yMin, yMax] = paddedDomain(yValues, config.log);
  const xScale = value => margin.left + (value - xMin) / (xMax - xMin) * plotWidth;
  const yScale = config.log
    ? value => margin.top + (Math.log10(yMax) - Math.log10(value)) / (Math.log10(yMax) - Math.log10(yMin)) * plotHeight
    : value => margin.top + (yMax - value) / (yMax - yMin) * plotHeight;

  appendSvg(svg, "rect", { class: "plot-frame", x: margin.left, y: margin.top, width: plotWidth, height: plotHeight });
  const xTicks = width < 440 ? [4, 8, 12, 16, 20, 24] : [4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24];
  xTicks.forEach(tick => {
    const x = xScale(tick);
    appendSvg(svg, "line", { class: "grid-line", x1: x, y1: margin.top, x2: x, y2: margin.top + plotHeight });
    appendText(svg, tick.toString(), x, margin.top + plotHeight + 18, { "text-anchor": "middle" });
  });
  const yTicks = config.log ? logTicks(yMin, yMax) : linearTicks(yMin, yMax, 5);
  yTicks.forEach(tick => {
    const y = yScale(tick);
    appendSvg(svg, "line", { class: "grid-line", x1: margin.left, y1: y, x2: margin.left + plotWidth, y2: y });
    appendText(svg, formatTick(tick, config.log), margin.left - 9, y + 4, { "text-anchor": "end" });
  });
  appendText(svg, "gm/ID [V⁻¹]", margin.left + plotWidth / 2, height - 8, { class: "axis-title", "text-anchor": "middle" });
  const yTitle = appendText(svg, config.yLabel, 15, margin.top + plotHeight / 2, { class: "axis-title", "text-anchor": "middle" });
  yTitle.setAttribute("transform", `rotate(-90 15 ${margin.top + plotHeight / 2})`);

  series.forEach((condition, index) => {
    const points = condition.points.filter(point =>
      point.gmid_per_v >= xMin && point.gmid_per_v <= xMax
      && Number.isFinite(point[config.key]) && (!config.log || point[config.key] > 0));
    const pathData = points.map((point, pointIndex) => {
      const x = xScale(point.gmid_per_v);
      const y = yScale(point[config.key] * (config.scale || 1));
      return `${pointIndex ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(" ");
    appendSvg(svg, "path", { class: "series-line", d: pathData, stroke: seriesColor(index) });
    const selected = interpolate(condition.points, state.gmid);
    if (selected) {
      appendSvg(svg, "circle", {
        class: "cursor-point", cx: xScale(state.gmid),
        cy: yScale(selected[config.key] * (config.scale || 1)), r: 4.5,
        fill: seriesColor(index),
      });
    }
  });

  const cursorX = xScale(state.gmid);
  appendSvg(svg, "line", { class: "cursor-line", x1: cursorX, y1: margin.top, x2: cursorX, y2: margin.top + plotHeight });
  const hit = appendSvg(svg, "rect", {
    class: "hit-area", x: margin.left, y: margin.top, width: plotWidth, height: plotHeight,
    tabindex: "0", "aria-label": `Set gm over ID cursor for ${config.yLabel}`,
  });
  const updateFromPointer = event => {
    const rect = svg.getBoundingClientRect();
    const localX = (event.clientX - rect.left) * width / rect.width;
    const value = xMin + (localX - margin.left) / plotWidth * (xMax - xMin);
    setGmid(Math.max(xMin, Math.min(xMax, value)));
  };
  hit.addEventListener("pointerdown", updateFromPointer);
  hit.addEventListener("pointermove", event => { if (event.buttons === 1) updateFromPointer(event); });
  hit.addEventListener("keydown", event => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      setGmid(state.gmid + (event.key === "ArrowRight" ? 0.1 : -0.1));
    }
  });

  const liveValues = series.map(condition => interpolate(condition.points, state.gmid))
    .filter(Boolean).map(point => point[config.key] * (config.scale || 1));
  document.getElementById(config.valueId).textContent = formatRange(liveValues, config.unit);
}

function renderOperatingPoint() {
  const series = getVisibleSeries();
  const selected = series.map((condition, index) => ({
    condition,
    color: seriesColor(index),
    label: state.mode === "explore" ? "Selected" : seriesLabel(condition, state.compareDimension),
    point: interpolate(condition.points, state.gmid),
  }));
  const available = selected.filter(item => item.point);
  dom.availability.className = "availability";
  if (available.length === selected.length) {
    dom.availability.textContent = "Available";
    dom.availability.classList.add("is-available");
  } else if (!available.length) {
    dom.availability.textContent = "Unavailable at this gm/ID";
    dom.availability.classList.add("is-unavailable");
  } else {
    dom.availability.textContent = `${available.length}/${selected.length} series available`;
    dom.availability.classList.add("is-unavailable");
  }

  const primary = [
    ["ID/W", "id_w_ua_per_um", "µA/µm", 4, 1],
    ["gm/gds", "gmro", "", 4, 1],
    ["fT", "ft_hz", "GHz", 4, 1e-9],
    ["VGS", "vgs_v", "V", 4, 1],
  ];
  dom.opPrimary.innerHTML = primary.map(([label, key, unit, digits, scale]) => {
    const values = available.map(item => item.point[key] * scale);
    return `<div class="metric"><span class="metric-label">${label}</span>
      <span class="metric-value">${escapeHtml(formatRange(values, unit, digits))}</span></div>`;
  }).join("");

  const thead = dom.opTable.querySelector("thead");
  const tbody = dom.opTable.querySelector("tbody");
  thead.innerHTML = `<tr><th scope="col">Parameter</th>${selected.map(item =>
    `<th scope="col"><span style="color:${item.color}">●</span> ${escapeHtml(item.label)}</th>`).join("")}</tr>`;
  tbody.innerHTML = DETAIL_METRICS.map(([label, key, unit, digits, scale = 1]) =>
    `<tr><th scope="row">${label}</th>${selected.map(item =>
      `<td>${item.point ? escapeHtml(formatWithUnit(item.point[key] * scale, unit, digits)) : "—"}</td>`).join("")}</tr>`
  ).join("");
}

function setMode(mode) {
  state.mode = mode;
  const explore = mode === "explore";
  dom.tabExplore.classList.toggle("is-active", explore);
  dom.tabCompare.classList.toggle("is-active", !explore);
  dom.tabExplore.setAttribute("aria-selected", String(explore));
  dom.tabCompare.setAttribute("aria-selected", String(!explore));
  dom.panelExplore.hidden = !explore;
  dom.panelCompare.hidden = explore;
  renderAll();
}

function setGmid(value, render = true) {
  if (!Number.isFinite(value)) return;
  state.gmid = Math.round(Math.max(4, Math.min(24, value)) * 10) / 10;
  dom.gmidSlider.value = String(state.gmid);
  dom.gmidInput.value = state.gmid.toFixed(1);
  dom.gmidOutput.textContent = `${state.gmid.toFixed(1)} V⁻¹`;
  if (render) scheduleVisualRender();
}

function findNominalCondition() {
  return state.conditions.find(condition =>
    condition.corner === "tt" && equalValue(condition.temperature_c, 27)
    && equalValue(condition.length_um, 0.15) && equalValue(condition.vds_v, 0.9)
    && equalValue(condition.vbs_v, 0)) || state.conditions[0];
}

function interpolate(points, x) {
  if (!points.length || x < points[0].gmid_per_v || x > points[points.length - 1].gmid_per_v) return null;
  let low = 0;
  let high = points.length - 1;
  while (high - low > 1) {
    const mid = Math.floor((low + high) / 2);
    if (points[mid].gmid_per_v <= x) low = mid;
    else high = mid;
  }
  const a = points[low];
  const b = points[high];
  const span = b.gmid_per_v - a.gmid_per_v;
  const ratio = span === 0 ? 0 : (x - a.gmid_per_v) / span;
  const result = {};
  Object.keys(a).forEach(key => {
    result[key] = typeof a[key] === "number" && typeof b[key] === "number"
      ? a[key] + (b[key] - a[key]) * ratio
      : a[key];
  });
  result.gmid_per_v = x;
  return result;
}

async function copyCurrentPoint() {
  const rows = operatingPointRows();
  if (!rows.length) return setActionStatus("当前 gm/ID 下没有可复制的工作点");
  const headers = Object.keys(rows[0]);
  const text = [headers.join("\t"), ...rows.map(row => headers.map(header => row[header]).join("\t"))].join("\n");
  try {
    await navigator.clipboard.writeText(text);
    setActionStatus(`已复制 ${rows.length} 个工作点`);
  } catch {
    setActionStatus("浏览器未允许剪贴板访问，请使用 HTTPS 或 localhost");
  }
}

function operatingPointRows() {
  return getVisibleSeries().map(condition => {
    const point = interpolate(condition.points, state.gmid);
    if (!point) return null;
    return {
      corner: condition.corner,
      temperature_c: condition.temperature_c,
      length_um: condition.length_um,
      vds_v: condition.vds_v,
      vbs_v: condition.vbs_v,
      gmid_per_v: state.gmid,
      vgs_v: point.vgs_v,
      id_w_ua_per_um: point.id_w_ua_per_um,
      gmro: point.gmro,
      ft_hz: point.ft_hz,
      gmb_over_gm: point.gmb_over_gm,
      vth_v: point.vth_v,
      vdsat_v: point.vdsat_v,
    };
  }).filter(Boolean);
}

function downloadCurrentSlice() {
  const series = getVisibleSeries();
  const headers = [
    "series", "corner", "temperature_c", "length_um", "vds_v", "vbs_v",
    "gmid_per_v", "vgs_v", "vth_v", "vov_v", "vdsat_v", "id_w_ua_per_um",
    "gm_s", "gds_s", "gmb_s", "gmb_over_gm", "gmro", "ft_hz", "cgg_f",
    "cgs_f", "cgd_f", "cgb_f", "cdb_f",
  ];
  const lines = [headers.join("\t")];
  series.forEach(condition => condition.points.forEach(point => {
    const prefix = [
      seriesLabel(condition, state.mode === "compare" ? state.compareDimension : "corner"),
      condition.corner, condition.temperature_c, condition.length_um, condition.vds_v, condition.vbs_v,
    ];
    lines.push([...prefix, ...headers.slice(6).map(header => point[header])].join("\t"));
  }));
  const blob = new Blob([lines.join("\n")], { type: "text/tab-separated-values;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `sky130_mos_${state.mode}_${state.gmid.toFixed(1).replace(".", "p")}.tsv`;
  anchor.click();
  URL.revokeObjectURL(url);
  setActionStatus(`已导出 ${series.length} 条曲线`);
}

function showLoadError(error) {
  dom.workspace.setAttribute("aria-busy", "false");
  dom.datasetStatus.textContent = "数据载入失败";
  dom.datasetStatus.classList.add("is-error");
  dom.errorBanner.hidden = false;
  dom.errorBanner.innerHTML = `无法读取 <code>${DATA_URL}</code>（${escapeHtml(error.message)}）。请先生成特性表，然后在 <code>practice/sky130</code> 目录运行 <code>python -m http.server 8000</code>，访问 <code>http://localhost:8000/web/</code>。`;
}

function conditionKey(row) {
  return `${row.corner}|${row.temperature_c}|${row.length_um}|${row.vds_v}|${row.vbs_v}`;
}

function fixedDescription(dimension, condition) {
  if (!condition) return "没有可比较的数据";
  const fields = CONDITION_FIELDS.filter(field => field !== dimension);
  return `固定条件：${fields.map(field => `${FIELD_META[field].label} ${FIELD_META[field].format(condition[field])}`).join(" · ")}`;
}

function seriesLabel(condition, dimension) {
  return FIELD_META[dimension]?.format(condition[dimension]) || condition.corner.toUpperCase();
}

function paddedDomain(values, logarithmic) {
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (logarithmic) {
    min = Math.max(min, Number.MIN_VALUE);
    const logMin = Math.log10(min);
    const logMax = Math.log10(max);
    const padding = Math.max(0.08, (logMax - logMin) * 0.08);
    return [10 ** (logMin - padding), 10 ** (logMax + padding)];
  }
  if (min === max) return [min - 1, max + 1];
  const padding = (max - min) * 0.08;
  return [Math.max(0, min - padding), max + padding];
}

function logTicks(min, max) {
  const ticks = [];
  for (let exponent = Math.ceil(Math.log10(min)); exponent <= Math.floor(Math.log10(max)); exponent += 1) {
    ticks.push(10 ** exponent);
  }
  if (ticks.length < 2) return linearTicks(min, max, 4);
  return ticks;
}

function linearTicks(min, max, count) {
  const rawStep = (max - min) / Math.max(1, count - 1);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const residual = rawStep / magnitude;
  const nice = residual >= 5 ? 5 : residual >= 2 ? 2 : 1;
  const step = nice * magnitude;
  const first = Math.ceil(min / step) * step;
  const ticks = [];
  for (let value = first; value <= max + step * 0.01; value += step) ticks.push(value);
  return ticks.length ? ticks : [min, max];
}

function appendSvg(parent, tag, attrs = {}) {
  const element = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, String(value)));
  parent.appendChild(element);
  return element;
}

function appendText(parent, content, x, y, attrs = {}) {
  const element = appendSvg(parent, "text", { x, y, ...attrs });
  element.textContent = content;
  return element;
}

function seriesColor(index) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--series-${index % 6 + 1}`).trim();
}

function formatRange(values, unit, digits = 4) {
  const finite = values.filter(Number.isFinite);
  if (!finite.length) return "—";
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  if (Math.abs(max - min) <= Math.max(1e-12, Math.abs(max) * 1e-6)) return formatWithUnit(min, unit, digits);
  return `${formatNumber(min, digits)}–${formatNumber(max, digits)}${unit ? ` ${unit}` : ""}`;
}

function formatWithUnit(value, unit, digits = 4) {
  if (!Number.isFinite(value)) return "—";
  return `${formatNumber(value, digits)}${unit ? ` ${unit}` : ""}`;
}

function formatNumber(value, digits = 4) {
  if (!Number.isFinite(Number(value))) return "—";
  const numeric = Number(value);
  const absolute = Math.abs(numeric);
  if (absolute !== 0 && (absolute >= 1e4 || absolute < 1e-3)) return numeric.toExponential(3);
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: digits }).format(numeric);
}

function formatTick(value, logarithmic) {
  if (logarithmic) {
    const exponent = Math.round(Math.log10(value));
    return `10^${exponent}`;
  }
  return formatNumber(value, 3);
}

function uniqueSorted(values) {
  return [...new Set(values.map(value => String(value)))].map(value => {
    const numeric = Number(value);
    return Number.isNaN(numeric) ? value : numeric;
  }).sort(compareValues);
}

function compareValues(a, b) {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b));
}

function equalValue(a, b) {
  if (typeof a === "number" || typeof b === "number") return Math.abs(Number(a) - Number(b)) < 1e-9;
  return String(a) === String(b);
}

function setActionStatus(message) {
  dom.actionStatus.textContent = message;
  window.clearTimeout(setActionStatus.timer);
  setActionStatus.timer = window.setTimeout(() => { dom.actionStatus.textContent = ""; }, 4000);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function toCamel(value) {
  return value.replace(/-([a-z])/g, (_, character) => character.toUpperCase());
}
