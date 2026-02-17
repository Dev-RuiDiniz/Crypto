const React = window.React;
const { useEffect, useState } = React;
const e = React.createElement;

import { api } from "../utils/api.js";

const EVENTS = [
  ["ORDER_EXECUTED", "Ordem executada"],
  ["ARBITRAGE_EXECUTED", "Arbitragem executada"],
  ["AUTH_FAILED", "Falha autenticação"],
  ["WS_DEGRADED", "WS degradado"],
  ["KILL_SWITCH_ACTIVATED", "Kill switch"],
];

export function NotificationsSettings() {
  const { tenantId } = api.getAuthContext();
  const [form, setForm] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showWebhook, setShowWebhook] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.getNotificationSettings(tenantId);
      setForm(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (loading || !form) return e("div", { className: "panel" }, "Carregando notificações...");

  const toggleEvent = (eventKey) => {
    const current = new Set(form.enabledEvents || []);
    if (current.has(eventKey)) current.delete(eventKey);
    else current.add(eventKey);
    setForm({ ...form, enabledEvents: Array.from(current) });
  };

  const save = async () => {
    setSaving(true);
    try {
      const saved = await api.updateNotificationSettings(tenantId, {
        emailEnabled: !!form.emailEnabled,
        emailRecipients: (form.emailRecipients || []).filter(Boolean),
        webhookEnabled: !!form.webhookEnabled,
        webhookUrl: form.webhookUrl || "",
        minSeverity: form.minSeverity || "INFO",
        enabledEvents: form.enabledEvents || [],
      });
      setForm(saved);
      alert("Configurações salvas");
    } finally {
      setSaving(false);
    }
  };

  return e(
    "div",
    { className: "panel" },
    e("h2", null, "Notificações"),
    e("div", { className: "form-row inline" },
      e("label", null, "Habilitar Email"),
      e("input", { type: "checkbox", checked: !!form.emailEnabled, onChange: (ev) => setForm({ ...form, emailEnabled: ev.target.checked }) })
    ),
    e("div", { className: "form-row" },
      e("label", null, "Emails (separados por vírgula)"),
      e("input", {
        type: "text",
        value: (form.emailRecipients || []).join(", "),
        onChange: (ev) => setForm({ ...form, emailRecipients: ev.target.value.split(",").map((x) => x.trim()).filter(Boolean) })
      })
    ),
    e("div", { className: "form-row inline" },
      e("label", null, "Habilitar WhatsApp/Webhook"),
      e("input", { type: "checkbox", checked: !!form.webhookEnabled, onChange: (ev) => setForm({ ...form, webhookEnabled: ev.target.checked }) })
    ),
    e("div", { className: "form-row" },
      e("label", null, "Webhook URL"),
      e("input", {
        type: showWebhook ? "text" : "password",
        value: form.webhookUrl || "",
        onChange: (ev) => setForm({ ...form, webhookUrl: ev.target.value })
      }),
      e("button", { type: "button", className: "btn-secondary", onClick: () => setShowWebhook(!showWebhook) }, showWebhook ? "Ocultar" : "Mostrar")
    ),
    e("div", { className: "form-row" },
      e("label", null, "Nível mínimo"),
      e("select", { value: form.minSeverity || "INFO", onChange: (ev) => setForm({ ...form, minSeverity: ev.target.value }) },
        e("option", { value: "INFO" }, "INFO"),
        e("option", { value: "IMPORTANT" }, "IMPORTANT"),
        e("option", { value: "ERROR" }, "ERROR")
      )
    ),
    e("h3", null, "Eventos"),
    ...EVENTS.map(([key, label]) => e("div", { className: "form-row inline", key },
      e("label", null, label),
      e("input", { type: "checkbox", checked: (form.enabledEvents || []).includes(key), onChange: () => toggleEvent(key) })
    )),
    e("div", { className: "actions" },
      e("button", { type: "button", className: "btn", onClick: save, disabled: saving }, saving ? "Salvando..." : "Salvar"),
      e("button", { type: "button", className: "btn-secondary", onClick: () => api.testNotification(tenantId, "email") }, "Testar Email"),
      e("button", { type: "button", className: "btn-secondary", onClick: () => api.testNotification(tenantId, "webhook") }, "Testar WhatsApp")
    )
  );
}
