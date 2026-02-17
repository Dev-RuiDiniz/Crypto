const React = window.React;
const { useState, useEffect } = React;
const e = React.createElement;

import { Dashboard } from "./components/Dashboard.js";
import { BotConfigPanel } from "./components/BotConfigPanel.js";
import { ExchangesSettings } from "./components/ExchangesSettings.js";
import { NotificationsSettings } from "./components/NotificationsSettings.js";
import { GoLiveChecklist } from "./components/GoLiveChecklist.js";

const REFRESH_MS = 2000;

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [settingsTab, setSettingsTab] = useState("exchanges");
  const [lastUpdate, setLastUpdate] = useState(null);

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setLastUpdate(now.toLocaleTimeString("pt-BR", { hour12: false }));
    };
    tick();
    const id = setInterval(tick, REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  return e(
    "div",
    { className: "app-root" },
    e(
      "header",
      { className: "app-header" },
      e(
        "div",
        { className: "app-header-inner" },
        e("div", null, e("h1", null, "ARBIT Terminal"), e("span", null, "Operação via DB (Sprint 3)")),
        e(
          "div",
          { className: "tabs" },
          e("button", { className: "tab-button" + (activeTab === "dashboard" ? " tab-button-active" : ""), onClick: () => setActiveTab("dashboard") }, "Dashboard"),
          e("button", { className: "tab-button" + (activeTab === "bot-config" ? " tab-button-active" : ""), onClick: () => setActiveTab("bot-config") }, "Config do Bot (DB)"),
          e("button", { className: "tab-button" + (activeTab === "settings" ? " tab-button-active" : ""), onClick: () => setActiveTab("settings") }, "Configurações"),
          e("button", { className: "tab-button" + (activeTab === "go-live" ? " tab-button-active" : ""), onClick: () => setActiveTab("go-live") }, "Go Live")
        )
      )
    ),
    e(
      "main",
      { className: "app-main" },
      e(
        "div",
        { className: "container" },
        activeTab === "dashboard"
          ? e(React.Fragment, null,
              e("div", { className: "dashboard-status" },
                e("span", { className: "status-indicator" }),
                `Atualização automática: ${REFRESH_MS / 1000}s`,
                lastUpdate ? ` | Última atualização: ${lastUpdate}` : ""
              ),
              e(Dashboard, { refreshMs: REFRESH_MS })
            )
          : activeTab === "bot-config"
            ? e(BotConfigPanel)
            : activeTab === "go-live"
              ? e(GoLiveChecklist)
              : e(React.Fragment, null,
                e("div", { className: "panel" },
                  e("h2", null, "Configurações"),
                  e("div", { className: "tabs" },
                    e("button", { className: "tab-button" + (settingsTab === "exchanges" ? " tab-button-active" : ""), onClick: () => setSettingsTab("exchanges") }, "Exchanges"),
                    e("button", { className: "tab-button" + (settingsTab === "notifications" ? " tab-button-active" : ""), onClick: () => setSettingsTab("notifications") }, "Notificações")
                  )
                ),
                settingsTab === "exchanges" && e(ExchangesSettings),
                settingsTab === "notifications" && e(NotificationsSettings)
              )
      )
    )
  );
}
