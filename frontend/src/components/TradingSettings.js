const React = window.React;
const { useEffect, useState } = React;
const e = React.createElement;

import { api } from "../utils/api.js";
import { ExchangesSettings } from "./ExchangesSettings.js";
import { NotificationsSettings } from "./NotificationsSettings.js";

export function TradingSettings() {
  const { tenantId, roles } = api.getAuthContext();
  const isAdmin = (roles || "").split(",").map((x) => x.trim().toUpperCase()).includes("ADMIN");
  const [tab, setTab] = useState("credentials");
  const [pairs, setPairs] = useState([]);
  const [selectedPairId, setSelectedPairId] = useState(null);
  const [spread, setSpread] = useState({ enabled: true, percent: 1.0, sidePolicy: "BOTH" });
  const [arb, setArb] = useState({ enabled: false, mode: "TWO_LEG" });
  const [globalRisk, setGlobalRisk] = useState({});
  const [pairRisk, setPairRisk] = useState({});
  const [runtime, setRuntime] = useState(null);
  const [newPair, setNewPair] = useState({ exchange: "", symbol: "", enabled: true });

  const loadPairs = async () => {
    const res = await api.getPairs(tenantId);
    const items = res.items || [];
    setPairs(items);
    if (!selectedPairId && items.length) setSelectedPairId(items[0].id);
  };

  useEffect(() => { loadPairs(); api.getGlobalRisk(tenantId).then(setGlobalRisk).catch(() => {}); }, []);

  useEffect(() => {
    if (!selectedPairId) return;
    api.getPairSpread(tenantId, selectedPairId).then(setSpread).catch(() => {});
    api.getPairArbitrage(tenantId, selectedPairId).then(setArb).catch(() => {});
    api.getPairRisk(tenantId, selectedPairId).then(setPairRisk).catch(() => {});
    api.getPairRuntimeStatus(tenantId, selectedPairId).then(setRuntime).catch(() => {});
  }, [selectedPairId]);

  const save = async (fn) => { try { await fn(); window.alert("Salvo"); } catch (err) { window.alert(err.message || "Erro"); } };

  return e("div", { className: "panel" },
    e("h2", null, "Configurações → Trading"),
    e("div", { className: "tabs" },
      ["credentials", "pairs", "spread", "arbitrage", "risk", "alerts"].map((k) => e("button", { key: k, className: `tab-button${tab===k?" tab-button-active":""}`, onClick: () => setTab(k) }, k.toUpperCase()))
    ),

    tab === "credentials" && e(ExchangesSettings),
    tab === "alerts" && e(NotificationsSettings),

    tab === "pairs" && e("div", null,
      e("h3", null, "Pares"),
      e("div", { className: "form-row" }, e("input", { placeholder: "exchange", value: newPair.exchange, onChange: (ev) => setNewPair({ ...newPair, exchange: ev.target.value }), disabled: !isAdmin }), e("input", { placeholder: "BTC/USDT", value: newPair.symbol, onChange: (ev) => setNewPair({ ...newPair, symbol: ev.target.value }), disabled: !isAdmin }), isAdmin && e("button", { className: "btn", onClick: () => save(async () => { await api.createPair(tenantId, newPair); await loadPairs(); }) }, "Adicionar")),
      e("ul", null, pairs.map((p) => e("li", { key: p.id }, `${p.exchange} ${p.symbol} (${p.enabled ? "RUNNING" : "PAUSED"}) `,
        e("button", { className: "btn", onClick: () => setSelectedPairId(p.id) }, "Selecionar"),
        isAdmin && e("button", { className: "btn", onClick: () => save(async () => { await api.updatePair(tenantId, p.id, { enabled: !p.enabled }); await loadPairs(); }) }, p.enabled ? "Pausar" : "Ativar")
      )))
    ),

    ["spread", "arbitrage", "risk"].includes(tab) && !selectedPairId && e("p", null, "Selecione um par na aba Pairs."),

    tab === "spread" && selectedPairId && e("div", null,
      e("h3", null, "Spread"),
      e("div", { className: "form-row" }, e("label", null, "Enabled"), e("input", { type: "checkbox", checked: !!spread.enabled, disabled: !isAdmin, onChange: (ev) => setSpread({ ...spread, enabled: ev.target.checked }) })),
      e("div", { className: "form-row" }, e("label", null, "Percent"), e("input", { type: "number", step: "0.01", value: spread.percent || 0, disabled: !isAdmin, onChange: (ev) => setSpread({ ...spread, percent: parseFloat(ev.target.value || "0") || 0 }) })),
      isAdmin && e("button", { className: "btn", onClick: () => save(async () => { await api.updatePairSpread(tenantId, selectedPairId, spread); setRuntime(await api.getPairRuntimeStatus(tenantId, selectedPairId)); }) }, "Salvar"),
      runtime && e("p", null, `Aplicado no worker em: ${runtime.spreadAppliedAt || "-"}`)
    ),

    tab === "arbitrage" && selectedPairId && e("div", null,
      e("h3", null, "Arbitragem"),
      e("input", { placeholder: "exchange A", value: arb.exchangeA || "", disabled: !isAdmin, onChange: (ev) => setArb({ ...arb, exchangeA: ev.target.value }) }),
      e("input", { placeholder: "exchange B", value: arb.exchangeB || "", disabled: !isAdmin, onChange: (ev) => setArb({ ...arb, exchangeB: ev.target.value }) }),
      e("input", { type: "number", value: arb.thresholdPercent || 0, disabled: !isAdmin, onChange: (ev) => setArb({ ...arb, thresholdPercent: parseFloat(ev.target.value || "0") || 0 }) }),
      isAdmin && e("button", { className: "btn", onClick: () => save(async () => { await api.updatePairArbitrage(tenantId, selectedPairId, arb); setRuntime(await api.getPairRuntimeStatus(tenantId, selectedPairId)); }) }, "Salvar"),
      runtime && e("p", null, `Aplicado no worker em: ${runtime.arbitrageAppliedAt || "-"}`)
    ),

    tab === "risk" && selectedPairId && e("div", null,
      e("h3", null, "Risco Global"),
      e("input", { type: "number", value: globalRisk.maxPercentPerTrade || 0, disabled: !isAdmin, onChange: (ev) => setGlobalRisk({ ...globalRisk, maxPercentPerTrade: parseFloat(ev.target.value || "0") || 0 }) }),
      isAdmin && e("button", { className: "btn", onClick: () => save(async () => setGlobalRisk(await api.updateGlobalRisk(tenantId, globalRisk))) }, "Salvar Global"),
      e("h3", null, "Risco por Par"),
      e("input", { type: "number", value: pairRisk.maxOpenOrdersPerSymbol || 0, disabled: !isAdmin, onChange: (ev) => setPairRisk({ ...pairRisk, maxOpenOrdersPerSymbol: parseInt(ev.target.value || "0", 10) || 0 }) }),
      isAdmin && e("button", { className: "btn", onClick: () => save(async () => { await api.updatePairRisk(tenantId, selectedPairId, pairRisk); setRuntime(await api.getPairRuntimeStatus(tenantId, selectedPairId)); }) }, "Salvar Par"),
      runtime && e("p", null, `Aplicado no worker em: ${runtime.riskAppliedAt || "-"}`)
    )
  );
}
