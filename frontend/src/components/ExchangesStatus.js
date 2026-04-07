const React = window.React;
const { useEffect, useMemo, useState } = React;
const e = React.createElement;

import { api } from "../utils/api.js";

function StatusBadge({ status }) {
  const s = String(status || "").toUpperCase();
  const tone = s === "ACTIVE" ? "success" : s === "REVOKED" ? "danger" : s === "INACTIVE" ? "warning" : "warning";
  return e("span", { className: `status-badge status-${tone}` }, s || "UNKNOWN");
}

function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("pt-BR", { hour12: false });
}

function fmtTest(ok, latency) {
  if (ok === null || typeof ok === "undefined") return "-";
  return ok ? `OK${typeof latency === "number" ? ` (${latency}ms)` : ""}` : "FALHOU";
}

export function ExchangesStatus() {
  const auth = useMemo(() => api.getAuthContext(), []);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.getExchangesStatus(auth.tenantId);
      setItems((data && data.items) || []);
      setError(null);
    } catch (err) {
      setError(err.message || "Falha ao carregar status das exchanges");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return e(
    "div",
    { className: "panel" },
    e("h2", null, "Status das Exchanges Salvas"),
    e("p", { className: "text-muted" }, `Tenant: ${auth.tenantId || "default"}`),
    e("button", { className: "btn btn-secondary", onClick: load, disabled: loading }, loading ? "Atualizando..." : "Atualizar"),
    loading && e("div", { className: "loading" }, e("div", { className: "loading-spinner" }), "Carregando status..."),
    !loading && error && e("div", { className: "alert alert-error" }, error),
    !loading && !error && items.length === 0 && e("div", { className: "empty-state" }, "Nenhuma exchange salva."),
    !loading && !error && items.length > 0 &&
      e(
        "div",
        { className: "table-wrapper" },
        e(
          "table",
          { className: "table" },
          e("thead", null, e("tr", null,
            e("th", null, "Exchange"),
            e("th", null, "Label"),
            e("th", null, "Status"),
            e("th", null, "Versao"),
            e("th", null, "Ultimo teste"),
            e("th", null, "Atualizado")
          )),
          e("tbody", null,
            items.map((row) =>
              e("tr", { key: `${row.exchange}-${row.credentialId || "none"}` },
                e("td", null, row.exchange || "-"),
                e("td", null, row.label || "-"),
                e("td", null, e(StatusBadge, { status: row.status })),
                e("td", null, row.credentialVersion || "-"),
                e("td", null, fmtTest(row.lastTestOk, row.lastTestLatencyMs)),
                e("td", null, fmtDate(row.updatedAt))
              )
            )
          )
        )
      )
  );
}
