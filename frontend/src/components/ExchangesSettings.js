const React = window.React;
const { useEffect, useMemo, useState } = React;
const e = React.createElement;

import { api } from "../utils/api.js";
import { buildRotatePayload, canManageCredentials } from "../utils/exchangeCredentials.mjs";

const ALLOWED_EXCHANGES = ["mexc", "binance", "bybit", "okx", "kucoin", "mercadobitcoin"];

function toast(message, isError = false) {
  window.alert(isError ? `Erro: ${message}` : message);
}

function safeError(err, fallback) {
  const correlation = err && err.correlationId ? ` (correlationId: ${err.correlationId})` : "";
  if (err && err.status === 403) return `Sem permissão${correlation}`;
  return `${fallback}${correlation}`;
}

function StatusBadge({ status }) {
  const tone = status === "ACTIVE" ? "success" : status === "REVOKED" ? "danger" : "warning";
  return e("span", { className: `status-badge status-${tone}` }, status || "—");
}

function SecretInput({ label, value, onChange, inputId }) {
  const [visible, setVisible] = useState(false);
  return e(
    "div",
    { className: "form-row" },
    e("label", { htmlFor: inputId }, label),
    e(
      "div",
      { className: "secret-input-row" },
      e("input", {
        id: inputId,
        type: visible ? "text" : "password",
        value,
        autoComplete: "off",
        onChange,
        "aria-label": label
      }),
      e("button", { type: "button", className: "btn btn-secondary", onClick: () => setVisible((v) => !v) }, visible ? "Ocultar" : "Mostrar")
    )
  );
}

function Modal({ title, children, onClose }) {
  return e(
    "div",
    { className: "modal-backdrop", role: "dialog", "aria-modal": "true" },
    e(
      "div",
      { className: "modal-panel" },
      e("div", { className: "modal-header" }, e("h3", null, title), e("button", { className: "btn btn-secondary", onClick: onClose }, "Fechar")),
      children
    )
  );
}

