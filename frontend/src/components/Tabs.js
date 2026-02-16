// frontend/src/components/Tabs.js
const React = window.React || {};
const e = React.createElement ? React.createElement.bind(React) : () => null;

/**
 * Componente de abas genérico
 * items: [{ key, label, badge? }]
 * active: string (key ativa)
 * onChange: (key) => void
 */
export function Tabs({ items, active, onChange }) {
  if (!items || !items.length) {
    return null;
  }

  return e(
    "div",
    { className: "tabs", role: "tablist" },
    ...items.map((item) => {
      const isActive = item.key === active;
      return e(
        "button",
        {
          key: item.key,
          type: "button",
          className:
            "tab-button" + (isActive ? " tab-button-active" : ""),
          onClick: () => typeof onChange === "function" && onChange(item.key),
          role: "tab",
          "aria-selected": isActive,
        },
        e("span", { className: "tab-label" }, item.label),
        item.badge != null &&
          e(
            "span",
            { className: "tab-badge" },
            String(item.badge)
          )
      );
    })
  );
}
