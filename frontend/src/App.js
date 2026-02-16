// frontend/src/App.js

// Usa React global (carregado em index.html via <script src="https://unpkg.com/react@18/...">)
const React = window.React;
const { useState, useEffect } = React;
const e = React.createElement;

import { Dashboard } from "./components/Dashboard.js";
import { Config } from "./components/Config.js";

const API_BASE = "http://127.0.0.1:8000/api";
const REFRESH_MS = 2000; // 2s

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [config, setConfig] = useState(null);
  const [loadingCfg, setLoadingCfg] = useState(false);
  const [savingCfg, setSavingCfg] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);

  async function fetchJson(url, opts) {
    const res = await fetch(url, opts);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} ao acessar ${url}`);
    }
    return await res.json();
  }

  // Atualiza apenas o horário exibido no topo (não faz chamada na API)
  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setLastUpdate(
        now.toLocaleTimeString("pt-BR", {
          hour12: false
        })
      );
    };
    tick();
    const id = setInterval(tick, REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  // Carrega config para a aba de Configurações
  useEffect(() => {
    let cancelado = false;

    async function loadCfg() {
      setLoadingCfg(true);
      try {
        const data = await fetchJson(`${API_BASE}/config`);
        if (!cancelado) {
          setConfig(data);
        }
      } catch (err) {
        console.error("[App] Falha ao carregar config:", err);
      } finally {
        if (!cancelado) setLoadingCfg(false);
      }
    }

    loadCfg();
    return () => {
      cancelado = true;
    };
  }, []);

  const handleSaveConfig = async (newCfg) => {
    setSavingCfg(true);
    try {
      const res = await fetch(`${API_BASE}/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newCfg)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await res.json();
      setConfig(newCfg);
    } catch (err) {
      console.error("[App] Erro ao salvar config:", err);
      alert("Erro ao salvar configuração. Veja o console para detalhes.");
    } finally {
      setSavingCfg(false);
    }
  };

  return e(
    "div",
    { className: "app-root" },

    // HEADER
    e(
      "header",
      { className: "app-header" },
      e(
        "div",
        { className: "app-header-inner" },

        // Left: título e subtítulo
        e(
          "div",
          null,
          e("h1", null, "ARBIT Terminal"),
          e(
            "span",
            null,
            "Visão consolidada de saldos, ordens e mids em tempo real"
          )
        ),

        // Right: tabs
        e(
          "div",
          { className: "tabs" },
          e(
            "button",
            {
              className:
                "tab-button" +
                (activeTab === "dashboard" ? " tab-button-active" : ""),
              onClick: () => setActiveTab("dashboard")
            },
            "Dashboard"
          ),
          e(
            "button",
            {
              className:
                "tab-button" +
                (activeTab === "config" ? " tab-button-active" : ""),
              onClick: () => setActiveTab("config")
            },
            "Configurações"
          )
        )
      )
    ),

    // MAIN
    e(
      "main",
      { className: "app-main" },
      e(
        "div",
        { className: "container" },

        activeTab === "dashboard"
          ? e(
              React.Fragment,
              null,

              // linha de status
              e(
                "div",
                { className: "dashboard-status" },
                e("span", { className: "status-indicator" }),
                `Atualização automática: ${REFRESH_MS / 1000}s`,
                lastUpdate ? ` | Última atualização: ${lastUpdate}` : ""
              ),

              // Dashboard em si
              e(Dashboard, { refreshMs: REFRESH_MS })
            )
          : e(
              "div",
              { className: "panel" },
              e(
                "div",
                { className: "panel-header" },
                e("h2", null, "Configurações do ARBIT")
              ),
              savingCfg &&
                e(
                  "p",
                  { className: "panel-subtitle" },
                  "Salvando configuração..."
                ),
              loadingCfg && !config
                ? e("p", { className: "panel-subtitle" }, "Carregando configuração...")
                : e(Config, { config, onSave: handleSaveConfig })
            )
      )
    )
  );
}
