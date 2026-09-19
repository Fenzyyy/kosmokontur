/*
  Frontend adapter.
  ВАЖНО: расчёт выполняет fuel_model на Python API.
  JS только собирает JSON, отправляет его и отображает Result.
*/

const API_BASE = window.ENGINE_API_URL || ((location.protocol === "http:" || location.protocol === "https:") ? location.origin : "http://localhost:8000");

let defaults = null;
let lastResult = null;
let fuelChart = null;
let capexChart = null;

const $ = (id) => document.getElementById(id);
const fmt = (v, digits = 1) =>
  Number(v ?? 0).toLocaleString("ru-RU", { maximumFractionDigits: digits });

function setStatus(text, kind = "warn") {
  $("status").innerHTML = `<span class="badge ${kind}">${text}</span>`;
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  let data = null;
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) {
    const message = data?.detail || data?.error || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return data;
}

async function loadDefaults() {
  try {
    defaults = await api("/api/defaults");
    $("connection").className = "badge ok";
    $("connection").textContent = "API подключён";

    $("planJson").value = JSON.stringify(defaults.plan_template, null, 2);
    $("demandVariant").value = "base";
    $("scenarioKind").value = "base";
    $("isruStressShare").value = defaults.ui?.isru_stress_share ?? "";
    $("inputJson").textContent = JSON.stringify(defaults, null, 2);
  } catch (err) {
    $("connection").className = "badge bad";
    $("connection").textContent = "API недоступен";
    $("planError").textContent =
      `Не удалось подключиться к ${API_BASE}. Запустите backend/api.py. ${err.message}`;
  }
}

function parsePlan() {
  $("planError").textContent = "";
  try {
    const plan = JSON.parse($("planJson").value);
    if (!plan || typeof plan !== "object") throw new Error("Plan должен быть JSON-объектом.");
    return plan;
  } catch (err) {
    $("planError").textContent = `Ошибка JSON: ${err.message}`;
    throw err;
  }
}

function buildPayload() {
  const plan = parsePlan();

  const rawShare = $("isruStressShare").value.trim().replace(",", ".");
  const share = rawShare === "" ? null : Number(rawShare);

  if (share !== null && (!Number.isFinite(share) || share < 0 || share > 1)) {
    throw new Error("Доля поставки ISRU должна быть числом от 0 до 1.");
  }

  return {
    scenario_kind: $("scenarioKind").value,
    demand_variant: $("demandVariant").value,
    isru_stress_share: share,
    plan
  };
}

function renderKpis(data) {
  const k = data.kpis || {};
  $("kpis").innerHTML = [
    ["PV cost, млн у.е.", fmt(k.pv_cost)],
    ["Total cost, млн у.е.", fmt(k.total_cost)],
    ["CAPEX, млн у.е.", fmt(k.capex_total)],
    ["CAPEX до дедлайна, млн у.е.", fmt(k.capex_through_deadline)],
    ["Обслужено, т", fmt(k.served_total)],
    ["Дефицит, т", fmt(k.shortage_total)],
    ["Критический дефицит, т", fmt(k.shortage_critical)],
    ["Потери, т", fmt(k.losses_total)]
  ].map(([label, value]) =>
    `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div></div>`
  ).join("");
}

function renderTable(data) {
  const head = [
    "Год", "Спрос", "Критический спрос", "Поставка",
    "Потери", "Обслужено", "Дефицит", "Запас конец", "Резерв"
  ];
  $("resultTable").querySelector("thead").innerHTML =
    `<tr>${head.map(x => `<th>${x}</th>`).join("")}</tr>`;

  const rows = data.yearly || [];
  $("resultTable").querySelector("tbody").innerHTML = rows.map(r => `
    <tr>
      <td>${r.year}</td>
      <td>${fmt(r.demand_total)}</td>
      <td>${fmt(r.demand_critical)}</td>
      <td>${fmt(r.gross_inflow)}</td>
      <td>${fmt(r.losses)}</td>
      <td>${fmt(r.served_total)}</td>
      <td>${fmt(r.shortage_total)}</td>
      <td>${fmt(r.inventory_close)}</td>
      <td>${fmt(r.reserve_required)}</td>
    </tr>
  `).join("");
}

