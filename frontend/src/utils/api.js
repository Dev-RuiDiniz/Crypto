const getBaseUrl = () => {
  if (window.env && window.env.API_BASE_URL) {
    return window.env.API_BASE_URL;
  }
  return "http://127.0.0.1:8000";
};

const getAuthContext = () => {
  const env = window.env || {};
  const tenantId = env.TENANT_ID || window.localStorage.getItem("tenantId") || "default";
  const userId = env.USER_ID || window.localStorage.getItem("userId") || "local-user";
  const roles = env.USER_ROLES || window.localStorage.getItem("roles") || "ADMIN";
  return { tenantId, userId, roles };
};

const BASE_URL = getBaseUrl();

function correlationId() {
  const rand = Math.random().toString(36).slice(2, 10);
  return `ui-${Date.now()}-${rand}`;
}

async function request(path, options = {}) {
  const { tenantId, userId, roles } = getAuthContext();
  const headers = {
    "Content-Type": "application/json",
    "X-User-Id": userId,
    "X-Tenant-Id": tenantId,
    "X-Roles": roles,
    "X-Correlation-Id": correlationId(),
    ...(options.headers || {})
  };

  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers
  });

  const text = await res.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (_err) {
      data = {};
    }
  }

  if (!res.ok) {
    const err = new Error((data && data.message) || `HTTP ${res.status}`);
    err.status = res.status;
    err.correlationId = (data && data.correlationId) || res.headers.get("X-Correlation-Id") || null;
    err.code = (data && data.error) || "HTTP_ERROR";
    throw err;
  }

  return data;
}

export const api = {
  ping: () => request("/api/ping"),
  getBalances: () => request("/api/balances"),
  getOrders: (state) => request(`/api/orders?state=${encodeURIComponent(state)}`),
  getMids: (pair) => request(`/api/mids?pair=${encodeURIComponent(pair)}`),
  getBotConfig: () => request("/api/bot-config"),
  upsertBotConfig: (data) => request("/api/bot-config", { method: "POST", body: JSON.stringify(data) }),
  getBotGlobalConfig: () => request("/api/bot-global-config"),
  updateBotGlobalConfig: (data) => request("/api/bot-global-config", { method: "POST", body: JSON.stringify(data) }),
  getConfigStatus: () => request("/api/config-status"),
  getArbitrageConfig: (pair) => request(`/api/arbitrage-config?pair=${encodeURIComponent(pair)}`),
  upsertArbitrageConfig: (data) => request("/api/arbitrage-config", { method: "POST", body: JSON.stringify(data) }),
  getArbitrageStatus: (pair) => request(`/api/arbitrage-status?pair=${encodeURIComponent(pair)}`),
  getConfigLegacy: () => request("/api/config"),

  getExchangeCredentials: (tenantId) => request(`/api/tenants/${encodeURIComponent(tenantId)}/exchange-credentials`),
  createExchangeCredential: (tenantId, payload) => request(`/api/tenants/${encodeURIComponent(tenantId)}/exchange-credentials`, { method: "POST", body: JSON.stringify(payload) }),
  updateExchangeCredential: (tenantId, id, payload) => request(`/api/tenants/${encodeURIComponent(tenantId)}/exchange-credentials/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  revokeExchangeCredential: (tenantId, id) => request(`/api/tenants/${encodeURIComponent(tenantId)}/exchange-credentials/${encodeURIComponent(id)}`, { method: "DELETE" }),
  testExchangeCredential: (tenantId, id) => request(`/api/tenants/${encodeURIComponent(tenantId)}/exchange-credentials/${encodeURIComponent(id)}/test`, { method: "POST" }),

  getAuthContext
};
