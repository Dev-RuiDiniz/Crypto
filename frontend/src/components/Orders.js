// frontend/src/components/Orders.js

const React = window.React || {};
const e = React.createElement ? React.createElement.bind(React) : () => null;

import { Tabs } from "./Tabs.js";

function formatNumber(value, decimals = 4) {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : parseFloat(value);
  if (Number.isNaN(n)) return String(value);
  return n.toFixed(decimals).replace(/\.?0+$/, "");
}

export function Orders({ pending, open, closed, activeTab, onTabChange }) {
  const tabs = [
    { key: "pending", label: "Pendentes" },
    { key: "open", label: "Abertas" },
    { key: "closed", label: "Fechadas" }
  ];

  let currentList = [];
  if (activeTab === "pending") currentList = pending || [];
  if (activeTab === "open") currentList = open || [];
  if (activeTab === "closed") currentList = closed || [];

  return e(
    "div",
    { className: "card card--full" },
    // HEADER
    e(
      "div",
      { className: "card-header-inline" },
      e("h2", null, "Ordens"),
      e(Tabs, { items: tabs, active: activeTab, onChange: onTabChange })
    ),

    // CORPO
    currentList.length === 0
      ? e(
          "p",
          { className: "empty-state" },
          activeTab === "pending"
            ? "Nenhuma ordem pendente no momento."
            : activeTab === "open"
            ? "Nenhuma ordem aberta no momento."
            : "Nenhuma ordem fechada registrada ainda."
        )
      : e(
          "div",
          { className: "table-wrapper" },
          e(
            "table",
            { className: "orders-table" },
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
                e("th", null, "ClientOrderId"),
                e("th", null, "Dedupe"),
                e("th", null, "Criada em")
              )
            ),
            e(
              "tbody",
              null,
              currentList.map((o) => {
                const rowKey =
                  o.id || `${o.exchange || "ex"}-${o.pair || o.symbol_local}-${o.created_at}`;
                const side = (o.side || "").toUpperCase();
                const status = (o.status || "").toLowerCase();

                let rowClass = "order-row";
                if (side === "BUY") rowClass += " order-row-buy";
                if (side === "SELL") rowClass += " order-row-sell";
                if (status === "filled" || status === "closed")
                  rowClass += " order-row-closed";

                return e(
                  "tr",
                  { key: rowKey, className: rowClass },
                  e("td", null, o.id || "—"),
                  e("td", null, o.exchange || "—"),
                  e("td", null, o.pair || o.symbol_local || "—"),
                  e("td", null, side || "—"),
                  e("td", null, formatNumber(o.price, 2)), // preço 2 casas
                  e("td", null, formatNumber(o.amount, 4)), // qty 4 casas
                  e("td", null, o.status || "—"),
                  e("td", null, o.client_order_id_short || o.client_order_id || "—"),
                  e("td", null, o.dedupe_state ? e("span", { className: `dedupe-badge dedupe-${String(o.dedupe_state || "").toLowerCase()}` }, o.dedupe_state) : "—"),
                  e("td", null, o.created_at || "—")
                );
              })
            )
          )
        )
  );
}
