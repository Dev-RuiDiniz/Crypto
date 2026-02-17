const getBaseUrl = () => {
  if (window.env && window.env.API_BASE_URL) {
    return window.env.API_BASE_URL;
  }
  return "http://127.0.0.1:8000";
};

const BASE_URL = getBaseUrl();

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json"
    },
    ...options
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
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
  getConfigLegacy: () => request("/api/config")
};
