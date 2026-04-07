const React = window.React;
const { useEffect, useMemo, useState } = React;
const e = React.createElement;

import { api } from "../utils/api.js";
import { MarketCatalog } from "./MarketCatalog.js";

function toast(message, isError = false) {
  window.alert(isError ? `Erro: ${message}` : message);
}

function toneFromStatus(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "ok" || normalized === "running") return "success";
  if (normalized === "stale" || normalized === "degraded") return "warning";
  return "danger";
}

function fmtIso(isoValue) {
  if (!isoValue) return "-";
  const d = new Date(isoValue);
  if (Number.isNaN(d.getTime())) return String(isoValue);
  return d.toLocaleString("pt-BR", { hour12: false });
}

export function ControlCenter() {
  const auth = useMemo(() => api.getAuthContext(), []);
  const tenantId = auth.tenantId || "default";

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [lastRefreshAt, setLastRefreshAt] = useState(null);

  const [globalCfg, setGlobalCfg] = useState({
    mode: "PAPER",
    loop_interval_ms: 2000,
    kill_switch_enabled: false,
    max_positions: 1,
    max_daily_loss: 0
  });
  const [pairRows, setPairRows] = useState([]);
  const [configStatus, setConfigStatus] = useState({});
  const [apiHealth, setApiHealth] = useState({});
  const [dbHealth, setDbHealth] = useState({});
  const [workerHealth, setWorkerHealth] = useState({});

  const loadAll = async () => {
    setLoading(true);
    try {
      const [globalData, pairData, cfgStatus, apiHealthData, dbHealthData, workerHealthData] = await Promise.all([
        api.getBotGlobalConfig(),
        api.getBotConfig(),
        api.getConfigStatus(),
        api.getHealth(),
        api.getDbHealth(),
        api.getWorkerHealth()
      ]);

      setGlobalCfg({
        mode: globalData.mode || "PAPER",
        loop_interval_ms: Number(globalData.loop_interval_ms || 2000),
        kill_switch_enabled: !!globalData.kill_switch_enabled,
        max_positions: Number(globalData.max_positions || 1),
        max_daily_loss: Number(globalData.max_daily_loss || 0)
      });
      setPairRows((pairData.items || []).map((item) => ({ ...item })));
      setConfigStatus(cfgStatus || {});
      setApiHealth(apiHealthData || {});
      setDbHealth(dbHealthData || {});
      setWorkerHealth(workerHealthData || {});
      setLastRefreshAt(new Date().toISOString());
      setError(null);
    } catch (err) {
      setError(err.message || "Falha ao carregar status do bot");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const runAction = async (action, successMessage) => {
    try {
      setBusy(true);
      await action();
      if (successMessage) toast(successMessage);
      await loadAll();
    } catch (err) {
      toast(err.message || "Falha ao executar acao", true);
    } finally {
      setBusy(false);
    }
  };

  const updatePair = (idx, key, value) => {
    setPairRows((prev) => prev.map((row, i) => (i === idx ? { ...row, [key]: value } : row)));
  };

  const savePair = async (row) => {
    await runAction(
      async () => {
        await api.upsertBotConfig(row);
      },
      `Par ${row.pair || "-"} salvo`
    );
  };

  const addPairFromCatalog = async (pair) => {
    const normalized = String(pair || "").trim().toUpperCase().replace("-", "/");
    if (!normalized) return;
    const alreadyExists = pairRows.some((row) => String(row.pair || "").trim().toUpperCase() === normalized);
    if (alreadyExists) {
      toast(`Par ${normalized} ja esta cadastrado.`);
      return;
    }
    await runAction(
      async () => {
        await api.upsertBotConfig({
          pair: normalized,
          enabled: true,
          strategy: "StrategySpread",
          risk_percentage: 0,
          max_percent_per_trade: 0,
          max_absolute_per_trade: 0,
          max_open_orders_per_symbol: 0,
          max_exposure_per_symbol: 0,
          kill_switch_enabled: false,
          max_daily_loss: 0
        });
      },
      `Par ${normalized} adicionado ao bot`
    );
  };

  const saveGlobal = async () => {
    await runAction(
      async () => {
        await api.updateBotGlobalConfig(globalCfg);
      },
      "Configuracao global atualizada"
    );
  };

  const setMode = async (nextMode) => {
    if (nextMode === "LIVE") {
      const ok = window.confirm("Voce esta ativando modo LIVE. Confirma?");
      if (!ok) return;
    }
    await runAction(
      async () => {
        await api.updateBotGlobalConfig({ mode: nextMode });
      },
      `Modo alterado para ${nextMode}`
    );
  };

  const setKillSwitch = async (enabled) => {
    await runAction(
      async () => {
        await api.updateBotGlobalConfig({ kill_switch_enabled: !!enabled });
      },
      enabled ? "Kill switch ativado" : "Kill switch desativado"
    );
  };

  const pauseAllPairs = async () => {
    if (!pairRows.length) {
      toast("Nao ha pares cadastrados para pausar", true);
      return;
    }
    await runAction(
      async () => {
        await Promise.all(pairRows.map((row) => api.upsertBotConfig({ ...row, enabled: false })));
      },
      "Todos os pares foram pausados"
    );
  };

  const resumeAllPairs = async () => {
    if (!pairRows.length) {
      toast("Nao ha pares cadastrados para retomar", true);
      return;
    }
    await runAction(
      async () => {
        await Promise.all(pairRows.map((row) => api.upsertBotConfig({ ...row, enabled: true })));
      },
      "Todos os pares foram retomados"
    );
  };

  const setLoopPreset = async (loopMs) => {
    await runAction(
      async () => {
        await api.updateBotGlobalConfig({ loop_interval_ms: Number(loopMs || 2000) });
      },
      `Loop atualizado para ${loopMs} ms`
    );
  };

  const openLogs = async () => {
    await runAction(
      async () => {
        const res = await api.openLogs();
        if (!res.ok) throw new Error("Abertura de logs nao suportada neste ambiente");
      },
      "Pasta de logs aberta"
    );
  };

  const apiTone = toneFromStatus(apiHealth.status || "down");
  const workerTone = toneFromStatus(workerHealth.status || "down");
  const dbTone = dbHealth.writable ? "success" : "danger";
  const syncTone = configStatus.in_sync ? "success" : "warning";

  if (loading) {
    return e(
      "div",
      { className: "panel" },
      e("div", { className: "loading" }, e("div", { className: "loading-spinner" }), e("div", null, "Carregando centro de controle..."))
    );
  }

  return e(
    "div",
    { className: "control-center-root" },
    error && e("div", { className: "alert alert-error" }, error),

    e(
      "div",
      { className: "panel" },
      e("h2", null, "Centro de Controle"),
      e("p", { className: "text-muted" }, `Tenant: ${tenantId} | Atualizado: ${fmtIso(lastRefreshAt)}`),
      e(
        "div",
        { className: "control-grid" },
        e("div", { className: "control-cell" }, e("span", { className: `status-badge status-${apiTone}` }, `API: ${apiHealth.status || "down"}`), e("div", null, `Versao: ${apiHealth.version || "-"}`)),
        e("div", { className: "control-cell" }, e("span", { className: `status-badge status-${workerTone}` }, `Worker: ${workerHealth.status || "down"}`), e("div", null, `PID: ${workerHealth.worker_pid || "-"}`)),
        e("div", { className: "control-cell" }, e("span", { className: `status-badge status-${dbTone}` }, `DB: ${dbHealth.writable ? "writable" : "degraded"}`), e("div", null, `Path: ${dbHealth.db_path || "-"}`)),
        e("div", { className: "control-cell" }, e("span", { className: `status-badge status-${syncTone}` }, `Config Sync: ${configStatus.in_sync ? "ok" : "pending"}`), e("div", null, `DB v${configStatus.db_config_version || "-"}`))
      ),
      e(
        "div",
        { className: "actions-inline control-actions-wrap" },
        e("button", { className: "btn btn-secondary", onClick: loadAll, disabled: busy }, "Atualizar status"),
        e("button", { className: "btn btn-secondary", onClick: openLogs, disabled: busy }, "Abrir logs"),
        e("button", { className: "btn btn-primary", onClick: () => setMode("PAPER"), disabled: busy || globalCfg.mode === "PAPER" }, "Modo PAPER"),
        e("button", { className: "btn btn-danger", onClick: () => setMode("LIVE"), disabled: busy || globalCfg.mode === "LIVE" }, "Modo LIVE"),
        e("button", { className: "btn btn-secondary", onClick: () => setKillSwitch(true), disabled: busy || !!globalCfg.kill_switch_enabled }, "Ativar kill switch"),
        e("button", { className: "btn btn-secondary", onClick: () => setKillSwitch(false), disabled: busy || !globalCfg.kill_switch_enabled }, "Desativar kill switch")
      )
    ),

    e(
      "div",
      { className: "panel" },
      e("h2", null, "Ajustes Rapidos"),
      e(
        "div",
        { className: "form-grid" },
        e("div", { className: "form-row" }, e("label", null, "Loop interval (ms)"), e("input", { type: "number", min: "100", value: globalCfg.loop_interval_ms, onChange: (ev) => setGlobalCfg({ ...globalCfg, loop_interval_ms: parseInt(ev.target.value || "2000", 10) || 2000 }) })),
        e("div", { className: "form-row" }, e("label", null, "Max positions"), e("input", { type: "number", min: "1", value: globalCfg.max_positions, onChange: (ev) => setGlobalCfg({ ...globalCfg, max_positions: parseInt(ev.target.value || "1", 10) || 1 }) })),
        e("div", { className: "form-row" }, e("label", null, "Max daily loss"), e("input", { type: "number", step: "0.01", min: "0", value: globalCfg.max_daily_loss, onChange: (ev) => setGlobalCfg({ ...globalCfg, max_daily_loss: parseFloat(ev.target.value || "0") || 0 }) }))
      ),
      e(
        "div",
        { className: "actions-inline control-actions-wrap" },
        e("button", { className: "btn btn-primary", onClick: saveGlobal, disabled: busy }, "Salvar ajustes"),
        e("button", { className: "btn btn-secondary", onClick: () => setLoopPreset(500), disabled: busy }, "Loop rapido (500ms)"),
        e("button", { className: "btn btn-secondary", onClick: () => setLoopPreset(2000), disabled: busy }, "Loop normal (2000ms)")
      )
    ),

    e(
      "div",
      { className: "panel" },
      e("h2", null, "Pares em Operacao"),
      e(
        "div",
        { className: "actions-inline control-actions-wrap" },
        e("button", { className: "btn btn-danger", onClick: pauseAllPairs, disabled: busy }, "Pausar todos os pares"),
        e("button", { className: "btn btn-primary", onClick: resumeAllPairs, disabled: busy }, "Retomar todos os pares")
      ),
      !pairRows.length
        ? e("p", { className: "text-muted" }, "Nenhum par cadastrado em config_pairs.")
        : e(
            "div",
            { className: "table-wrapper" },
            e(
              "table",
              { className: "table" },
              e("thead", null, e("tr", null, e("th", null, "Par"), e("th", null, "Ativo"), e("th", null, "Estrategia"), e("th", null, "Risk %"), e("th", null, "Max daily loss"), e("th", null, "Acao"))),
              e(
                "tbody",
                null,
                pairRows.map((row, idx) =>
                  e(
                    "tr",
                    { key: row.pair || idx },
                    e("td", null, e("input", { value: row.pair || "", onChange: (ev) => updatePair(idx, "pair", ev.target.value), disabled: busy })),
                    e("td", null, e("input", { type: "checkbox", checked: !!row.enabled, onChange: (ev) => updatePair(idx, "enabled", ev.target.checked), disabled: busy })),
                    e(
                      "td",
                      null,
                      e(
                        "select",
                        { value: row.strategy || "StrategySpread", onChange: (ev) => updatePair(idx, "strategy", ev.target.value), disabled: busy },
                        e("option", { value: "StrategySpread" }, "StrategySpread"),
                        e("option", { value: "StrategyArbitrageSimple" }, "StrategyArbitrageSimple")
                      )
                    ),
                    e("td", null, e("input", { type: "number", step: "0.01", value: row.risk_percentage || 0, onChange: (ev) => updatePair(idx, "risk_percentage", parseFloat(ev.target.value || "0") || 0), disabled: busy })),
                    e("td", null, e("input", { type: "number", step: "0.01", value: row.max_daily_loss || 0, onChange: (ev) => updatePair(idx, "max_daily_loss", parseFloat(ev.target.value || "0") || 0), disabled: busy })),
                    e("td", null, e("button", { className: "btn btn-secondary", onClick: () => savePair(row), disabled: busy }, "Salvar"))
                  )
                )
              )
            )
          )
    )
    ,
    e(MarketCatalog, { tenantId, onAddPair: addPairFromCatalog, disabled: busy })
  );
}
