const React = window.React;
const { useEffect, useMemo, useState } = React;
const e = React.createElement;

import { api } from "../utils/api.js";

function toast(message, isError = false) {
  window.alert(isError ? `Erro: ${message}` : message);
}

function normalizePair(raw) {
  return String(raw || "")
    .trim()
    .toUpperCase()
    .replace(/-/g, "/");
}

function normalizeExchange(raw) {
  return String(raw || "")
    .trim()
    .toLowerCase();
}

function splitPair(raw) {
  const token = normalizePair(raw);
  const parts = token.split("/");
  return {
    base: parts[0] || "",
    quote: parts[1] || ""
  };
}

function normalizeSpreadMap(spreadObj) {
  const normalized = {};
  Object.entries(spreadObj || {}).forEach(([key, value]) => {
    normalized[String(key || "").trim().toUpperCase()] = value;
  });
  return normalized;
}

function parsePairs(listValue) {
  return String(listValue || "")
    .split(",")
    .map((item) => normalizePair(item))
    .filter(Boolean);
}

function formatFieldIssue(field, issue) {
  const fieldLabel = {
    exchange: "Exchange",
    label: "Label",
    apiKey: "API Key",
    apiSecret: "API Secret",
    passphrase: "Passphrase"
  }[String(field || "").trim()] || field || "campo";

  const issueLabel = {
    invalid_length: "tamanho invalido",
    invalid_chars: "caracteres invalidos",
    invalid_exchange: "exchange invalida",
    invalid_status: "status invalido"
  }[String(issue || "").trim()] || issue || "valor invalido";

  return `${fieldLabel}: ${issueLabel}`;
}

function formatApiError(err, fallback) {
  if (!err) return fallback;
  const details = Array.isArray(err.details) ? err.details : [];
  const detailTxt = details.length ? ` (${details.map((d) => formatFieldIssue(d.field, d.issue)).join("; ")})` : "";
  const corr = err.correlationId ? ` (correlationId: ${err.correlationId})` : "";
  return `${err.message || fallback}${detailTxt}${corr}`;
}

function tone(status) {
  const val = String(status || "").toLowerCase();
  if (val === "ok" || val === "running") return "success";
  if (val === "stale" || val === "degraded") return "warning";
  return "danger";
}

function fmt(value) {
  if (value === null || typeof value === "undefined") return "-";
  if (typeof value === "number") return Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 8 });
  return String(value);
}

