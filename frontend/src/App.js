const React = window.React;
const { useState, useEffect } = React;
const e = React.createElement;

import { Dashboard } from "./components/Dashboard.js";
import { BotConfigPanel } from "./components/BotConfigPanel.js";

const REFRESH_MS = 2000;

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
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
        e("div", null, e("h1", null, "ARBIT Terminal"), e("span", null, "Operação via DB (Sprint 2)")),
        e(
          "div",
          { className: "tabs" },
          e("button", { className: "tab-button" + (activeTab === "dashboard" ? " tab-button-active" : ""), onClick: () => setActiveTab("dashboard") }, "Dashboard"),
          e("button", { className: "tab-button" + (activeTab === "bot-config" ? " tab-button-active" : ""), onClick: () => setActiveTab("bot-config") }, "Config do Bot (DB)")
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
          : e(BotConfigPanel)
      )
    )
  );
}
