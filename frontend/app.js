const $ = (id) => document.getElementById(id);

const api = (path, opts = {}) =>
  fetch(path, {
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    ...opts,
  }).then(async (r) => {
    if (!r.ok) {
      const t = await r.text();
      throw new Error(`[HTTP ${r.status}] ${t || r.statusText}`);
    }
    return r.json();
  });

const chartRefs = { hora: null, dia: null, unidades: null };

const CHART_TEXT = "#94a3b8";
const CHART_GRID = "rgba(148, 163, 184, 0.12)";

function chartScaleOpts(isHorizontalY) {
  const tick = { color: CHART_TEXT, maxRotation: isHorizontalY ? 0 : 45 };
  const grid = { color: CHART_GRID };
  return {
    x: isHorizontalY
      ? { beginAtZero: true, ticks: tick, grid: { ...grid, drawTicks: true } }
      : { ticks: tick, grid },
    y: isHorizontalY
      ? { ticks: tick, grid }
      : { beginAtZero: true, ticks: tick, grid, title: { display: true, text: "min", color: CHART_TEXT } },
  };
}
let totalRegistros = 0;

const MSG_SEM_DADOS_BASE =
  "A tabela atendimentos está vazia (0 registros). No PowerShell, na pasta backend, rode: python scripts\\import_excel.py --file \"C:\\Users\\Taina\\Downloads\\Tempo de Espera x Atendimento 1.xlsx\" --truncate — ou execute o script RODAR_PASSO_A_PASSO.ps1 na raiz do projeto. Depois atualize esta página (F5).";

async function loadMeta() {
  const m = await api("/api/meta");
  totalRegistros = Number(m.total_registros ?? 0);
  const unSel = $("unidade");
  const espSel = $("especialidade");
  const diaSel = $("dia");
  const horaSel = $("hora");

  unSel.innerHTML = '<option value="">Todas as unidades</option>' +
    m.unidades.map((u) => `<option value="${escapeAttr(u)}">${escapeHtml(u)}</option>`).join("");
  espSel.innerHTML = '<option value="">Todas as especialidades</option>' +
    m.especialidades.map((e) => `<option value="${escapeAttr(e)}">${escapeHtml(e)}</option>`).join("");

  diaSel.innerHTML =
    '<option value="">Qualquer dia</option>' +
    m.dias_semana.map((d) => `<option value="${escapeAttr(d)}">${escapeHtml(d)}</option>`).join("");
  horaSel.innerHTML =
    '<option value="">Qualquer hora</option>' +
    m.horas.map((h) => `<option value="${h}">${String(h).padStart(2, "0")}h</option>`).join("");

  if (totalRegistros === 0) {
    $("insight").textContent = MSG_SEM_DADOS_BASE;
  }
}

async function loadInsight() {
  if (totalRegistros === 0) {
    return;
  }
  try {
    const esp = $("especialidade").value || null;
    const url = esp ? `/api/insights/melhor-agora?especialidade=${encodeURIComponent(esp)}` : "/api/insights/melhor-agora";
    const data = await api(url);
    $("insight").textContent = data.mensagem || "";
  } catch {
    $("insight").textContent = "Conecte o banco e importe os dados para ver a dica “melhor opção agora”.";
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function escapeAttr(s) {
  return escapeHtml(s).replace(/'/g, "&#39;");
}

function readFilters() {
  return {
    q: $("q").value.trim() || null,
    unidade: $("unidade").value.trim() || null,
    especialidade: $("especialidade").value.trim() || null,
    dia_semana: $("dia").value.trim() || null,
    hora: $("hora").value === "" ? null : Number($("hora").value),
  };
}

function renderCards(top3, ctxText) {
  const wrap = $("cards");
  const empty = $("empty-state");
  $("result-context").textContent = ctxText || "";
  wrap.innerHTML = "";
  if (!top3.length) {
    empty.hidden = false;
    empty.textContent =
      totalRegistros === 0
        ? "Sem registros na base. Importe a planilha e atualize a página (F5)."
        : "Nenhum resultado para os filtros atuais.";
    return;
  }
  empty.hidden = true;
  const icons = ["🏥", "⏱️", "👨‍⚕️"];
  top3.forEach((row, i) => {
    const el = document.createElement("article");
    el.className = "card";
    el.innerHTML = `
      <div class="rank">${icons[i] || "🏥"} · ${i + 1}º lugar</div>
      <h3>${escapeHtml(row.nome_unidade)}</h3>
      <div><span class="pill">⏱ ${escapeHtml(String(row.tempo_medio_minutos))} min médios</span></div>
      <ul class="meta">
        <li><strong>Especialidade (recorte):</strong> ${escapeHtml(row.especialidade)}</li>
        <li><strong>Horário analisado:</strong> ${escapeHtml(row.horario_analisado)}</li>
        <li><strong>Dia analisado:</strong> ${escapeHtml(row.dia_semana)}</li>
        <li><strong>Amostras:</strong> ${row.amostras}</li>
      </ul>`;
    wrap.appendChild(el);
  });
}

async function runSearch() {
  const body = readFilters();
  const data = await api("/api/search", { method: "POST", body: JSON.stringify(body) });
  const f = body;
  const ctx = [
    f.dia_semana ? `Dia: ${f.dia_semana}` : null,
    f.hora != null ? `Hora: ${String(f.hora).padStart(2, "0")}h` : null,
    f.especialidade ? `Especialidade: ${f.especialidade}` : null,
    f.unidade ? `Unidade contém: ${f.unidade}` : null,
    f.q ? `Busca geral: “${f.q}”` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  renderCards(data.top3 || [], ctx);
  if (totalRegistros === 0) {
    $("insight").textContent = MSG_SEM_DADOS_BASE;
  } else {
    $("insight").textContent = data.mensagem_contexto || "";
  }
  await refreshCharts();
}

async function refreshCharts() {
  const u = $("unidade").value.trim();
  const e = $("especialidade").value.trim();
  const d = $("dia").value.trim();
  const h = $("hora").value === "" ? null : Number($("hora").value);

  const qs = (extra) => {
    const p = new URLSearchParams();
    if (u) p.set("unidade", u);
    if (e) p.set("especialidade", e);
    if (d) p.set("dia_semana", d);
    Object.entries(extra || {}).forEach(([k, v]) => {
      if (v != null && v !== "") p.set(k, String(v));
    });
    const s = p.toString();
    return s ? `?${s}` : "";
  };

  const [byHora, byDia, byUni] = await Promise.all([
    api(`/api/charts/por-hora${qs({ dia_semana: d || undefined })}`),
    api(`/api/charts/por-dia-semana${qs()}`),
    api(`/api/charts/comparacao-unidades${qs({ hora: h != null ? h : undefined, dia_semana: d || undefined, limit: 12 })}`),
  ]);

  if (byHora.serie?.length) {
    drawLine(
      "chart-hora",
      byHora.serie.map((x) => `${String(x.hora).padStart(2, "0")}h`),
      byHora.serie.map((x) => x.media_minutos),
      "hora",
    );
  } else {
    destroyChart("hora");
  }
  if (byDia.serie?.length) {
    drawBar("chart-dia", byDia.serie.map((x) => x.dia), byDia.serie.map((x) => x.media_minutos), "dia");
  } else {
    destroyChart("dia");
  }
  if (byUni.serie?.length) {
    drawBarH(
      "chart-unidades",
      byUni.serie.map((x) => x.unidade),
      byUni.serie.map((x) => x.media_minutos),
      "unidades",
    );
  } else {
    destroyChart("unidades");
  }
}

function destroyChart(key) {
  if (chartRefs[key]) {
    chartRefs[key].destroy();
    chartRefs[key] = null;
  }
}

function drawLine(canvasId, labels, values, key) {
  const ctx = $(canvasId).getContext("2d");
  destroyChart(key);
  chartRefs[key] = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Minutos (média)",
          data: values,
          borderColor: "#2dd4bf",
          backgroundColor: "rgba(45, 212, 191, 0.12)",
          fill: true,
          tension: 0.28,
          pointRadius: 3,
          pointBackgroundColor: "#38bdf8",
          pointBorderColor: "#0f1419",
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: chartScaleOpts(false),
    },
  });
}

function drawBar(canvasId, labels, values, key) {
  const ctx = $(canvasId).getContext("2d");
  destroyChart(key);
  chartRefs[key] = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Minutos (média)",
          data: values,
          backgroundColor: "rgba(45, 212, 191, 0.55)",
          borderColor: "rgba(45, 212, 191, 0.9)",
          borderWidth: 1,
          borderRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: chartScaleOpts(false),
    },
  });
}

