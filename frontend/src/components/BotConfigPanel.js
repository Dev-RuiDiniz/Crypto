const React = window.React;
const { useEffect, useState } = React;
const e = React.createElement;

import { api } from "../utils/api.js";

function toast(message, isError = false) {
  window.alert(isError ? `Erro: ${message}` : message);
}

export function BotConfigPanel() {
  const [rows, setRows] = useState([]);
  const [globalCfg, setGlobalCfg] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [pairsData, globalData] = await Promise.all([
        api.getBotConfig(),
        api.getBotGlobalConfig()
      ]);
      setRows((pairsData.items || []).map((item) => ({ ...item })));
      setGlobalCfg({
        mode: globalData.mode || "PAPER",
        loop_interval_ms: globalData.loop_interval_ms || 2000,
        kill_switch_enabled: !!globalData.kill_switch_enabled,
        max_positions: globalData.max_positions || 1,
        max_daily_loss: globalData.max_daily_loss || 0
      });
    } catch (err) {
      toast(err.message || "Falha ao carregar configurações", true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const updateRow = (idx, key, value) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, [key]: value } : r)));
  };

  const saveRow = async (row) => {
    try {
      await api.upsertBotConfig(row);
      toast("Salvo com sucesso");
      await load();
    } catch (err) {
      toast(err.message || "Falha ao salvar par", true);
    }
  };

  const saveGlobal = async () => {
    try {
      await api.updateBotGlobalConfig(globalCfg);
      toast("Salvo com sucesso");
      await load();
    } catch (err) {
      toast(err.message || "Falha ao salvar config global", true);
    }
  };

  if (loading) return e("div", { className: "panel" }, "Carregando configurações do bot...");

  return e(
    "div",
    null,
    e(
      "div",
      { className: "panel" },
      e("h2", null, "Config Global (DB)"),
      globalCfg &&
        e(
          React.Fragment,
          null,
          e("div", { className: "form-row" },
            e("label", null, "Mode"),
            e("select", {
              value: globalCfg.mode,
              onChange: (ev) => setGlobalCfg({ ...globalCfg, mode: ev.target.value })
            }, e("option", { value: "PAPER" }, "PAPER"), e("option", { value: "LIVE" }, "LIVE"))
          ),
          e("div", { className: "form-row" },
            e("label", null, "Loop interval (ms)"),
            e("input", {
              type: "number",
              value: globalCfg.loop_interval_ms,
              onChange: (ev) => setGlobalCfg({ ...globalCfg, loop_interval_ms: parseInt(ev.target.value || "0", 10) || 0 })
            })
          ),
          e("div", { className: "form-row" },
            e("label", null, "Kill switch"),
            e("input", {
              type: "checkbox",
              checked: globalCfg.kill_switch_enabled,
              onChange: (ev) => setGlobalCfg({ ...globalCfg, kill_switch_enabled: ev.target.checked })
            })
          ),
          e("div", { className: "form-row" },
            e("label", null, "Max positions"),
            e("input", {
              type: "number",
              value: globalCfg.max_positions,
              onChange: (ev) => setGlobalCfg({ ...globalCfg, max_positions: parseInt(ev.target.value || "1", 10) || 1 })
            })
          ),
          e("div", { className: "form-row" },
            e("label", null, "Max daily loss"),
            e("input", {
              type: "number",
              step: "0.01",
              value: globalCfg.max_daily_loss,
              onChange: (ev) => setGlobalCfg({ ...globalCfg, max_daily_loss: parseFloat(ev.target.value || "0") || 0 })
            })
          ),
          e("button", { className: "btn", onClick: saveGlobal }, "Salvar")
        )
    ),
    e(
      "div",
      { className: "panel" },
      e("h2", null, "Config por Par (DB)"),
      e(
        "div",
        { className: "table-wrapper" },
        e(
          "table",
          { className: "table" },
          e("thead", null, e("tr", null,
            e("th", null, "Pair"),
            e("th", null, "Enabled"),
            e("th", null, "Strategy"),
            e("th", null, "Risk %"),
            e("th", null, "Max daily loss"),
            e("th", null, "Ações")
          )),
          e("tbody", null,
            rows.map((row, idx) => e("tr", { key: row.pair || idx },
              e("td", null, e("input", { value: row.pair || "", onChange: (ev) => updateRow(idx, "pair", ev.target.value) })),
              e("td", null, e("input", { type: "checkbox", checked: !!row.enabled, onChange: (ev) => updateRow(idx, "enabled", ev.target.checked) })),
              e("td", null, e("select", { value: row.strategy || "StrategySpread", onChange: (ev) => updateRow(idx, "strategy", ev.target.value) },
                e("option", { value: "StrategySpread" }, "StrategySpread")
              )),
              e("td", null, e("input", { type: "number", step: "0.01", value: row.risk_percentage || 0, onChange: (ev) => updateRow(idx, "risk_percentage", parseFloat(ev.target.value || "0") || 0) })),
              e("td", null, e("input", { type: "number", step: "0.01", value: row.max_daily_loss || 0, onChange: (ev) => updateRow(idx, "max_daily_loss", parseFloat(ev.target.value || "0") || 0) })),
              e("td", null, e("button", { className: "btn", onClick: () => saveRow(row) }, "Salvar"))
            )),
            e("tr", { key: "new" },
              e("td", { colSpan: 6 }, e("button", { className: "btn", onClick: () => setRows([...rows, { pair: "", enabled: true, strategy: "StrategySpread", risk_percentage: 0, max_daily_loss: 0 }]) }, "+ Adicionar par"))
            )
          )
        )
      )
    )
  );
}
