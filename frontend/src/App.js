const React = window.React;
const { useState } = React;
const e = React.createElement;

import { ControlCenter } from "./components/ControlCenter.js";
import { ExchangesSettings } from "./components/ExchangesSettings.js";
import { ExchangesStatus } from "./components/ExchangesStatus.js";
import { AssetsPairsSettings } from "./components/AssetsPairsSettings.js";
import { PairAutomationSettings } from "./components/PairAutomationSettings.js";
import { QuickStartFlow } from "./components/QuickStartFlow.js";

export default function App() {
  const [activeTab, setActiveTab] = useState("quick");

  return e(
    "div",
    { className: "app-root" },
    e(
      "header",
      { className: "app-header" },
      e(
        "div",
        { className: "app-header-inner" },
        e("div", null, e("h1", null, "ARBIT Terminal"), e("span", null, "Interface simplificada para operacao do cliente")),
        e(
          "div",
          { className: "tabs" },
          e("button", { className: "tab-button" + (activeTab === "quick" ? " tab-button-active" : ""), onClick: () => setActiveTab("quick") }, "Fluxo Rapido"),
          e("button", { className: "tab-button" + (activeTab === "strategy" ? " tab-button-active" : ""), onClick: () => setActiveTab("strategy") }, "Estrategia por Par"),
          e("button", { className: "tab-button" + (activeTab === "assets" ? " tab-button-active" : ""), onClick: () => setActiveTab("assets") }, "Moedas e Pares"),
          e("button", { className: "tab-button" + (activeTab === "exchanges" ? " tab-button-active" : ""), onClick: () => setActiveTab("exchanges") }, "Exchanges"),
          e("button", { className: "tab-button" + (activeTab === "operation" ? " tab-button-active" : ""), onClick: () => setActiveTab("operation") }, "Operacao")
        )
      )
    ),
    e(
      "main",
      { className: "app-main" },
      e(
        "div",
        { className: "container" },
        activeTab === "quick"
          ? e(QuickStartFlow)
          : activeTab === "strategy"
          ? e(PairAutomationSettings)
          : activeTab === "assets"
          ? e(AssetsPairsSettings)
          : activeTab === "exchanges"
          ? e("div", { className: "exchanges-stack" }, e(ExchangesSettings), e(ExchangesStatus))
          : e(ControlCenter)
      )
    )
  );
}
