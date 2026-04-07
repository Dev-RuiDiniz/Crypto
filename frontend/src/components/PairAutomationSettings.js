const React = window.React;
const { useEffect, useMemo, useState } = React;
const e = React.createElement;

import { api } from "../utils/api.js";

function toast(message, isError = false) {
  window.alert(isError ? `Erro: ${message}` : message);
}

function normalizePair(pair) {
  return String(pair || "").trim().toUpperCase();
}

function parsePairs(listValue) {
  return String(listValue || "")
    .split(",")
    .map((item) => normalizePair(item))
    .filter(Boolean);
}

function parseSpreadByPair(spreadObj) {
  const rows = {};
  const source = spreadObj || {};
  Object.entries(source).forEach(([rawKey, rawVal]) => {
    const key = String(rawKey || "").trim().toUpperCase();
    const value = Number.parseFloat(String(rawVal));
    if (!Number.isFinite(value)) return;

    if (key.endsWith("_BUY_PCT")) {
      const pair = key.slice(0, -8);
      rows[pair] = rows[pair] || { pair, buy_pct: "", sell_pct: "" };
      rows[pair].buy_pct = value;
      return;
    }
    if (key.endsWith("_SELL_PCT")) {
      const pair = key.slice(0, -9);
      rows[pair] = rows[pair] || { pair, buy_pct: "", sell_pct: "" };
      rows[pair].sell_pct = value;
      return;
    }
    if (key.includes("/")) {
      rows[key] = rows[key] || { pair: key, buy_pct: "", sell_pct: "" };
      rows[key].buy_pct = value;
      rows[key].sell_pct = value;
    }
  });
  return Object.values(rows).sort((a, b) => a.pair.localeCompare(b.pair));
}

function normalizeSpreadMap(spreadObj) {
  const normalized = {};
  Object.entries(spreadObj || {}).forEach(([key, value]) => {
    normalized[String(key || "").trim().toUpperCase()] = value;
  });
  return normalized;
}