export function QuickStartFlow() {
  const auth = useMemo(() => api.getAuthContext(), []);
  const tenantId = auth.tenantId || "default";

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [credentials, setCredentials] = useState([]);
  const [exchangeStatus, setExchangeStatus] = useState([]);
  const [botConfigRows, setBotConfigRows] = useState([]);
  const [assetsPairs, setAssetsPairs] = useState({ assets: [], pairs: [] });
  const [globalConfig, setGlobalConfig] = useState({ mode: "PAPER", kill_switch_enabled: false });
  const [apiHealth, setApiHealth] = useState({});
  const [workerHealth, setWorkerHealth] = useState({});
  const [pairMids, setPairMids] = useState({});
  const [openOrders, setOpenOrders] = useState([]);
  const [bulkMappings, setBulkMappings] = useState([]);

  const [credentialForm, setCredentialForm] = useState({
    exchange: "novadax",
    label: "",
    apiKey: "",
    apiSecret: "",
    passphrase: ""
  });

  const [pairForm, setPairForm] = useState({
    pair: "VISTA/BRL",
    exchange: "novadax",
    buy_symbol: "VISTA/BRL",
    sell_symbol: "VISTA/BRL",
    onlyThisPair: true
  });

  const [strategyForm, setStrategyForm] = useState({
    buy_pct: 0.04,
    sell_pct: 0.04,
    risk_percentage: 11,
    stake_usdt: 25,
    oneSideWhenNoBalance: true
  });

  const selectedPair = normalizePair(pairForm.pair);

  const load = async () => {
    setLoading(true);
    try {
      const [credsData, statusData, botCfg, assetsData, globalCfg, health, worker, midsData, ordersData] = await Promise.all([
        api.getExchangeCredentials(tenantId),
        api.getExchangesStatus(tenantId),
        api.getBotConfig(),
        api.getAssetsPairs(tenantId),
        api.getBotGlobalConfig(),
        api.getHealth(),
        api.getWorkerHealth(),
        api.getMids(selectedPair || "VISTA/BRL"),
        api.getOrders("open")
      ]);

      const creds = Array.isArray(credsData) ? credsData : credsData.items || [];
      setCredentials(creds);
      setExchangeStatus((statusData && statusData.items) || []);
      setBotConfigRows((botCfg && botCfg.items) || []);
      setAssetsPairs(assetsData || { assets: [], pairs: [] });
      setGlobalConfig({
        mode: globalCfg.mode || "PAPER",
        kill_switch_enabled: !!globalCfg.kill_switch_enabled
      });
      setApiHealth(health || {});
      setWorkerHealth(worker || {});
      setPairMids((midsData && midsData.mids) || {});
      setOpenOrders((ordersData && ordersData.orders) || []);
    } catch (err) {
      toast(err.message || "Falha ao carregar fluxo rápido", true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!selectedPair) return;
    api
      .getMids(selectedPair)
      .then((data) => setPairMids((data && data.mids) || {}))
      .catch(() => {});
  }, [selectedPair]);

  const activeExchanges = useMemo(() => {
    const fromCreds = (credentials || [])
      .filter((c) => String(c.status || "").toUpperCase() === "ACTIVE")
      .map((c) => normalizeExchange(c.exchange))
      .filter(Boolean);
    const unique = Array.from(new Set(fromCreds));
    if (unique.length) return unique.sort((a, b) => a.localeCompare(b));
    return ["novadax", "mercadobitcoin", "gateio", "mexc"];
  }, [credentials]);

  useEffect(() => {
    const current = normalizeExchange(pairForm.exchange);
    if (activeExchanges.includes(current)) return;
    const fallback = activeExchanges[0] || "novadax";
    setPairForm((prev) => ({ ...prev, exchange: fallback }));
  }, [activeExchanges, pairForm.exchange]);

  useEffect(() => {
    const pair = normalizePair(pairForm.pair);
    if (!pair) return;

    const pairMappings = (assetsPairs.pairs || [])
      .filter((item) => normalizePair(item.pair) === pair)
      .reduce((acc, item) => {
        acc[normalizeExchange(item.exchange)] = {
          buy_symbol: normalizePair(item.buy_symbol || pair),
          sell_symbol: normalizePair(item.sell_symbol || pair)
        };
        return acc;
      }, {});

    setBulkMappings(
      activeExchanges.map((exchange) => {
        const existing = pairMappings[exchange] || null;
        return {
          exchange,
          buy_symbol: existing ? existing.buy_symbol : pair,
          sell_symbol: existing ? existing.sell_symbol : pair
        };
      })
    );
  }, [activeExchanges, assetsPairs.pairs, pairForm.pair]);

  const activeStatusByExchange = useMemo(() => {
    const map = {};
    (exchangeStatus || []).forEach((item) => {
      const ex = String(item.exchange || "").toLowerCase();
      if (!ex) return;
      map[ex] = item;
    });
    return map;
  }, [exchangeStatus]);

  const ensurePairEnabled = async (pair, riskOverride = null) => {
    const pairNorm = normalizePair(pair);
    const existing = (botConfigRows || []).find((row) => normalizePair(row.pair) === pairNorm);
    await api.upsertBotConfig({
      pair: pairNorm,
      enabled: true,
      strategy: (existing && existing.strategy) || "StrategySpread",
      risk_percentage: Number.isFinite(riskOverride) ? riskOverride : Number(strategyForm.risk_percentage || 0),
      max_percent_per_trade: (existing && existing.max_percent_per_trade) || 0,
      max_absolute_per_trade: (existing && existing.max_absolute_per_trade) || 0,
      max_open_orders_per_symbol: (existing && existing.max_open_orders_per_symbol) || 0,
      max_exposure_per_symbol: (existing && existing.max_exposure_per_symbol) || 0,
      kill_switch_enabled: false,
      max_daily_loss: (existing && existing.max_daily_loss) || 0
    });
  };

  const disableOtherPairsIfNeeded = async (pair) => {
    if (!pairForm.onlyThisPair) return;
    const pairNorm = normalizePair(pair);
    const latest = await api.getBotConfig();
    const rows = (latest && latest.items) || [];
    await Promise.all(
      rows.map((row) =>
        api.upsertBotConfig({
          ...row,
          pair: row.pair,
          enabled: normalizePair(row.pair) === pairNorm
        })
      )
    );
  };

  const run = async (fn, successMessage) => {
    try {
      setSaving(true);
      await fn();
      if (successMessage) toast(successMessage);
      await load();
    } catch (err) {
      toast(formatApiError(err, "Falha ao executar acao"), true);
    } finally {
      setSaving(false);
    }
  };

  const saveCredential = async (ev) => {
    ev.preventDefault();
    if (!credentialForm.apiKey || !credentialForm.apiSecret) {
      toast("Preencha API Key e API Secret", true);
      return;
    }
    await run(async () => {
      const created = await api.createExchangeCredential(tenantId, {
        exchange: credentialForm.exchange,
        label: credentialForm.label || `cred-${Date.now()}`,
        apiKey: credentialForm.apiKey,
        apiSecret: credentialForm.apiSecret,
        ...(credentialForm.passphrase.trim() ? { passphrase: credentialForm.passphrase.trim() } : {})
      });
      if (created && created.id) {
        await api.testExchangeCredential(tenantId, created.id);
      }
      setCredentialForm((prev) => ({ ...prev, apiKey: "", apiSecret: "", passphrase: "" }));
      setPairForm((prev) => ({ ...prev, exchange: credentialForm.exchange }));
    }, "Credencial salva e testada");
  };

  const testActiveCredential = async () => {
    const exchange = String(pairForm.exchange || "").toLowerCase();
    const active = (credentials || []).find(
      (c) => String(c.exchange || "").toLowerCase() === exchange && String(c.status || "").toUpperCase() === "ACTIVE"
    );
    if (!active) {
      toast(`Sem credencial ACTIVE para ${exchange}`, true);
      return;
    }
    await run(async () => {
      await api.testExchangeCredential(tenantId, active.id);
    }, `Credencial ${exchange} testada com sucesso`);
  };

  const savePair = async (ev) => {
    ev.preventDefault();
    const pair = normalizePair(pairForm.pair);
    const exchange = String(pairForm.exchange || "").trim().toLowerCase();
    const buy = normalizePair(pairForm.buy_symbol);
    const sell = normalizePair(pairForm.sell_symbol);
    if (!pair || !exchange || !buy || !sell) {
      toast("Preencha par, exchange, BUY e SELL", true);
      return;
    }

    await run(async () => {
      await api.upsertPairMapping(tenantId, {
        pair,
        exchange,
        buy_symbol: buy,
        sell_symbol: sell,
        enabled: true
      });

      await ensurePairEnabled(pair);
      await disableOtherPairsIfNeeded(pair);
    }, "Par salvo e automação ativada");
  };

  const updateBulkMapping = (exchange, patch) => {
    const ex = normalizeExchange(exchange);
    setBulkMappings((prev) =>
      prev.map((row) =>
        normalizeExchange(row.exchange) === ex
          ? {
              ...row,
              ...patch
            }
          : row
      )
    );
  };

  const applyBulkQuote = (exchange, quote) => {
    const { base } = splitPair(pairForm.pair);
    const q = String(quote || "").trim().toUpperCase();
    if (!base || !q) return;
    const local = `${base}/${q}`;
    updateBulkMapping(exchange, { buy_symbol: local, sell_symbol: local });
  };

  const saveBulkMappings = async () => {
    const pair = normalizePair(pairForm.pair);
    if (!pair || !pair.includes("/")) {
      toast("Informe um par global valido antes de salvar em lote", true);
      return;
    }

    const rows = (bulkMappings || [])
      .map((row) => ({
        exchange: normalizeExchange(row.exchange),
        buy_symbol: normalizePair(row.buy_symbol),
        sell_symbol: normalizePair(row.sell_symbol)
      }))
      .filter((row) => row.exchange);

    if (!rows.length) {
      toast("Nenhuma exchange para salvar no lote", true);
      return;
    }

    const invalidRow = rows.find((row) => !row.buy_symbol || !row.sell_symbol);
    if (invalidRow) {
      toast(`Preencha BUY e SELL para ${invalidRow.exchange}`, true);
      return;
    }

    await run(async () => {
      await Promise.all(
        rows.map((row) =>
          api.upsertPairMapping(tenantId, {
            pair,
            exchange: row.exchange,
            buy_symbol: row.buy_symbol,
            sell_symbol: row.sell_symbol,
            enabled: true
          })
        )
      );
      await ensurePairEnabled(pair);
      await disableOtherPairsIfNeeded(pair);
    }, "Mapeamento salvo em lote");
  };

  const saveStrategy = async (ev) => {
    ev.preventDefault();
    const pair = normalizePair(pairForm.pair);
    if (!pair) {
      toast("Informe o par primeiro", true);
      return;
    }

    const buyPct = Number.parseFloat(strategyForm.buy_pct);
    const sellPct = Number.parseFloat(strategyForm.sell_pct);
    const stakeUsdt = Number.parseFloat(strategyForm.stake_usdt);
    const riskPct = Number.parseFloat(strategyForm.risk_percentage);
    if (!Number.isFinite(buyPct) || !Number.isFinite(sellPct) || buyPct < 0 || sellPct < 0) {
      toast("% compra/% venda inválidos", true);
      return;
    }
    if (!Number.isFinite(stakeUsdt) || stakeUsdt <= 0) {
      toast("Stake em USDT deve ser maior que zero", true);
      return;
    }

    await run(async () => {
      const cfg = await api.getConfigLegacy();
      const spread = normalizeSpreadMap(cfg.spread || {});
      const pairUpper = pair.toUpperCase();
      spread[`${pairUpper}_BUY_PCT`] = buyPct;
      spread[`${pairUpper}_SELL_PCT`] = sellPct;
      delete spread[pairUpper];

      const stake = { ...(cfg.stake || {}) };
      const pairLower = pair.toLowerCase();
      stake[`${pairLower}_mode`] = "FIXO_USDT";
      stake[`${pairLower}_value`] = stakeUsdt;

      const pairSet = new Set(parsePairs(cfg.pairs && cfg.pairs.list));
      pairSet.add(pairUpper);

      await api.updateConfigLegacy({
        spread,
        stake,
        pairs: { list: Array.from(pairSet).sort((a, b) => a.localeCompare(b)).join(",") },
        router: {
          place_both_sides_per_exchange: !strategyForm.oneSideWhenNoBalance
        }
      });

      await ensurePairEnabled(pairUpper, Number.isFinite(riskPct) ? riskPct : 0);
    }, "Estratégia salva");
  };

  const setMode = async (mode) => {
    if (mode === "LIVE") {
      const ok = window.confirm("Isso envia ordens reais para a exchange. Confirma modo LIVE?");
      if (!ok) return;
    }
    await run(async () => {
      await api.updateBotGlobalConfig({
        mode,
        kill_switch_enabled: false
      });
    }, `Modo alterado para ${mode}`);
  };

  const pairHasOrders = useMemo(() => {
    const pair = normalizePair(pairForm.pair);
    return (openOrders || []).some((o) => normalizePair(o.pair || o.symbol) === pair);
  }, [openOrders, pairForm.pair]);

  const selectedMid = useMemo(() => {
    const values = Object.values(pairMids || {}).filter((v) => typeof v === "number" && Number.isFinite(v));
    return values.length ? values[0] : null;
  }, [pairMids]);

  const currentExchangeStatus = activeStatusByExchange[String(pairForm.exchange || "").toLowerCase()] || null;

  if (loading) {
    return e(
      "div",
      { className: "panel" },
      e("div", { className: "loading" }, e("div", { className: "loading-spinner" }), "Carregando fluxo guiado...")
    );
  }

  return e(
    "div",
    { className: "quick-flow-root" },
    e(
      "div",
      { className: "panel quick-flow-intro" },
      e("h2", null, "Fluxo Rápido"),
      e(
        "p",
        { className: "text-muted" },
        "Use este fluxo em ordem. Em geral basta: salvar credencial, salvar par, definir %/stake e escolher PAPER ou LIVE."
      ),
      e(
        "div",
        { className: "quick-status-grid" },
        e("div", { className: "quick-status-item" }, e("span", { className: `status-badge status-${tone(apiHealth.status)}` }, `API: ${apiHealth.status || "down"}`)),
        e("div", { className: "quick-status-item" }, e("span", { className: `status-badge status-${tone(workerHealth.status)}` }, `Worker: ${workerHealth.status || "down"}`)),
        e("div", { className: "quick-status-item" }, e("span", { className: `status-badge status-${tone(currentExchangeStatus && currentExchangeStatus.lastTestOk ? "ok" : "warning")}` }, `Exchange: ${pairForm.exchange || "-"} ${currentExchangeStatus && currentExchangeStatus.lastTestOk ? "OK" : "sem teste"}`)),
        e("div", { className: "quick-status-item" }, e("span", { className: `status-badge status-${selectedMid ? "success" : "warning"}` }, `Mid ${selectedPair || "-"}: ${selectedMid ? fmt(selectedMid) : "indisponível"}`))
      ),
      e(
        "div",
        { className: "actions-inline quick-flow-actions" },
        e("button", { className: "btn btn-secondary", onClick: load, disabled: saving }, saving ? "Processando..." : "Atualizar status"),
        e("button", { className: "btn btn-primary", onClick: () => setMode("PAPER"), disabled: saving || globalConfig.mode === "PAPER" }, "Modo PAPER"),
        e("button", { className: "btn btn-danger", onClick: () => setMode("LIVE"), disabled: saving || globalConfig.mode === "LIVE" }, "Modo LIVE")
      )
    ),

    e(
      "div",
      { className: "panel quick-step-card" },
      e("div", { className: "quick-step-header" }, e("span", { className: "quick-step-number" }, "1"), e("h3", null, "Credencial da Exchange")),
      e(
        "form",
        { className: "form-grid", onSubmit: saveCredential },
        e(
          "div",
          { className: "form-row" },
          e("label", null, "Exchange"),
          e(
            "select",
            { value: credentialForm.exchange, onChange: (ev) => setCredentialForm({ ...credentialForm, exchange: ev.target.value }) },
            e("option", { value: "novadax" }, "novadax"),
            e("option", { value: "gateio" }, "gateio"),
            e("option", { value: "mexc" }, "mexc"),
            e("option", { value: "mercadobitcoin" }, "mercadobitcoin")
          )
        ),
        e("div", { className: "form-row" }, e("label", null, "Label"), e("input", { value: credentialForm.label, placeholder: "Ex.: principal", onChange: (ev) => setCredentialForm({ ...credentialForm, label: ev.target.value }) })),
        e("div", { className: "form-row" }, e("label", null, "API Key"), e("input", { value: credentialForm.apiKey, onChange: (ev) => setCredentialForm({ ...credentialForm, apiKey: ev.target.value }), required: true })),
        e("div", { className: "form-row" }, e("label", null, "API Secret"), e("input", { value: credentialForm.apiSecret, onChange: (ev) => setCredentialForm({ ...credentialForm, apiSecret: ev.target.value }), required: true })),
        e("div", { className: "form-row" }, e("label", null, "Passphrase (opcional)"), e("input", { value: credentialForm.passphrase, onChange: (ev) => setCredentialForm({ ...credentialForm, passphrase: ev.target.value }) })),
        e(
          "div",
          { className: "form-actions" },
          e("button", { type: "submit", className: "btn btn-primary", disabled: saving }, "Salvar + Testar"),
          e("button", { type: "button", className: "btn btn-secondary", onClick: testActiveCredential, disabled: saving }, "Testar credencial ativa")
        )
      )
    ),

    e(
      "div",
      { className: "panel quick-step-card" },
      e("div", { className: "quick-step-header" }, e("span", { className: "quick-step-number" }, "2"), e("h3", null, "Par e Mapeamento")),
      e("p", { className: "text-muted" }, "Use um par global unico (ex.: VISTA/USDT) e mapeie o simbolo local por exchange (BRL ou USD/USDT)."),
      e(
        "form",
        { className: "form-grid", onSubmit: savePair },
        e("div", { className: "form-row" }, e("label", null, "Par"), e("input", { value: pairForm.pair, placeholder: "Ex.: VISTA/BRL", onChange: (ev) => setPairForm({ ...pairForm, pair: normalizePair(ev.target.value) }), required: true })),
        e(
          "div",
          { className: "form-row" },
          e("label", null, "Exchange"),
          e(
            "select",
            {
              value: pairForm.exchange,
              onChange: (ev) => setPairForm({ ...pairForm, exchange: normalizeExchange(ev.target.value) }),
              required: true
            },
            activeExchanges.map((ex) => e("option", { key: ex, value: ex }, ex))
          )
        ),
        e("div", { className: "form-row" }, e("label", null, "BUY Symbol"), e("input", { value: pairForm.buy_symbol, onChange: (ev) => setPairForm({ ...pairForm, buy_symbol: normalizePair(ev.target.value) }), required: true })),
        e("div", { className: "form-row" }, e("label", null, "SELL Symbol"), e("input", { value: pairForm.sell_symbol, onChange: (ev) => setPairForm({ ...pairForm, sell_symbol: normalizePair(ev.target.value) }), required: true })),
        e("label", { className: "checkbox-row" }, e("input", { type: "checkbox", checked: !!pairForm.onlyThisPair, onChange: (ev) => setPairForm({ ...pairForm, onlyThisPair: ev.target.checked }) }), "Deixar somente este par ativo"),
        e("div", { className: "form-actions" }, e("button", { type: "submit", className: "btn btn-primary", disabled: saving }, "Salvar par"))
      ),
      e(
        "div",
        { className: "quick-bulk-card" },
        e("h4", null, "Salvar simbolos em lote por exchange"),
        e("p", { className: "text-muted" }, "Exemplo VISTA: BRL nas exchanges brasileiras e USD/USDT nas internacionais."),
        !bulkMappings.length
          ? e("p", { className: "text-muted" }, "Adicione e teste credenciais ativas para preencher as exchanges automaticamente.")
          : e(
              "div",
              { className: "quick-bulk-list" },
              bulkMappings.map((row) =>
                e(
                  "div",
                  { className: "quick-bulk-row", key: `${selectedPair}-${row.exchange}` },
                  e("div", { className: "quick-bulk-exchange" }, row.exchange),
                  e(
                    "div",
                    { className: "actions-inline quick-bulk-quotes" },
                    e("button", { type: "button", className: "btn btn-secondary", onClick: () => applyBulkQuote(row.exchange, "BRL"), disabled: saving }, "BRL"),
                    e("button", { type: "button", className: "btn btn-secondary", onClick: () => applyBulkQuote(row.exchange, "USD"), disabled: saving }, "USD"),
                    e("button", { type: "button", className: "btn btn-secondary", onClick: () => applyBulkQuote(row.exchange, "USDT"), disabled: saving }, "USDT")
                  ),
                  e(
                    "div",
                    { className: "form-row" },
                    e("label", null, "BUY"),
                    e("input", {
                      value: row.buy_symbol,
                      onChange: (ev) => updateBulkMapping(row.exchange, { buy_symbol: normalizePair(ev.target.value) }),
                      placeholder: "Ex.: VISTA/BRL",
                      disabled: saving
                    })
                  ),
                  e(
                    "div",
                    { className: "form-row" },
                    e("label", null, "SELL"),
                    e("input", {
                      value: row.sell_symbol,
                      onChange: (ev) => updateBulkMapping(row.exchange, { sell_symbol: normalizePair(ev.target.value) }),
                      placeholder: "Ex.: VISTA/BRL",
                      disabled: saving
                    })
                  )
                )
              )
            ),
        e("div", { className: "form-actions" }, e("button", { type: "button", className: "btn btn-primary", onClick: saveBulkMappings, disabled: saving || !bulkMappings.length }, "Salvar lote"))
      )
    ),

    e(
      "div",
      { className: "panel quick-step-card" },
      e("div", { className: "quick-step-header" }, e("span", { className: "quick-step-number" }, "3"), e("h3", null, "Estratégia (Simples)")),
      e(
        "form",
        { className: "form-grid", onSubmit: saveStrategy },
        e("div", { className: "form-row" }, e("label", null, "% Compra"), e("input", { type: "number", step: "0.0001", min: "0", value: strategyForm.buy_pct, onChange: (ev) => setStrategyForm({ ...strategyForm, buy_pct: ev.target.value }), required: true })),
        e("div", { className: "form-row" }, e("label", null, "% Venda"), e("input", { type: "number", step: "0.0001", min: "0", value: strategyForm.sell_pct, onChange: (ev) => setStrategyForm({ ...strategyForm, sell_pct: ev.target.value }), required: true })),
        e("div", { className: "form-row" }, e("label", null, "Risco % por operação"), e("input", { type: "number", step: "0.01", min: "0", value: strategyForm.risk_percentage, onChange: (ev) => setStrategyForm({ ...strategyForm, risk_percentage: ev.target.value }) })),
        e("div", { className: "form-row" }, e("label", null, "Stake USDT"), e("input", { type: "number", step: "0.01", min: "0.01", value: strategyForm.stake_usdt, onChange: (ev) => setStrategyForm({ ...strategyForm, stake_usdt: ev.target.value }), required: true })),
        e("label", { className: "checkbox-row" }, e("input", { type: "checkbox", checked: !!strategyForm.oneSideWhenNoBalance, onChange: (ev) => setStrategyForm({ ...strategyForm, oneSideWhenNoBalance: ev.target.checked }) }), "Permitir operar só um lado quando faltar saldo"),
        e("div", { className: "form-actions" }, e("button", { type: "submit", className: "btn btn-primary", disabled: saving }, "Salvar estratégia"))
      )
    ),

    e(
      "div",
      { className: "panel quick-step-card" },
      e("div", { className: "quick-step-header" }, e("span", { className: "quick-step-number" }, "4"), e("h3", null, "Rodar")),
      e("p", { className: "text-muted" }, `Par atual: ${selectedPair || "-"} | Modo atual: ${globalConfig.mode || "PAPER"}`),
      e(
        "div",
        { className: "quick-summary-grid" },
        e("div", { className: "quick-summary-item" }, e("strong", null, "Mid"), e("div", null, selectedMid ? fmt(selectedMid) : "Aguardando preço")),
        e("div", { className: "quick-summary-item" }, e("strong", null, "Ordens abertas"), e("div", null, pairHasOrders ? "Sim" : "Não")),
        e("div", { className: "quick-summary-item" }, e("strong", null, "Credencial ativa"), e("div", null, (currentExchangeStatus && currentExchangeStatus.status) || "N/A")),
        e("div", { className: "quick-summary-item" }, e("strong", null, "Worker"), e("div", null, workerHealth.status || "N/A"))
      ),
      e(
        "div",
        { className: "actions-inline quick-flow-actions" },
        e("button", { className: "btn btn-secondary", onClick: load, disabled: saving }, "Atualizar agora"),
        e("button", { className: "btn btn-primary", onClick: () => setMode("PAPER"), disabled: saving || globalConfig.mode === "PAPER" }, "Rodar em PAPER"),
        e("button", { className: "btn btn-danger", onClick: () => setMode("LIVE"), disabled: saving || globalConfig.mode === "LIVE" }, "Rodar em LIVE")
      )
    )
  );
}
