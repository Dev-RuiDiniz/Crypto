const React = window.React;
const { useEffect, useMemo, useState } = React;
const e = React.createElement;

import { api } from "../utils/api.js";

function tone(enabled, mapped) {
  if (enabled && mapped) return "status-success";
  if (mapped) return "status-warning";
  return "status-danger";
}

function badge(text, klass) {
  return e("span", { className: `status-badge ${klass || ""}`.trim() }, text);
}

export function MarketCatalog(props) {
  const onAddPair = props.onAddPair || (() => {});
  const disabled = !!props.disabled;
  const tenantId = (props.tenantId || "default").trim() || "default";

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [exchangeFilter, setExchangeFilter] = useState("all");
  const [query, setQuery] = useState("");

  const loadCatalog = async () => {
    setLoading(true);
    try {
      const data = await api.getPairsCatalog(tenantId);
      setCatalog(data || {});
      setError(null);
    } catch (err) {
      setError(err.message || "Falha ao carregar catalogo");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCatalog();
  }, [tenantId]);

  const exchanges = (catalog && catalog.exchanges) || [];
  const pairs = (catalog && catalog.pairs) || [];
  const assets = (catalog && catalog.assets) || {};
  const counts = (catalog && catalog.counts) || {};

  const filteredPairs = useMemo(() => {
    const q = String(query || "").trim().toUpperCase();
    return pairs.filter((item) => {
      const byExchange =
        exchangeFilter === "all" ||
        (item.exchanges || []).some((ex) => String(ex.exchange || "").toLowerCase() === exchangeFilter);
      if (!byExchange) return false;
      if (!q) return true;

      const inPair = String(item.pair || "").toUpperCase().includes(q);
      const inBase = String(item.base || "").toUpperCase().includes(q);
      const inQuote = String(item.quote || "").toUpperCase().includes(q);
      const inSource = (item.sources || []).some((src) => String(src || "").toUpperCase().includes(q));
      const inSymbols = (item.exchanges || []).some((ex) => {
        return (
          String(ex.buy_symbol || "").toUpperCase().includes(q) ||
          String(ex.sell_symbol || "").toUpperCase().includes(q) ||
          String(ex.local_base || "").toUpperCase().includes(q) ||
          String(ex.local_quote || "").toUpperCase().includes(q) ||
          String(ex.exchange || "").toUpperCase().includes(q)
        );
      });
      return inPair || inBase || inQuote || inSource || inSymbols;
    });
  }, [pairs, exchangeFilter, query]);

  return e(
    "div",
    { className: "panel" },
    e("h2", null, "Catalogo de Mercados (Pares e Moedas)"),
    e(
      "p",
      { className: "text-muted" },
      `Pares: ${counts.pairs || 0} | Exchanges: ${counts.exchanges || 0} | Moedas base: ${counts.assets_global_base || 0} | Moedas quote: ${counts.assets_global_quote || 0}`
    ),
    e(
      "div",
      { className: "catalog-toolbar" },
      e(
        "div",
        { className: "form-row" },
        e("label", null, "Exchange"),
        e(
          "select",
          { value: exchangeFilter, onChange: (ev) => setExchangeFilter(ev.target.value), disabled: disabled || loading },
          e("option", { value: "all" }, "Todas"),
          exchanges.map((item) => e("option", { key: item.exchange, value: item.exchange }, item.exchange))
        )
      ),
      e(
        "div",
        { className: "form-row" },
        e("label", null, "Buscar par/moeda"),
        e("input", {
          type: "text",
          placeholder: "Ex.: BTC, USDT, BRL, mexc",
          value: query,
          onChange: (ev) => setQuery(ev.target.value),
          disabled: disabled || loading
        })
      ),
      e("button", { className: "btn btn-secondary", onClick: loadCatalog, disabled: disabled || loading }, loading ? "Atualizando..." : "Atualizar catalogo")
    ),

    error && e("div", { className: "alert alert-error" }, error),

    !error &&
      e(
        "div",
        { className: "catalog-assets-grid" },
        e(
          "div",
          { className: "card" },
          e("h3", null, "Moedas base"),
          e(
            "div",
            { className: "catalog-chip-list" },
            ((assets.global_base || []).slice(0, 60)).map((asset) => e("span", { key: `base-${asset}`, className: "catalog-chip" }, asset))
          )
        ),
        e(
          "div",
          { className: "card" },
          e("h3", null, "Moedas quote"),
          e(
            "div",
            { className: "catalog-chip-list" },
            ((assets.global_quote || []).slice(0, 60)).map((asset) => e("span", { key: `quote-${asset}`, className: "catalog-chip" }, asset))
          )
        )
      ),

    e(
      "div",
      { className: "table-wrapper" },
      e(
        "table",
        { className: "table table--wide" },
        e(
          "thead",
          null,
          e(
            "tr",
            null,
            e("th", null, "Par global"),
            e("th", null, "Base"),
            e("th", null, "Quote"),
            e("th", null, "Exchanges"),
            e("th", null, "Simbolos locais"),
            e("th", null, "Fontes"),
            e("th", null, "Acao")
          )
        ),
        e(
          "tbody",
          null,
          filteredPairs.map((item) =>
            e(
              "tr",
              { key: item.pair },
              e("td", null, item.pair || "-"),
              e("td", null, item.base || "-"),
              e("td", null, item.quote || "-"),
              e(
                "td",
                null,
                (item.exchanges || []).map((ex) =>
                  e(
                    "div",
                    { key: `${item.pair}-${ex.exchange}` },
                    badge(
                      `${ex.exchange}${ex.enabled ? "" : " (off)"}`,
                      tone(!!ex.enabled, !!ex.mapped)
                    )
                  )
                )
              ),
              e(
                "td",
                null,
                (item.exchanges || []).map((ex) =>
                  e(
                    "div",
                    { className: "catalog-local-line", key: `${item.pair}-${ex.exchange}-symbols` },
                    `${ex.exchange}: ${ex.buy_symbol || "-"} / ${ex.sell_symbol || "-"}`
                  )
                )
              ),
              e(
                "td",
                null,
                (item.sources || []).map((src) => e("div", { key: `${item.pair}-${src}` }, badge(src, "status-warning")))
              ),
              e(
                "td",
                null,
                e("button", { className: "btn btn-primary", disabled: disabled || loading, onClick: () => onAddPair(item.pair) }, "Adicionar no bot")
              )
            )
          ),
          !filteredPairs.length &&
            e(
              "tr",
              { key: "empty" },
              e("td", { colSpan: 7 }, "Nenhum par encontrado para os filtros atuais.")
            )
        )
      )
    )
  );
}
