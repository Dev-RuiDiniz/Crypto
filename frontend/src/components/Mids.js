// frontend/src/components/Mids.js
const React = window.React || {};
const e = React.createElement ? React.createElement.bind(React) : () => null;

function formatNumber(value, decimals = 3) {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : parseFloat(value);
  if (Number.isNaN(n)) return String(value);
  return n.toFixed(decimals).replace(/\.?0+$/, "");
}

export function Mids({ data, pair, onPairChange }) {
  // Aceita tanto { mids: {...} } quanto { gate: 123, mexc: 124, ... }
  const midsObj =
    (data && (data.mids || data)) && typeof (data.mids || data) === "object"
      ? (data.mids || data)
      : {};

  const exchanges = Object.keys(midsObj || {});

  const hasData = exchanges.length > 0;

  return e(
    "div",
    { className: "card card--full" },
    e(
      "div",
      { className: "card-header-inline" },
      e("h2", { className: "card-title" }, "Mids por corretora"),
      e(
        "div",
        { className: "card-controls" },
        e(
          "label",
          { className: "field-label" },
          "Par:",
          e("input", {
            type: "text",
            value: pair || "",
            onChange: (ev) =>
              typeof onPairChange === "function" &&
              onPairChange(ev.target.value.toUpperCase()),
            className: "input input--sm",
            placeholder: "Ex: SOL-USDT"
          })
        )
      )
    ),
    !hasData
      ? e(
          "p",
          { className: "empty-state" },
          "Nenhum midprice disponível para este par ainda."
        )
      : e(
          "div",
          { className: "mids-row" },
          exchanges.map((ex) =>
            e(
              "div",
              { key: ex, className: "mids-item" },
              e("div", { className: "mids-label" }, ex),
              e(
                "div",
                { className: "mids-value" },
                formatNumber(midsObj[ex], 3)
              )
            )
          )
        )
  );
}