export function ExchangesSettings() {
  const auth = useMemo(() => api.getAuthContext(), []);
  const isAdmin = useMemo(() => canManageCredentials(auth.roles), [auth.roles]);

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [rotateTarget, setRotateTarget] = useState(null);
  const [pendingTestId, setPendingTestId] = useState(null);

  const [createForm, setCreateForm] = useState({ exchange: "mexc", label: "", apiKey: "", apiSecret: "", passphrase: "", confirmTradeOnly: false });
  const [rotateForm, setRotateForm] = useState({ label: "", status: "ACTIVE", apiKey: "", apiSecret: "", passphrase: "" });

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.getExchangeCredentials(auth.tenantId);
      setRows((data.items || []).map((x) => ({ ...x, testOkUntil: 0 })));
      setError(null);
    } catch (err) {
      setError(safeError(err, "Falha ao carregar credenciais"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const resetCreate = () => setCreateForm({ exchange: "mexc", label: "", apiKey: "", apiSecret: "", passphrase: "", confirmTradeOnly: false });
  const resetRotate = () => setRotateForm({ label: "", status: "ACTIVE", apiKey: "", apiSecret: "", passphrase: "" });

  const onCreate = async (ev) => {
    ev.preventDefault();
    try {
      await api.createExchangeCredential(auth.tenantId, {
        exchange: createForm.exchange,
        label: createForm.label,
        apiKey: createForm.apiKey,
        apiSecret: createForm.apiSecret,
        ...(createForm.passphrase.trim() ? { passphrase: createForm.passphrase.trim() } : {})
      });
      setShowCreate(false);
      resetCreate();
      toast("Credencial criada");
      load();
    } catch (err) {
      toast(safeError(err, "Falha ao criar credencial"), true);
      setCreateForm((p) => ({ ...p, apiSecret: "" }));
    }
  };

  const onRotate = async (ev) => {
    ev.preventDefault();
    if (!rotateTarget) return;
    try {
      await api.updateExchangeCredential(auth.tenantId, rotateTarget.id, buildRotatePayload(rotateForm));
      setRotateTarget(null);
      resetRotate();
      toast("Credencial atualizada");
      load();
    } catch (err) {
      toast(safeError(err, "Falha ao rotacionar"), true);
      setRotateForm((p) => ({ ...p, apiSecret: "" }));
    }
  };

  const onTest = async (id) => {
    setPendingTestId(id);
    try {
      const res = await api.testExchangeCredential(auth.tenantId, id);
      const latency = res && typeof res.latencyMs !== "undefined" ? `${res.latencyMs}ms` : "OK";
      setRows((prev) => prev.map((r) => (r.id === id ? { ...r, testOkUntil: Date.now() + 5000 } : r)));
      toast(`Conexão OK — ${latency}`);
    } catch (err) {
      toast(safeError(err, "Falha no teste"), true);
    } finally {
      setPendingTestId(null);
    }
  };

  const onRevoke = async (id) => {
    if (!window.confirm("Isso revoga a credencial e o robô não poderá operar com ela. Deseja continuar?")) return;
    try {
      await api.revokeExchangeCredential(auth.tenantId, id);
      toast("Credencial revogada");
      load();
    } catch (err) {
      toast(safeError(err, "Falha ao revogar"), true);
    }
  };

  const fmtDate = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleString("pt-BR", { hour12: false });
  };

  return e(
    "div",
    { className: "panel" },
    e("h2", null, "Exchanges"),
    e("p", { className: "text-muted" }, "Gerencie credenciais de exchange por conta/tenant."),
    e("div", { className: "alert alert-error" }, "Use apenas permissões de TRADE. NÃO habilite WITHDRAW."),
    isAdmin && e("button", { className: "btn btn-primary", onClick: () => setShowCreate(true) }, "Adicionar credencial"),

    loading && e("div", { className: "loading" }, e("div", { className: "loading-spinner" }), "Carregando credenciais..."),
    !loading && error && e("div", { className: "alert alert-error" }, error, e("button", { className: "btn btn-secondary", onClick: load }, "Tentar novamente")),
    !loading && !error && rows.length === 0 && e("div", { className: "empty-state" }, "Nenhuma credencial cadastrada.", isAdmin && e("div", null, e("button", { className: "btn btn-primary", onClick: () => setShowCreate(true) }, "Adicionar credencial"))),

    !loading && !error && rows.length > 0 &&
      e("div", { className: "table-wrapper" },
        e("table", { className: "table" },
          e("thead", null, e("tr", null,
            e("th", null, "Exchange"),
            e("th", null, "Label"),
            e("th", null, "Last4"),
            e("th", null, "Status"),
            e("th", null, "Atualizado"),
            e("th", null, "Ações")
          )),
          e("tbody", null,
            rows.map((row) => e("tr", { key: row.id },
              e("td", null, row.exchange),
              e("td", null, row.label),
              e("td", null, row.last4),
              e("td", null, e(StatusBadge, { status: row.status }), row.testOkUntil > Date.now() && e("span", { className: "status-badge status-success" }, "TEST OK")),
              e("td", null, fmtDate(row.updatedAt)),
              e("td", { className: "actions-inline" },
                isAdmin && e("button", { className: "btn btn-secondary", onClick: () => { setRotateTarget(row); setRotateForm({ label: row.label || "", status: row.status || "ACTIVE", apiKey: "", apiSecret: "", passphrase: "" }); } }, "Rotacionar"),
                isAdmin && e("button", { className: "btn btn-secondary", onClick: () => onTest(row.id), disabled: pendingTestId === row.id }, pendingTestId === row.id ? "Testando..." : "Testar"),
                isAdmin && e("button", { className: "btn btn-danger", onClick: () => onRevoke(row.id) }, "Revogar"),
                !isAdmin && e("span", { className: "text-muted" }, "Somente leitura")
              )
            ))
          )
        )
      ),

    showCreate && e(Modal, { title: "Adicionar credencial", onClose: () => { setShowCreate(false); resetCreate(); } },
      e("form", { onSubmit: onCreate },
        e("div", { className: "form-row" }, e("label", null, "Exchange"), e("select", { value: createForm.exchange, onChange: (ev) => setCreateForm({ ...createForm, exchange: ev.target.value }) }, ALLOWED_EXCHANGES.map((ex) => e("option", { key: ex, value: ex }, ex)))),
        e("div", { className: "form-row" }, e("label", null, "Label"), e("input", { value: createForm.label, onChange: (ev) => setCreateForm({ ...createForm, label: ev.target.value }), required: true })),
        e(SecretInput, { label: "API Key", inputId: "create-api-key", value: createForm.apiKey, onChange: (ev) => setCreateForm({ ...createForm, apiKey: ev.target.value }) }),
        e(SecretInput, { label: "API Secret", inputId: "create-api-secret", value: createForm.apiSecret, onChange: (ev) => setCreateForm({ ...createForm, apiSecret: ev.target.value }) }),
        e(SecretInput, { label: "Passphrase (opcional)", inputId: "create-passphrase", value: createForm.passphrase, onChange: (ev) => setCreateForm({ ...createForm, passphrase: ev.target.value }) }),
        e("label", { className: "checkbox-row" }, e("input", { type: "checkbox", checked: createForm.confirmTradeOnly, onChange: (ev) => setCreateForm({ ...createForm, confirmTradeOnly: ev.target.checked }), required: true }), "Confirmo que NÃO habilitei permissão de withdraw"),
        e("div", { className: "form-actions" }, e("button", { type: "button", className: "btn btn-secondary", onClick: () => { setShowCreate(false); resetCreate(); } }, "Cancelar"), e("button", { type: "submit", className: "btn btn-primary" }, "Salvar"))
      )
    ),

    rotateTarget && e(Modal, { title: "Rotacionar credencial", onClose: () => { setRotateTarget(null); resetRotate(); } },
      e("form", { onSubmit: onRotate },
        e("div", { className: "form-row" }, e("label", null, "Label"), e("input", { value: rotateForm.label, onChange: (ev) => setRotateForm({ ...rotateForm, label: ev.target.value }), required: true })),
        e("div", { className: "form-row" }, e("label", null, "Status"), e("select", { value: rotateForm.status, onChange: (ev) => setRotateForm({ ...rotateForm, status: ev.target.value }) }, e("option", { value: "ACTIVE" }, "ACTIVE"), e("option", { value: "INACTIVE" }, "INACTIVE"))),
        e("p", { className: "text-muted" }, "Se preencher novos valores, a versão será incrementada e o robô pode recarregar credenciais."),
        e(SecretInput, { label: "Nova API Key (opcional)", inputId: "rotate-api-key", value: rotateForm.apiKey, onChange: (ev) => setRotateForm({ ...rotateForm, apiKey: ev.target.value }) }),
        e(SecretInput, { label: "Novo API Secret (opcional)", inputId: "rotate-api-secret", value: rotateForm.apiSecret, onChange: (ev) => setRotateForm({ ...rotateForm, apiSecret: ev.target.value }) }),
        e(SecretInput, { label: "Nova Passphrase (opcional)", inputId: "rotate-passphrase", value: rotateForm.passphrase, onChange: (ev) => setRotateForm({ ...rotateForm, passphrase: ev.target.value }) }),
        e("div", { className: "form-actions" }, e("button", { type: "button", className: "btn btn-secondary", onClick: () => { setRotateTarget(null); resetRotate(); } }, "Cancelar"), e("button", { type: "submit", className: "btn btn-primary" }, "Salvar"))
      )
    )
  );
}