function renderChecks(data) {
  const violations = data.violations || [];
  if (!violations.length) {
    $("checks").innerHTML = `<div class="risk"><span class="badge ok">OK</span> Нарушений нет.</div>`;
    $("violations").innerHTML = `<div class="hint">Движок не вернул нарушений.</div>`;
    return;
  }

  const hard = violations.filter(v => v.severity === "HARD").length;
  const benchmark = violations.filter(v => v.severity === "BENCHMARK").length;

  $("checks").innerHTML = `
    <div class="risk"><span class="badge ${hard ? "bad" : "ok"}">${hard ? "НАРУШЕНИЯ" : "OK"}</span>
      HARD: ${hard}; benchmark: ${benchmark}</div>
    <div class="hint">Полный набор проверок находится в JSON результата.</div>
  `;

  $("violations").innerHTML = violations.map(v => `
    <div class="risk">
      <strong>${v.code || ""}</strong>
      <div class="hint">
        ${v.severity || ""}${v.year != null ? ` · ${v.year}` : ""}
        ${v.subject ? ` · ${v.subject}` : ""}
        ${v.message ? `<br>${v.message}` : ""}
      </div>
    </div>
  `).join("");
}


async function loadChartJs() {
  if (window.Chart) return true;
  return new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js";
    script.async = true;
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.head.appendChild(script);
  });
}

function renderCharts(data) {
  const yearly = data.yearly || [];
  const costs = data.costs || [];
  const labels = yearly.map(r => r.year);

  if (!window.Chart) return;
  if (fuelChart) fuelChart.destroy();
  if (capexChart) capexChart.destroy();

  fuelChart = new Chart($("fuelChart"), {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Запас на конец года, т",
        data: yearly.map(r => r.inventory_close),
        tension: 0.2
      }, {
        label: "Требуемый резерв, т",
        data: yearly.map(r => r.reserve_required),
        tension: 0.2
      }]
    },
    options: { responsive: true, maintainAspectRatio: false }
  });

  capexChart = new Chart($("capexChart"), {
    type: "bar",
    data: {
      labels: costs.map(r => r.year),
      datasets: [{
        label: "CAPEX, млн у.е.",
        data: costs.map(r => r.capex)
      }]
    },
    options: { responsive: true, maintainAspectRatio: false }
  });
}

function render(data) {
  lastResult = data;

  setStatus(data.feasible ? "Допустимый план" : "Есть нарушения",
            data.feasible ? "ok" : "bad");

  const meta = data.meta || {};
  $("strategyBox").innerHTML = `
    <strong>${meta.plan_name || meta.plan_id || "План двигателя"}</strong>
    <div class="hint">
      Сценарий: ${meta.scenario_name || meta.scenario_id || "—"} ·
      engine: ${meta.engine_version || "—"} ·
      горизонт: ${(meta.horizon || []).join("–")}
    </div>
  `;

  renderKpis(data);
  renderTable(data);
  renderChecks(data);
  renderCharts(data);

  $("outputJson").textContent = JSON.stringify(data, null, 2);
}

async function calculate() {
  try {
    await loadChartJs();
    const payload = buildPayload();
    $("inputJson").textContent = JSON.stringify(payload, null, 2);
    setStatus("Расчёт…", "warn");

    const data = await api("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    render(data);
  } catch (err) {
    console.error(err);
    setStatus("Ошибка", "bad");
    $("planError").textContent = err.message;
  }
}

function download(name, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 500);
}

$("calcBtn").addEventListener("click", calculate);

$("loadTemplate").addEventListener("click", () => {
  if (!defaults) return;
  $("planJson").value = JSON.stringify(defaults.plan_template, null, 2);
  $("planError").textContent = "";
});

$("formatPlan").addEventListener("click", () => {
  try {
    $("planJson").value = JSON.stringify(JSON.parse($("planJson").value), null, 2);
    $("planError").textContent = "";
  } catch (err) {
    $("planError").textContent = `Ошибка JSON: ${err.message}`;
  }
});

$("downloadJson").addEventListener("click", () => {
  if (lastResult) download(
    "fuel_model_result.json",
    JSON.stringify(lastResult, null, 2),
    "application/json"
  );
});

$("downloadCsv").addEventListener("click", () => {
  if (!lastResult) return;
  const rows = lastResult.yearly || [];
  const header = [
    "year", "demand_total", "demand_critical", "gross_inflow",
    "losses", "served_total", "shortage_total",
    "inventory_close", "reserve_required"
  ];
  const csv = [
    header.join(";"),
    ...rows.map(r => header.map(k => String(r[k] ?? "").replaceAll(";", ",")).join(";"))
  ].join("\n");
  download("fuel_model_yearly.csv", csv, "text/csv;charset=utf-8");
});

loadDefaults();