export function PairAutomationSettings() {
  const auth = useMemo(() => api.getAuthContext(), []);
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState(null);
  const [assetsPairs, setAssetsPairs] = useState({ assets: [], pairs: [] });
  const [pairRows, setPairRows] = useState([]);
  const [pairForm, setPairForm] = useState({ pair: "", buy_pct: 0.1, sell_pct: 0.1 });
  const [routerForm, setRouterForm] = useState({
    anchor_mode: "LOCAL",
    track_local_bps: 15,
    reprice_cooldown_sec: 5,
    place_both_sides_per_exchange: true
  });

  const load = async () => {
    setLoading(true);
    try {
      const [cfg, assetsData] = await Promise.all([api.getConfigLegacy(), api.getAssetsPairs(auth.tenantId)]);
      setConfig(cfg);
      setAssetsPairs(assetsData || { assets: [], pairs: [] });
      setPairRows(parseSpreadByPair(cfg.spread || {}));
      setRouterForm({
        anchor_mode: ((cfg.router && cfg.router.anchor_mode) || "LOCAL").toUpperCase(),
        track_local_bps: Number.parseInt((cfg.router && cfg.router.track_local_bps) || 15, 10),
        reprice_cooldown_sec: Number.parseFloat((cfg.router && cfg.router.reprice_cooldown_sec) || 5),
        place_both_sides_per_exchange: !!(cfg.router && cfg.router.place_both_sides_per_exchange)
      });
    } catch (err) {
      toast(err.message || "Falha ao carregar automacao por par", true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const pairOptions = useMemo(() => {
    const configured = parsePairs(config && config.pairs && config.pairs.list);
    const mapped = (assetsPairs.pairs || []).map((item) => normalizePair(item.pair));
    return [...new Set([...configured, ...mapped])].sort((a, b) => a.localeCompare(b));
  }, [config, assetsPairs]);

  const savePairRule = async (ev) => {
    ev.preventDefault();
    const pair = normalizePair(pairForm.pair);
    if (!pair || !pair.includes("/")) {
      toast("Informe um par valido no formato BASE/QUOTE", true);
      return;
    }
    const buyPct = Number.parseFloat(pairForm.buy_pct);
    const sellPct = Number.parseFloat(pairForm.sell_pct);
    if (!Number.isFinite(buyPct) || !Number.isFinite(sellPct) || buyPct < 0 || sellPct < 0) {
      toast("Percentuais de compra/venda devem ser numeros >= 0", true);
      return;
    }

    try {
      const latest = await api.getConfigLegacy();
      const spread = normalizeSpreadMap(latest.spread || {});
      spread[`${pair}_BUY_PCT`] = buyPct;
      spread[`${pair}_SELL_PCT`] = sellPct;
      delete spread[pair];

      const pairsSet = new Set(parsePairs(latest.pairs && latest.pairs.list));
      pairsSet.add(pair);

      await api.updateConfigLegacy({
        spread,
        pairs: { list: Array.from(pairsSet).sort((a, b) => a.localeCompare(b)).join(",") }
      });
      toast(`Regra salva para ${pair}`);
      setPairForm({ pair: "", buy_pct: 0.1, sell_pct: 0.1 });
      await load();
    } catch (err) {
      toast(err.message || "Falha ao salvar regra do par", true);
    }
  };

  const removePairRule = async (pair) => {
    if (!window.confirm(`Remover regra de spread para ${pair}?`)) return;
    try {
      const latest = await api.getConfigLegacy();
      const spread = normalizeSpreadMap(latest.spread || {});
      delete spread[`${pair}_BUY_PCT`];
      delete spread[`${pair}_SELL_PCT`];
      delete spread[pair];
      await api.updateConfigLegacy({ spread });
      await load();
    } catch (err) {
      toast(err.message || "Falha ao remover regra", true);
    }
  };

  const saveRouter = async (ev) => {
    ev.preventDefault();
    try {
      await api.updateConfigLegacy({
        router: {
          anchor_mode: String(routerForm.anchor_mode || "LOCAL").toUpperCase(),
          track_local_bps: Number.parseInt(routerForm.track_local_bps || 0, 10),
          reprice_cooldown_sec: Number.parseFloat(routerForm.reprice_cooldown_sec || 0),
          place_both_sides_per_exchange: !!routerForm.place_both_sides_per_exchange
        }
      });
      toast("Parametros de flutuacao automatica salvos");
      await load();
    } catch (err) {
      toast(err.message || "Falha ao salvar parametros do robo", true);
    }
  };

  return e(
    "div",
    { className: "panel" },
    e("h2", null, "Automacao por Par"),
    e(
      "p",
      { className: "text-muted" },
      "Defina por par a % de compra e venda. O robo recalcula e reposiciona ordens automaticamente com base no book."
    ),
    e("button", { className: "btn btn-secondary", onClick: load, disabled: loading }, loading ? "Atualizando..." : "Atualizar"),
    loading && e("div", { className: "loading" }, e("div", { className: "loading-spinner" }), "Carregando..."),

    !loading &&
      e(
        "div",
        { className: "panel" },
        e("h3", null, "Parametros de Flutuacao"),
        e(
          "form",
          { className: "form-grid", onSubmit: saveRouter },
          e(
            "div",
            { className: "form-row" },
            e("label", null, "Modo de ancoragem"),
            e(
              "select",
              {
                value: routerForm.anchor_mode,
                onChange: (ev) => setRouterForm({ ...routerForm, anchor_mode: ev.target.value })
              },
              e("option", { value: "LOCAL" }, "LOCAL (recomendado)"),
              e("option", { value: "REF" }, "REF")
            )
          ),
          e(
            "div",
            { className: "form-row" },
            e("label", null, "Banda de repricing (bps)"),
            e("input", {
              type: "number",
              min: "0",
              value: routerForm.track_local_bps,
              onChange: (ev) => setRouterForm({ ...routerForm, track_local_bps: ev.target.value })
            })
          ),
          e(
            "div",
            { className: "form-row" },
            e("label", null, "Cooldown de repricing (segundos)"),
            e("input", {
              type: "number",
              min: "0",
              step: "0.5",
              value: routerForm.reprice_cooldown_sec,
              onChange: (ev) => setRouterForm({ ...routerForm, reprice_cooldown_sec: ev.target.value })
            })
          ),
          e(
            "label",
            { className: "checkbox-row" },
            e("input", {
              type: "checkbox",
              checked: !!routerForm.place_both_sides_per_exchange,
              onChange: (ev) => setRouterForm({ ...routerForm, place_both_sides_per_exchange: ev.target.checked })
            }),
            "Manter compra e venda por exchange"
          ),
          e("div", { className: "form-actions" }, e("button", { type: "submit", className: "btn btn-primary" }, "Salvar Parametros"))
        )
      ),

    !loading &&
      e(
        "div",
        { className: "panel" },
        e("h3", null, "Nova Regra de Par"),
        e(
          "form",
          { className: "form-grid", onSubmit: savePairRule },
          e(
            "div",
            { className: "form-row" },
            e("label", null, "Par"),
            e("input", {
              list: "pair-options-list",
              value: pairForm.pair,
              placeholder: "Ex.: BTC/USDT",
              onChange: (ev) => setPairForm({ ...pairForm, pair: normalizePair(ev.target.value) }),
              required: true
            }),
            e(
              "datalist",
              { id: "pair-options-list" },
              pairOptions.map((pair) => e("option", { key: pair, value: pair }, pair))
            )
          ),
          e(
            "div",
            { className: "form-row" },
            e("label", null, "% Compra (BUY_PCT)"),
            e("input", {
              type: "number",
              min: "0",
              step: "0.0001",
              value: pairForm.buy_pct,
              onChange: (ev) => setPairForm({ ...pairForm, buy_pct: ev.target.value }),
              required: true
            })
          ),
          e(
            "div",
            { className: "form-row" },
            e("label", null, "% Venda (SELL_PCT)"),
            e("input", {
              type: "number",
              min: "0",
              step: "0.0001",
              value: pairForm.sell_pct,
              onChange: (ev) => setPairForm({ ...pairForm, sell_pct: ev.target.value }),
              required: true
            })
          ),
          e("div", { className: "form-actions" }, e("button", { type: "submit", className: "btn btn-primary" }, "Salvar Regra"))
        )
      ),

    !loading &&
      e(
        "div",
        { className: "panel" },
        e("h3", null, `Regras Salvas (${pairRows.length})`),
        !pairRows.length
          ? e("p", { className: "text-muted" }, "Nenhuma regra por par cadastrada.")
          : e(
              "div",
              { className: "table-wrapper" },
              e(
                "table",
                { className: "table" },
                e("thead", null, e("tr", null, e("th", null, "Par"), e("th", null, "% Compra"), e("th", null, "% Venda"), e("th", null, "Acoes"))),
                e(
                  "tbody",
                  null,
                  pairRows.map((row) =>
                    e(
                      "tr",
                      { key: row.pair },
                      e("td", null, row.pair),
                      e("td", null, row.buy_pct === "" ? "-" : row.buy_pct),
                      e("td", null, row.sell_pct === "" ? "-" : row.sell_pct),
                      e("td", null, e("button", { className: "btn btn-danger", onClick: () => removePairRule(row.pair) }, "Remover"))
                    )
                  )
                )
              )
            )
      )
  );
}
