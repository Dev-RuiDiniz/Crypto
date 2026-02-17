// frontend/src/components/Dashboard.js

import { api } from "../utils/api.js";

const React = window.React;
const { useState, useEffect } = React;
const e = React.createElement;

const API_BASE = "http://127.0.0.1:8000/api";

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} ao acessar ${url}`);
  }
  return await res.json();
}

export function Dashboard(props) {
  const refreshMs = props.refreshMs || 2000;

  const [balances, setBalances] = useState({});
  const [mids, setMids] = useState({});
  const [pair, setPair] = useState("SOL-USDT");

  const [ordersPending, setOrdersPending] = useState([]);
  const [ordersOpen, setOrdersOpen] = useState([]);
  const [ordersClosed, setOrdersClosed] = useState([]);

  const [activeOrdersTab, setActiveOrdersTab] = useState("pending"); // pending | open | closed

  const [loading, setLoading] = useState(true); // loading só para o 1º load
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);

  const [error, setError] = useState(null);
  const [orderbookStatus, setOrderbookStatus] = useState([]);
  const [metrics, setMetrics] = useState({});
  const [configStatus, setConfigStatus] = useState({});

  // Loop de atualização
  useEffect(() => {
    let cancelled = false;

    async function loadAll() {
      if (!hasLoadedOnce) setLoading(true);

      try {
        const [
          balJson,
          ordersPendingJson,
          ordersOpenJson,
          ordersClosedJson,
          midsJson,
          obStatusJson,
          metricsJson,
          cfgStatusJson
        ] = await Promise.all([
          fetchJson(`${API_BASE}/balances`),
          fetchJson(`${API_BASE}/orders?state=pending`),
          fetchJson(`${API_BASE}/orders?state=open`),
          fetchJson(`${API_BASE}/orders?state=closed`),
          fetchJson(`${API_BASE}/mids?pair=${encodeURIComponent(pair)}`),
          fetchJson(`${API_BASE}/tenants/default/marketdata/orderbook-status`),
          api.getMetrics("default"),
          fetchJson(`${API_BASE}/config-status`)
        ]);

        if (cancelled) return;

        setBalances(balJson || {});
        setOrdersPending((ordersPendingJson && ordersPendingJson.orders) || []);
        setOrdersOpen((ordersOpenJson && ordersOpenJson.orders) || []);
        setOrdersClosed((ordersClosedJson && ordersClosedJson.orders) || []);
        setMids((midsJson && midsJson.mids) || {});
        setOrderbookStatus((obStatusJson && obStatusJson.items) || []);
        setMetrics(metricsJson || {});
        setConfigStatus(cfgStatusJson || {});
        setError(null);

        if (!hasLoadedOnce) {
          setHasLoadedOnce(true);
          setLoading(false);
        }
      } catch (err) {
        if (cancelled) return;
        console.error("[Dashboard] Erro ao buscar dados da API:", err);
        setError(err.message || "Erro ao carregar dados do bot");
        if (!hasLoadedOnce) setLoading(false);
      }
    }

    loadAll();
    const id = setInterval(loadAll, refreshMs);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pair, refreshMs, hasLoadedOnce]);

  // ====== helpers / métricas rápidas ======

  const exchangesCount = Object.keys(balances || {}).length;
  const pendingCount = ordersPending.length;
  const openCount = ordersOpen.length;
  const closedCount = ordersClosed.length;

  function formatNum(val, decimals = 4) {
    if (val === null || val === undefined || val === "") return "—";
    const n = typeof val === "number" ? val : parseFloat(val);
    if (Number.isNaN(n)) return String(val);
    return n.toFixed(decimals).replace(/\.?0+$/, "");
  }

  function truncateText(text, max = 28) {
    const s = String(text || "");
    if (s.length <= max) return s;
    return s.slice(0, max - 1) + "…";
  }

  // ====== render helpers ======

  function renderStats() {
    return e(
      "div",
      { className: "stats-grid" },
      e(
        "div",
        { className: "stat-card" },
        e("div", { className: "stat-value" }, exchangesCount || 0),
        e("div", { className: "stat-label" }, "Corretoras")
      ),
      e(
        "div",
        { className: "stat-card" },
        e("div", { className: "stat-value" }, pendingCount || 0),
        e("div", { className: "stat-label" }, "Ordens pendentes")
      ),
      e(
        "div",
        { className: "stat-card" },
        e("div", { className: "stat-value" }, openCount || 0),
        e("div", { className: "stat-label" }, "Ordens abertas")
      ),
      e(
        "div",
        { className: "stat-card" },
        e("div", { className: "stat-value" }, closedCount || 0),
        e("div", { className: "stat-label" }, "Ordens fechadas")
      )
    );
  }

  function renderBalances() {
    const exNames = Object.keys(balances || {});
    if (!exNames.length) {
      return e("p", { className: "panel-subtitle" }, "Nenhum saldo disponível (ainda).");
    }

    return e(
      "div",
      { className: "balances-grid" },
      exNames.map((exName) =>
        e(
          "div",
          { key: exName, className: "card" },
          e("h3", null, exName),
          e(
            "div",
            { className: "table-wrapper" }, // <- garante que saldo NUNCA vaze para fora do card
            e(
              "table",
              { className: "table" }, // <- sem table--wide aqui
              e(
                "thead",
                null,
                e(
                  "tr",
                  null,
                  e("th", null, "Ativo"),
                  e("th", null, "Livre"),
                  e("th", null, "Total")
                )
              ),
              e(
                "tbody",
                null,
                Object.entries(balances[exName] || {}).map(([asset, info]) =>
                  e(
                    "tr",
                    { key: asset },
                    e("td", null, asset),
                    e("td", { className: "numeric" }, formatNum(info.free, 6)),
                    e("td", { className: "numeric" }, formatNum(info.total, 6))
                  )
                )
              )
            )
          )
        )
      )
    );
  }

  function renderMidsPanel() {
    const exNames = Object.keys(mids || {});

    return e(
      "div",
      { className: "panel" },
      e(
        "div",
        { className: "panel-header" },
        e("h2", null, "Preço Médio do Ativo"),
        e(
          "div",
          { className: "pair-selector" },
          e("span", { style: { fontSize: "12px", color: "var(--text-secondary)" } }, "Par:"),
          e(
            "select",
            { value: pair, onChange: (ev) => setPair(ev.target.value) },
            e("option", { value: "SOL-USDT" }, "SOL-USDT"),
            e("option", { value: "BTC-USDT" }, "BTC-USDT"),
            e("option", { value: "ETH-USDT" }, "ETH-USDT")
          )
        )
      ),
      !exNames.length
        ? e("p", { className: "panel-subtitle" }, "Sem dados de midprice ainda.")
        : e(
            "div",
            { className: "mids-line" },
            exNames.map((exName) =>
              e(
                "span",
                { key: exName },
                exName,
                ": ",
                formatNum(mids[exName], 3)
              )
            )
          )
    );
  }




  function renderOperationalStatus() {
    const cb = metrics.circuitBreakerState || {};
    const wsItems = ((metrics.wsState || {}).items || []);
    const cbOpen = Object.entries(cb).find(([, val]) => (val || {}).state === "OPEN");
    const wsFallback = wsItems.find((r) => String((r && r.state) || "").toUpperCase() === "POLL_ACTIVE");

    let status = "RUNNING";
    let reason = "Sistema operando normalmente";
    if ((configStatus.worker_status || "").toLowerCase() !== "ok") {
      status = "PAUSED";
      reason = "Worker offline/stale";
    } else if (cbOpen) {
      status = "DEGRADED";
      reason = `Circuit breaker open (${cbOpen[0]})`;
    } else if (wsFallback) {
      status = "DEGRADED";
      reason = "MarketData fallback active";
    }

    return e("div", { className: "panel" },
      e("h2", null, "Status do Sistema"),
      e("div", { className: "mids-line" },
        e("strong", null, status),
        " · ",
        reason
      ),
      e("p", { className: "panel-subtitle" }, `Latência média: ${metrics.cycleLatencyMs || 0} ms | Ordens/min: ${metrics.ordersPerMinute || 0}`)
    );
  }

  function renderMarketDataPanel() {
    if (!orderbookStatus.length) {
      return e("div", { className: "panel" }, e("h2", null, "Market Data"), e("p", { className: "panel-subtitle" }, "Sem status de order book ainda."));
    }

    return e(
      "div",
      { className: "panel" },
      e("h2", null, "Market Data (Order Book)"),
      e(
        "div",
        { className: "table-wrapper" },
        e(
          "table",
          { className: "table table--wide" },
          e("thead", null, e("tr", null,
            e("th", null, "Exchange"),
            e("th", null, "Par"),
            e("th", null, "Fonte"),
            e("th", null, "Estado"),
            e("th", null, "Idade"),
            e("th", null, "Best Bid"),
            e("th", null, "Best Ask")
          )),
          e("tbody", null,
            orderbookStatus.map((row, idx) => e("tr", { key: `${row.exchange}-${row.symbol}-${idx}` },
              e("td", null, row.exchange || "—"),
              e("td", null, row.symbol || "—"),
              e("td", null, row.source || "—"),
              e("td", null, row.state || "—"),
              e("td", { className: "numeric" }, row.ageMs == null ? "—" : `${row.ageMs} ms`),
              e("td", { className: "numeric" }, row.bestBid && row.bestBid.price != null ? `${formatNum(row.bestBid.price, 6)} (${formatNum(row.bestBid.qty, 4)})` : "—"),
              e("td", { className: "numeric" }, row.bestAsk && row.bestAsk.price != null ? `${formatNum(row.bestAsk.price, 6)} (${formatNum(row.bestAsk.qty, 4)})` : "—")
            ))
          )
        )
      )
    );
  }

  function renderOrdersPanel() {
    let rows = [];
    if (activeOrdersTab === "pending") rows = ordersPending;
    if (activeOrdersTab === "open") rows = ordersOpen;
    if (activeOrdersTab === "closed") rows = ordersClosed;

    let emptyMsg = "Nenhuma ordem neste estado.";
    if (activeOrdersTab === "pending") emptyMsg = "Nenhuma ordem pendente.";
    if (activeOrdersTab === "open") emptyMsg = "Nenhuma ordem aberta.";
    if (activeOrdersTab === "closed") emptyMsg = "Nenhuma ordem fechada registrada.";

    return e(
      "div",
      { className: "panel orders-container" },
      e(
        "div",
        { className: "panel-header" },
        e("h2", null, "Ordens"),
        e(
          "div",
          { className: "tabs" },
          e(
            "button",
            {
              className: "tab-button" + (activeOrdersTab === "pending" ? " tab-button-active" : ""),
              onClick: () => setActiveOrdersTab("pending")
            },
            "Pendentes"
          ),
          e(
            "button",
            {
              className: "tab-button" + (activeOrdersTab === "open" ? " tab-button-active" : ""),
              onClick: () => setActiveOrdersTab("open")
            },
            "Abertas"
          ),
          e(
            "button",
            {
              className: "tab-button" + (activeOrdersTab === "closed" ? " tab-button-active" : ""),
              onClick: () => setActiveOrdersTab("closed")
            },
            "Fechadas"
          )
        )
      ),
      rows.length === 0
        ? e("div", { className: "orders-empty" }, emptyMsg)
        : e(
            "div",
            { className: "table-wrapper" }, // <- wrapper correto para segurar overflow
            e(
              "table",
              { className: "table table--wide" }, // <- wide só aqui (ordens têm muitas colunas)
              e(
                "thead",
                null,
                e(
                  "tr",
                  null,
                  e("th", null, "ID"),
                  e("th", null, "Exchange"),
                  e("th", null, "Par"),
                  e("th", null, "Side"),
                  e("th", null, "Preço"),
                  e("th", null, "Qtd"),
                  e("th", null, "Status"),
                  e("th", null, "Criada em")
                )
              ),
              e(
                "tbody",
                null,
                rows.map((o) =>
                  e(
                    "tr",
                    { key: o.id || `${o.exchange}-${o.pair}-${o.created_at}` },
                    e("td", null, truncateText(o.id || "—", 32)),
                    e("td", null, o.exchange || "—"),
                    e("td", null, o.pair || o.symbol_local || "—"),
                    e("td", null, o.side || "—"),
                    e("td", { className: "numeric" }, formatNum(o.price, 4)),
                    e("td", { className: "numeric" }, formatNum(o.amount, 6)),
                    e("td", null, o.status || "—"),
                    e("td", null, o.created_at || "—")
                  )
                )
              )
            )
          )
    );
  }

  // ====== render principal ======

  return e(
    "div",
    { className: "dashboard-root" },

    error &&
      e(
        "div",
        { className: "alert alert-error" },
        "Erro ao carregar dados: ",
        error
      ),

    // Loading apenas no primeiro load (usa classes existentes do main.css)
    loading &&
      e(
        "div",
        { className: "loading" },
        e("div", { className: "loading-spinner" }),
        e("div", null, "Atualizando dados do bot...")
      ),

    renderStats(),

    e(
      "div",
      { className: "dashboard-grid" },

      // Coluna esquerda (garante que o grid pode encolher sem overflow)
      e("div", { style: { minWidth: 0 } }, renderOrdersPanel()),

      // Coluna direita (garante que o grid pode encolher sem overflow)
      e(
        "div",
        { style: { minWidth: 0, display: "grid", gap: "24px" } },
        e(
          "div",
          { className: "panel" },
          e("div", { className: "panel-header" }, e("h2", null, "Saldos por corretora")),
          renderBalances()
        ),
        renderOperationalStatus(),
        renderMidsPanel(),
        renderMarketDataPanel()
      )
    )
  );
}