function drawBarH(canvasId, labels, values, key) {
  const ctx = $(canvasId).getContext("2d");
  destroyChart(key);
  chartRefs[key] = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Minutos (média)",
          data: values,
          backgroundColor: "rgba(56, 189, 248, 0.45)",
          borderColor: "rgba(56, 189, 248, 0.85)",
          borderWidth: 1,
          borderRadius: 6,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          beginAtZero: true,
          ticks: { color: CHART_TEXT },
          grid: { color: CHART_GRID },
          title: { display: true, text: "min", color: CHART_TEXT },
        },
        y: {
          ticks: { color: CHART_TEXT },
          grid: { color: CHART_GRID },
        },
      },
    },
  });
}

let suggestTimer = null;
async function suggest(term) {
  const dl = $("suggestions");
  if (!term || term.length < 2) {
    dl.innerHTML = "";
    return;
  }
  const data = await api(`/api/suggest?term=${encodeURIComponent(term)}`);
  dl.innerHTML = data.suggestions.map((s) => `<option value="${escapeAttr(s.label)}"></option>`).join("");
}

async function init() {
  $("btn-search").addEventListener("click", () => runSearch().catch((e) => alert(e.message)));
  $("q").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") runSearch().catch((e) => alert(e.message));
  });
  $("q").addEventListener("input", () => {
    clearTimeout(suggestTimer);
    const v = $("q").value.trim();
    suggestTimer = setTimeout(() => suggest(v).catch(() => {}), 220);
  });
  ["unidade", "especialidade", "dia", "hora"].forEach((id) => {
    $(id).addEventListener("change", () => {
      loadInsight().catch(() => {});
    });
  });

  try {
    await loadMeta();
    await loadInsight();
    await runSearch();
  } catch (e) {
    const m = String(e && e.message ? e.message : e);
    const apiOkDbFail =
      /\[HTTP 503\]|\[HTTP 500\]/i.test(m) ||
      /Banco indispon|detail/i.test(m) ||
      /Can't connect|2003|Access denied/i.test(m);
    $("insight").textContent = apiOkDbFail
      ? "A página até pode abrir, mas o backend não consegue conectar no MySQL. Confira: serviço MySQL ligado no Windows; em backend\\.env a porta (geralmente 3306), usuário e senha; se o usuário 'saude' existe e tem permissão no banco saude_parnaiba (Workbench). Depois rode o importador e reinicie o uvicorn."
      : "Não foi possível falar com a API. 1) Abra http://127.0.0.1:8000/ (não abra o index.html pelo Explorer). 2) No PowerShell: cd backend → python -m uvicorn app.main:app --host 127.0.0.1 --port 8000. 3) MySQL rodando + importação do Excel.";
    console.error(e);
  }
}

document.addEventListener("DOMContentLoaded", init);
