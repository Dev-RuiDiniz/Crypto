const React = window.React;
const { useEffect, useMemo, useState } = React;
const e = React.createElement;

import { api } from "../utils/api.js";

const EXCHANGES = ["gateio", "mexc", "novadax", "mercadobitcoin", "gate", "binance", "bybit", "okx", "kucoin"];

function toast(message, isError = false) {
  window.alert(isError ? `Erro: ${message}` : message);
}

function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("pt-BR", { hour12: false });
}

export function AssetsPairsSettings() {
  const auth = useMemo(() => api.getAuthContext(), []);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [assets, setAssets] = useState([]);
  const [pairs, setPairs] = useState([]);

  const [assetForm, setAssetForm] = useState({ asset: "", kind: "BOTH", enabled: true, notes: "" });
  const [pairForm, setPairForm] = useState({ pair: "", exchange: "gateio", buy_symbol: "", sell_symbol: "", enabled: true });

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.getAssetsPairs(auth.tenantId);
      setAssets(data.assets || []);
      setPairs(data.pairs || []);
      setError(null);
    } catch (err) {
      setError(err.message || "Falha ao carregar moedas e pares");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const saveAsset = async (ev) => {
    ev.preventDefault();
    try {
      await api.upsertAsset(auth.tenantId, assetForm);
      toast("Moeda salva");
      setAssetForm({ asset: "", kind: "BOTH", enabled: true, notes: "" });
      load();
    } catch (err) {
      toast(err.message || "Falha ao salvar moeda", true);
    }
  };

  const removeAsset = async (asset) => {
    if (!window.confirm(`Remover moeda ${asset}?`)) return;
    try {
      await api.deleteAsset(auth.tenantId, asset);
      load();
    } catch (err) {
      toast(err.message || "Falha ao remover moeda", true);
    }
  };

  const savePair = async (ev) => {
    ev.preventDefault();
    try {
      await api.upsertPairMapping(auth.tenantId, pairForm);
      toast("Par/mapeamento salvo e sincronizado");
      setPairForm({ pair: "", exchange: "gateio", buy_symbol: "", sell_symbol: "", enabled: true });
      load();
    } catch (err) {
      toast(err.message || "Falha ao salvar par", true);
    }
  };

  const removePair = async (pair, exchange) => {
    if (!window.confirm(`Remover mapeamento ${pair} em ${exchange}?`)) return;
    try {
      await api.deletePairMapping(auth.tenantId, pair, exchange);
      load();
    } catch (err) {
      toast(err.message || "Falha ao remover mapeamento", true);
    }
  };

  return e(
    "div",
    { className: "panel" },
    e("h2", null, "Moedas e Pares"),
    e("p", { className: "text-muted" }, "Cadastre moedas e mapeie pares por exchange para ordens pareadas (BUY/SELL)."),
    e("button", { className: "btn btn-secondary", onClick: load, disabled: loading }, loading ? "Atualizando..." : "Atualizar"),
    loading && e("div", { className: "loading" }, e("div", { className: "loading-spinner" }), "Carregando..."),
    !loading && error && e("div", { className: "alert alert-error" }, error),

    e(
      "div",
      { className: "panel" },
      e("h3", null, "Nova Moeda"),
      e(
        "form",
        { className: "form-grid", onSubmit: saveAsset },
        e("div", { className: "form-row" }, e("label", null, "Moeda"), e("input", { value: assetForm.asset, placeholder: "Ex.: BTC", onChange: (ev) => setAssetForm({ ...assetForm, asset: ev.target.value.toUpperCase() }), required: true })),
        e(
          "div",
          { className: "form-row" },
          e("label", null, "Tipo"),
          e(
            "select",
            { value: assetForm.kind, onChange: (ev) => setAssetForm({ ...assetForm, kind: ev.target.value }) },
            e("option", { value: "BOTH" }, "BOTH"),
            e("option", { value: "BASE" }, "BASE"),
            e("option", { value: "QUOTE" }, "QUOTE")
          )
        ),
        e("div", { className: "form-row" }, e("label", null, "Obs"), e("input", { value: assetForm.notes, onChange: (ev) => setAssetForm({ ...assetForm, notes: ev.target.value }) })),
        e("label", { className: "checkbox-row" }, e("input", { type: "checkbox", checked: !!assetForm.enabled, onChange: (ev) => setAssetForm({ ...assetForm, enabled: ev.target.checked }) }), "Ativa"),
        e("div", { className: "form-actions" }, e("button", { type: "submit", className: "btn btn-primary" }, "Salvar Moeda"))
      )
    ),

    e(
      "div",
      { className: "panel" },
      e("h3", null, "Novo Par / Mapeamento"),
      e(
        "form",
        { className: "form-grid", onSubmit: savePair },
        e("div", { className: "form-row" }, e("label", null, "Par Global"), e("input", { value: pairForm.pair, placeholder: "Ex.: BTC/USDT", onChange: (ev) => setPairForm({ ...pairForm, pair: ev.target.value.toUpperCase() }), required: true })),
        e(
          "div",
          { className: "form-row" },
          e("label", null, "Exchange"),
          e("select", { value: pairForm.exchange, onChange: (ev) => setPairForm({ ...pairForm, exchange: ev.target.value }) }, EXCHANGES.map((ex) => e("option", { key: ex, value: ex }, ex)))
        ),
        e("div", { className: "form-row" }, e("label", null, "BUY Symbol"), e("input", { value: pairForm.buy_symbol, placeholder: "Ex.: BTC/USDT ou BTC/BRL", onChange: (ev) => setPairForm({ ...pairForm, buy_symbol: ev.target.value.toUpperCase() }), required: true })),
        e("div", { className: "form-row" }, e("label", null, "SELL Symbol"), e("input", { value: pairForm.sell_symbol, placeholder: "Ex.: BTC/USDT ou BTC/BRL", onChange: (ev) => setPairForm({ ...pairForm, sell_symbol: ev.target.value.toUpperCase() }), required: true })),
        e("label", { className: "checkbox-row" }, e("input", { type: "checkbox", checked: !!pairForm.enabled, onChange: (ev) => setPairForm({ ...pairForm, enabled: ev.target.checked }) }), "Ativo"),
        e("div", { className: "form-actions" }, e("button", { type: "submit", className: "btn btn-primary" }, "Salvar Par"))
      )
    ),

    e(
      "div",
      { className: "panel" },
      e("h3", null, `Moedas (${assets.length})`),
      !assets.length
        ? e("p", { className: "text-muted" }, "Nenhuma moeda cadastrada.")
        : e(
            "div",
            { className: "table-wrapper" },
            e(
              "table",
              { className: "table" },
              e("thead", null, e("tr", null, e("th", null, "Moeda"), e("th", null, "Tipo"), e("th", null, "Status"), e("th", null, "Atualizado"), e("th", null, "Acoes"))),
              e(
                "tbody",
                null,
                assets.map((row) =>
                  e(
                    "tr",
                    { key: row.asset },
                    e("td", null, row.asset || "-"),
                    e("td", null, row.kind || "-"),
                    e("td", null, row.enabled ? "ATIVA" : "INATIVA"),
                    e("td", null, fmtDate(row.updated_at)),
                    e("td", null, e("button", { className: "btn btn-danger", onClick: () => removeAsset(row.asset) }, "Remover"))
                  )
                )
              )
            )
          )
    ),

    e(
      "div",
      { className: "panel" },
      e("h3", null, `Mapeamentos de Pares (${pairs.length})`),
      !pairs.length
        ? e("p", { className: "text-muted" }, "Nenhum mapeamento cadastrado.")
        : e(
            "div",
            { className: "table-wrapper" },
            e(
              "table",
              { className: "table" },
              e("thead", null, e("tr", null, e("th", null, "Par"), e("th", null, "Exchange"), e("th", null, "BUY"), e("th", null, "SELL"), e("th", null, "Status"), e("th", null, "Atualizado"), e("th", null, "Acoes"))),
              e(
                "tbody",
                null,
                pairs.map((row) =>
                  e(
                    "tr",
                    { key: `${row.pair}-${row.exchange}` },
                    e("td", null, row.pair || "-"),
                    e("td", null, row.exchange || "-"),
                    e("td", null, row.buy_symbol || "-"),
                    e("td", null, row.sell_symbol || "-"),
                    e("td", null, row.enabled ? "ATIVO" : "INATIVO"),
                    e("td", null, fmtDate(row.updated_at)),
                    e("td", null, e("button", { className: "btn btn-danger", onClick: () => removePair(row.pair, row.exchange) }, "Remover"))
                  )
                )
              )
            )
          )
    )
  );
}
