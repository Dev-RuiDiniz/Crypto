const React = window.React;
const { useEffect, useState } = React;
const e = React.createElement;

import { api } from "../utils/api.js";

export function GoLiveChecklist() {
  const { tenantId } = api.getAuthContext();
  const [items, setItems] = useState([]);
  const [workerStatus, setWorkerStatus] = useState("unknown");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await api.getGoLiveChecklist(tenantId);
        if (cancelled) return;
        setItems(res.items || []);
        setWorkerStatus(res.workerStatus || "unknown");
        setError("");
      } catch (err) {
        if (cancelled) return;
        setError(err.message || "Falha ao carregar checklist");
      }
    }
    load();
  }, [tenantId]);

  const badge = (ok, warning) => {
    if (warning) return e("span", { className: "status-badge status-warning" }, "AVISO");
    return e("span", { className: `status-badge ${ok ? "status-success" : "status-danger"}` }, ok ? "OK" : "PENDENTE");
  };

  return e("div", { className: "panel" },
    e("h2", null, "Checklist de Go-Live"),
    e("p", { className: "panel-subtitle" }, `Worker status: ${workerStatus}`),
    error && e("div", { className: "alert alert-error" }, error),
    e("div", { className: "table-wrapper" },
      e("table", { className: "table table--wide" },
        e("thead", null, e("tr", null, e("th", null, "Item"), e("th", null, "Status"), e("th", null, "Ação"), e("th", null, "Observação"))),
        e("tbody", null,
          (items || []).map((item) => e("tr", { key: item.key },
            e("td", null, item.label || item.key),
            e("td", null, badge(!!item.ok, item.warning)),
            e("td", null, e("code", null, item.link || "#/")),
            e("td", null, item.warning || "—")
          ))
        )
      )
    )
  );
}
