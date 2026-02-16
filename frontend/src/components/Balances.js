// frontend/src/components/Balances.js

const React = window.React || {};
const e = React.createElement ? React.createElement.bind(React) : () => null;

function formatNumber(value, decimals = 6) {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : parseFloat(value);
  if (Number.isNaN(n)) return String(value);
  // fixa e remove zeros e ponto se não precisar
  return n.toFixed(decimals).replace(/\.?0+$/, "");
}

export function Balances({ data }) {
  const hasData = data && Object.keys(data).length > 0;

  if (!hasData) {
    return e(
      "div",
      { className: "card card--full" },
      e("h2", null, "Saldos por corretora"),
      e("p", { className: "empty-state" }, "Nenhum saldo disponível no momento.")
    );
  }

  const exchanges = Object.keys(data || {}).sort();

  return e(
    "div",
    { className: "card card--full" },
    e("h2", null, "Saldos por corretora"),
    e(
      "div",
      { className: "cards-grid" },
      ...exchanges.map((ex) => {
        const assets = data[ex] || {};
        const assetNames = Object.keys(assets);

        return e(
          "div",
          { key: ex, className: "card card--nested" },
          e(
            "div",
            { className: "card-header-inline" },
            e("span", { className: "card-title-sm" }, ex),
            e(
              "span",
              { className: "card-subtitle" },
              `${assetNames.length} ativo${assetNames.length === 1 ? "" : "s"}`
            )
          ),
          e(
            "div",
            { className: "table-wrapper" },
            e(
              "table",
              { className: "balances-table" },
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
                assetNames.map((asset) =>
                  e(
                    "tr",
                    { key: asset },
                    e("td", null, asset),
                    e("td", null, formatNumber(assets[asset].free, 6)),
                    e("td", null, formatNumber(assets[asset].total, 6))
                  )
                )
              )
            )
          )
        );
      })
    )
  );
}
