// frontend/src/components/Config.js

// Usa React global carregado em index.html
const React = window.React;
const { useState, useEffect } = React;
const e = React.createElement;

// Componente de label com bolinha de ajuda (tooltip via title)
const HelpLabel = ({ label, help }) =>
  e(
    "label",
    { className: "label-with-help" },
    e("span", { className: "label-text" }, label),
    help &&
      e(
        "span",
        {
          className: "help-icon",
          title: help
        },
        "?"
      )
  );

export function Config({ config, onSave }) {
  const [localCfg, setLocalCfg] = useState(null);
  const [saving, setSaving] = useState(false);

  // Normaliza config recebida do backend
  useEffect(() => {
    if (config) {
      const global = Object.assign(
        {
          mode: config.mode,
          usdt_brl_rate: config.usdt_brl_rate,
          ref_price: config.ref_price,
          loop_interval_ms: config.loop_interval_ms,
          print_every_sec: config.print_every_sec,
          panel_enabled: true,
          panel_redraw_on_change: true,
          panel_force_redraw_sec: 45,
          panel_header_show_usdt_brl: false,
          panel_show_mids: true,
          panel_show_balances: true,
          api_snapshot_path: "./data/api_snapshot.json",
          sqlite_path: "./data/state.db",
          csv_enable: true
        },
        config.global || {}
      );

      const boot = Object.assign(
        {
          cancel_open_orders_on_start: false,
          cancel_only_configured_pairs: true,
          cancel_dry_run: false,
          cancel_verify_retries: 2,
          cancel_verify_sleep_ms: 800,
          cancel_list_details: false,
          cancel_list_max: 60,
          http_timeout_sec: 15,
          max_retries: 3,
          retry_backoff_ms: 400
        },
        config.boot || {}
      );

      const router = Object.assign(
        {
          anchor_mode: "LOCAL",
          sticky_per_side: true,
          min_notional_usdt: 1,
          track_local_bps: 15,
          reprice_cooldown_sec: 5,
          place_both_sides_per_exchange: true,
          auto_post_fill_opposite: true,
          post_fill_use_filled_qty: true,
          alert_cooldown_sec: 120,
          balance_ttl_sec: 8,
          one_cycle_and_exit: false
        },
        config.router || {}
      );

      const risk = Object.assign(
        {
          max_open_orders_per_pair_per_exchange: 2,
          max_gross_exposure_usdt: 500,
          kill_switch_drawdown_pct: 25,
          cancel_all_on_killswitch: true
        },
        config.risk || {}
      );

      const pairs = Object.assign(
        {
          list: (config.pairs && config.pairs.list) || ""
        },
        config.pairs || {}
      );

      const logCfg = Object.assign(
        {
          level: "INFO",
          file: "./logs/arbit.log",
          rotate_mb: 10,
          verbose_skips: false,
          console_events: true,
          events_max: 20,
          event_dedup_sec: 90
        },
        config.log || {}
      );

      setLocalCfg({
        // campos planos (compatíveis com backend)
        mode: global.mode,
        usdt_brl_rate: global.usdt_brl_rate,
        ref_price: global.ref_price,
        loop_interval_ms: global.loop_interval_ms,
        print_every_sec: global.print_every_sec,
        stake: config.stake || {},
        spread: config.spread || {},
        // grupos
        global,
        boot,
        router,
        risk,
        pairs,
        log: logCfg
      });
    }
  }, [config]);

  if (!localCfg) {
    return e("div", { className: "panel" }, "Carregando configuração...");
  }

  // altera campo plano
  const handleChange = (field, value) => {
    setLocalCfg((prev) => Object.assign({}, prev, { [field]: value }));
  };

  // altera campo em GLOBAL (sincroniza com planos equivalentes)
  const handleGlobalChange = (field, value) => {
    setLocalCfg((prev) => {
      const next = Object.assign({}, prev, {
        global: Object.assign({}, prev.global || {})
      });
      next.global[field] = value;

      // manter compat com campos planos
      if (field === "mode") next.mode = value;
      if (field === "usdt_brl_rate") next.usdt_brl_rate = value;
      if (field === "ref_price") next.ref_price = value;
      if (field === "loop_interval_ms") next.loop_interval_ms = value;
      if (field === "print_every_sec") next.print_every_sec = value;

      return next;
    });
  };

  // altera campo em um grupo (boot/router/risk/pairs/log)
  const handleGroupChange = (group, field, value) => {
    setLocalCfg((prev) => {
      const g = Object.assign({}, prev[group] || {});
      g[field] = value;
      return Object.assign({}, prev, { [group]: g });
    });
  };

  const handleSubmit = async (ev) => {
    ev.preventDefault();
    setSaving(true);
    try {
      await onSave(localCfg);
    } finally {
      setSaving(false);
    }
  };

  const stakeText = Object.entries(localCfg.stake || {})
    .map(([k, v]) => k + "=" + v)
    .join("\n");

  const spreadText = Object.entries(localCfg.spread || {})
    .map(([k, v]) => k + "=" + v)
    .join("\n");

  const g = localCfg.global || {};
  const b = localCfg.boot || {};
  const r = localCfg.router || {};
  const rk = localCfg.risk || {};
  const p = localCfg.pairs || {};
  const lg = localCfg.log || {};

  return e(
    "div",
    { className: "panel" },
    e("h2", null, "Configurações do Bot"),
    e(
      "form",
      { className: "config-form", onSubmit: handleSubmit },

      // ===== GLOBAL BÁSICO =====
      e("h3", null, "Global"),
      // MODE
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Modo de operação (MODE)",
          help:
            "REAL: envia ordens para as corretoras com saldo real. PAPER: modo simulado, sem enviar ordens reais (se implementado no core)."
        }),
        e(
          "select",
          {
            value: g.mode,
            onChange: (ev) => handleGlobalChange("mode", ev.target.value)
          },
          e("option", { value: "REAL" }, "REAL"),
          e("option", { value: "PAPER" }, "PAPER")
        )
      ),
      // USDT_BRL_RATE
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Cotação USDT/BRL (USDT_BRL_RATE)",
          help:
            "Taxa usada para converter valores em BRL para USDT e vice-versa. Não precisa ser tick a tick, mas influencia cálculo de mínimos e relatórios."
        }),
        e("input", {
          type: "number",
          step: "0.01",
          value: g.usdt_brl_rate,
          onChange: (ev) =>
            handleGlobalChange(
              "usdt_brl_rate",
              parseFloat(ev.target.value || "0")
            )
        })
      ),
      // REF_PRICE
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Modo de preço de referência (REF_PRICE)",
          help:
            "Define como o preço de referência é calculado a partir dos mids das corretoras. MEDIAN = mediana simples. VWAP = preço médio ponderado por volume (quando existir no core)."
        }),
        e(
          "select",
          {
            value: g.ref_price,
            onChange: (ev) => handleGlobalChange("ref_price", ev.target.value)
          },
          e("option", { value: "MEDIAN" }, "MEDIAN"),
          e("option", { value: "VWAP" }, "VWAP")
        )
      ),
      // LOOP_INTERVAL_MS
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Intervalo do loop (LOOP_INTERVAL_MS)",
          help:
            "Tempo em milissegundos entre cada ciclo do monitor: coleta mids, calcula referências, reposiciona ordens e atualiza snapshot."
        }),
        e("input", {
          type: "number",
          value: g.loop_interval_ms,
          onChange: (ev) =>
            handleGlobalChange(
              "loop_interval_ms",
              parseInt(ev.target.value || "0", 10)
            )
        })
      ),
      // PRINT_EVERY_SEC
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Intervalo do painel (PRINT_EVERY_SEC)",
          help:
            "Intervalo mínimo, em segundos, para redesenhar o painel de texto no terminal. Ajuda a evitar flood de prints."
        }),
        e("input", {
          type: "number",
          value: g.print_every_sec,
          onChange: (ev) =>
            handleGlobalChange(
              "print_every_sec",
              parseInt(ev.target.value || "0", 10)
            )
        })
      ),

      // ===== PAINEL / SNAPSHOT =====
      e("h3", null, "Painel / Snapshot"),
      // PANEL_ENABLED
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Exibir painel no terminal",
          help:
            "Liga ou desliga o painel de status em modo texto no terminal. Se desativado, o bot continua rodando, mas sem o painel ao vivo."
        }),
        e("input", {
          type: "checkbox",
          checked: !!g.panel_enabled,
          onChange: (ev) =>
            handleGlobalChange("panel_enabled", ev.target.checked)
        })
      ),
      // PANEL_REDRAW_ON_CHANGE
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Redesenhar apenas quando mudar",
          help:
            "Se ativado, o painel só é redesenhado quando o estado relevante muda (ordens, eventos, saldos), reduzindo pisca-pisca e consumo de CPU."
        }),
        e("input", {
          type: "checkbox",
          checked: !!g.panel_redraw_on_change,
          onChange: (ev) =>
            handleGlobalChange("panel_redraw_on_change", ev.target.checked)
        })
      ),
      // PANEL_FORCE_REDRAW_SEC
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Forçar redesenho a cada X s",
          help:
            "Tempo máximo, em segundos, para forçar um redesenho do painel mesmo que nada relevante tenha mudado."
        }),
        e("input", {
          type: "number",
          value: g.panel_force_redraw_sec,
          onChange: (ev) =>
            handleGlobalChange(
              "panel_force_redraw_sec",
              parseInt(ev.target.value || "0", 10)
            )
        })
      ),
      // PANEL_HEADER_SHOW_USDT_BRL
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Mostrar USDT/BRL no cabeçalho",
          help:
            "Quando ativo, o painel mostra a cotação USDT/BRL no cabeçalho, usando o valor configurado em USDT_BRL_RATE."
        }),
        e("input", {
          type: "checkbox",
          checked: !!g.panel_header_show_usdt_brl,
          onChange: (ev) =>
            handleGlobalChange(
              "panel_header_show_usdt_brl",
              ev.target.checked
            )
        })
      ),
      // PANEL_SHOW_MIDS
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Mostrar mids das corretoras",
          help:
            "Se ativado, o painel exibe, para cada par, os mids (preço médio bid/ask) de cada corretora ativa."
        }),
        e("input", {
          type: "checkbox",
          checked: !!g.panel_show_mids,
          onChange: (ev) =>
            handleGlobalChange("panel_show_mids", ev.target.checked)
        })
      ),
      // PANEL_SHOW_BALANCES
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Mostrar saldos iniciais",
          help:
            "Se ativado, o painel mostra um snapshot dos saldos lidos no boot por corretora/ativo (não atualiza em tempo real)."
        }),
        e("input", {
          type: "checkbox",
          checked: !!g.panel_show_balances,
          onChange: (ev) =>
            handleGlobalChange("panel_show_balances", ev.target.checked)
        })
      ),
      // API_SNAPSHOT_PATH
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Caminho do snapshot JSON (API_SNAPSHOT_PATH)",
          help:
            "Arquivo JSON gerado pelo bot com o estado atual (saldos, ordens, mids). O front lê esse arquivo para exibir os dados. Caminho relativo ao diretório do projeto."
        }),
        e("input", {
          type: "text",
          value: g.api_snapshot_path || "",
          onChange: (ev) =>
            handleGlobalChange("api_snapshot_path", ev.target.value)
        })
      ),
      // SQLITE_PATH
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Caminho do banco de estado (SQLITE_PATH)",
          help:
            "Local do arquivo SQLite usado para persistir o estado interno do bot (se habilitado no core)."
        }),
        e("input", {
          type: "text",
          value: g.sqlite_path || "",
          onChange: (ev) =>
            handleGlobalChange("sqlite_path", ev.target.value)
        })
      ),
      // CSV_ENABLE
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Gerar arquivos CSV",
          help:
            "Quando ativado, o bot grava alguns dados em arquivos CSV (por exemplo, fills) para análise posterior."
        }),
        e("input", {
          type: "checkbox",
          checked: !!g.csv_enable,
          onChange: (ev) =>
            handleGlobalChange("csv_enable", ev.target.checked)
        })
      ),

      // ===== BOOT / REDE =====
      e("h3", null, "Boot / Rede"),
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Cancelar ordens ao iniciar",
          help:
            "Se ligado, ao iniciar o bot ele tenta cancelar todas as ordens abertas nas corretoras (ou apenas dos pares configurados). Ajuda a começar sempre “limpo”."
        }),
        e("input", {
          type: "checkbox",
          checked: !!b.cancel_open_orders_on_start,
          onChange: (ev) =>
            handleGroupChange(
              "boot",
              "cancel_open_orders_on_start",
              ev.target.checked
            )
        })
      ),
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Cancelar apenas pares configurados",
          help:
            "Quando ativo, o cancelamento de boot só afeta ordens dos pares listados em [PAIRS].LIST. Se desligado, tenta cancelar qualquer ordem aberta."
        }),
        e("input", {
          type: "checkbox",
          checked: !!b.cancel_only_configured_pairs,
          onChange: (ev) =>
            handleGroupChange(
              "boot",
              "cancel_only_configured_pairs",
              ev.target.checked
            )
        })
      ),
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Dry-run no cancelamento",
          help:
            "Se habilitado, o bot apenas lista as ordens que cancelaria no boot, sem realmente enviar as requisições de cancelamento."
        }),
        e("input", {
          type: "checkbox",
          checked: !!b.cancel_dry_run,
          onChange: (ev) =>
            handleGroupChange("boot", "cancel_dry_run", ev.target.checked)
        })
      ),
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Timeout HTTP (HTTP_TIMEOUT_SEC)",
          help:
            "Tempo máximo, em segundos, para aguardar resposta das APIs das corretoras antes de considerar timeout."
        }),
        e("input", {
          type: "number",
          value: b.http_timeout_sec,
          onChange: (ev) =>
            handleGroupChange(
              "boot",
              "http_timeout_sec",
              parseInt(ev.target.value || "0", 10)
            )
        })
      ),
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Máx. tentativas HTTP (MAX_RETRIES)",
          help:
            "Número máximo de tentativas extras em chamadas HTTP que falham por erro temporário ou timeout."
        }),
        e("input", {
          type: "number",
          value: b.max_retries,
          onChange: (ev) =>
            handleGroupChange(
              "boot",
              "max_retries",
              parseInt(ev.target.value || "0", 10)
            )
        })
      ),
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Espera entre tentativas (RETRY_BACKOFF_MS)",
          help:
            "Tempo em milissegundos de espera entre cada retry de chamadas HTTP, para evitar spam na API da corretora."
        }),
        e("input", {
          type: "number",
          value: b.retry_backoff_ms,
          onChange: (ev) =>
            handleGroupChange(
              "boot",
              "retry_backoff_ms",
              parseInt(ev.target.value || "0", 10)
            )
        })
      ),

      // ===== ROUTER =====
      e("h3", null, "Roteamento / Execução"),
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Modo de ancoragem (ANCHOR_MODE)",
          help:
            "LOCAL: cada corretora ancora o preço nas próprias books (bid/ask) somado ao spread configurado. REF: usa alvos calculados a partir do preço de referência global."
        }),
        e(
          "select",
          {
            value: r.anchor_mode,
            onChange: (ev) =>
              handleGroupChange("router", "anchor_mode", ev.target.value)
          },
          e("option", { value: "LOCAL" }, "LOCAL"),
          e("option", { value: "REF" }, "REF")
        )
      ),
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Mínimo por ordem em USDT (MIN_NOTIONAL_USDT)",
          help:
            "Valor mínimo da ordem em USDT que o roteador tenta respeitar ao abrir ordens. Ajuda a não ficar tentando ordens muito pequenas que a corretora rejeita."
        }),
        e("input", {
          type: "number",
          step: "0.01",
          value: r.min_notional_usdt,
          onChange: (ev) =>
            handleGroupChange(
              "router",
              "min_notional_usdt",
              parseFloat(ev.target.value || "0")
            )
        })
      ),
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Colocar BUY e SELL em todas exchanges",
          help:
            "Quando ativo, o roteador tenta manter ordens de compra e venda (ambos os lados) em cada corretora habilitada, respeitando os limites de risco."
        }),
        e("input", {
          type: "checkbox",
          checked: !!r.place_both_sides_per_exchange,
          onChange: (ev) =>
            handleGroupChange(
              "router",
              "place_both_sides_per_exchange",
              ev.target.checked
            )
        })
      ),
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Postar ordem oposta após fill",
          help:
            "Se ligado, quando uma ordem é executada (fill), o bot automaticamente tenta abrir a ordem oposta para fechar o spread do par/corretora."
        }),
        e("input", {
          type: "checkbox",
          checked: !!r.auto_post_fill_opposite,
          onChange: (ev) =>
            handleGroupChange(
              "router",
              "auto_post_fill_opposite",
              ev.target.checked
            )
        })
      ),
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Apenas um ciclo e sair",
          help:
            "Quando ativado, o bot tenta completar um ciclo de compra e venda (buy + sell) e, ao finalizar, encerra automaticamente a execução."
        }),
        e("input", {
          type: "checkbox",
          checked: !!r.one_cycle_and_exit,
          onChange: (ev) =>
            handleGroupChange(
              "router",
              "one_cycle_and_exit",
              ev.target.checked
            )
        })
      ),

      // ===== RISK =====
      e("h3", null, "Risco"),
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Máx. ordens por par/exchange",
          help:
            "Número máximo de ordens abertas simultâneas por par em cada corretora. Ajuda a evitar excesso de ordens fragmentadas."
        }),
        e("input", {
          type: "number",
          value: rk.max_open_orders_per_pair_per_exchange,
          onChange: (ev) =>
            handleGroupChange(
              "risk",
              "max_open_orders_per_pair_per_exchange",
              parseInt(ev.target.value || "0", 10)
            )
        })
      ),
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Exposição bruta máxima (USDT)",
          help:
            "Limite de exposição total do bot, em USDT, somando ordens de todas corretoras e pares. Acima disso, o roteador deixa de abrir novas ordens."
        }),
        e("input", {
          type: "number",
          step: "0.01",
          value: rk.max_gross_exposure_usdt,
          onChange: (ev) =>
            handleGroupChange(
              "risk",
              "max_gross_exposure_usdt",
              parseFloat(ev.target.value || "0")
            )
        })
      ),
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Kill-switch (drawdown %) (KILL_SWITCH_DRAWDOWN_PCT)",
          help:
            "Percentual de perda (drawdown) a partir do qual o kill-switch pode ser disparado pelo core. Ex.: 25 significa -25% de queda."
        }),
        e("input", {
          type: "number",
          step: "0.1",
          value: rk.kill_switch_drawdown_pct,
          onChange: (ev) =>
            handleGroupChange(
              "risk",
              "kill_switch_drawdown_pct",
              parseFloat(ev.target.value || "0")
            )
        })
      ),
      e(
        "div",
        { className: "form-row inline" },
        e(HelpLabel, {
          label: "Cancelar tudo ao acionar kill-switch",
          help:
            "Se ativado, ao acionar o kill-switch o bot tenta cancelar todas as ordens abertas e interrompe a operação."
        }),
        e("input", {
          type: "checkbox",
          checked: !!rk.cancel_all_on_killswitch,
          onChange: (ev) =>
            handleGroupChange(
              "risk",
              "cancel_all_on_killswitch",
              ev.target.checked
            )
        })
      ),

      // ===== PAIRS =====
      e("h3", null, "Pares"),
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Lista de pares (PAIRS.LIST)",
          help:
            "Lista de pares globais que o bot vai operar, separados por vírgula. Exemplo: BTC/USDT,ETH/USDT,SOL/USDT."
        }),
        e("input", {
          type: "text",
          value: p.list || "",
          onChange: (ev) =>
            handleGroupChange("pairs", "list", ev.target.value)
        })
      ),

      // ===== LOG (básico) =====
      e("h3", null, "Log"),
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Nível de log (LEVEL)",
          help:
            "Nível de detalhamento do log gravado em arquivo. DEBUG é o mais verboso, ERROR mostra apenas erros."
        }),
        e(
          "select",
          {
            value: lg.level,
            onChange: (ev) =>
              handleGroupChange("log", "level", ev.target.value)
          },
          e("option", { value: "DEBUG" }, "DEBUG"),
          e("option", { value: "INFO" }, "INFO"),
          e("option", { value: "WARNING" }, "WARNING"),
          e("option", { value: "ERROR" }, "ERROR")
        )
      ),

      // ===== STAKE / SPREAD =====
      e("h3", null, "Stake / Spread (brutos do INI)"),
      // STAKE (bruto)
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Seção [STAKE]",
          help:
            "Conteúdo bruto da seção [STAKE] do config.ini. Cada linha é uma chave=valor (ex.: BTC/USDT_VALUE=5.00). O backend escreve exatamente como estiver aqui."
        }),
        e("textarea", {
          rows: 3,
          value: stakeText,
          onChange: (ev) => {
            const lines = ev.target.value.split("\n");
            const newStake = {};
            lines.forEach((line) => {
              const parts = line.split("=");
              if (parts.length === 2) {
                const k = parts[0].trim();
                const v = parts[1].trim();
                if (k && v) newStake[k] = v;
              }
            });
            handleChange("stake", newStake);
          }
        })
      ),
      // SPREAD (bruto)
      e(
        "div",
        { className: "form-row" },
        e(HelpLabel, {
          label: "Seção [SPREAD]",
          help:
            "Conteúdo bruto da seção [SPREAD] do config.ini. Define os spreads por par ou globais. Ex.: BTC/USDT_BUY_PCT=0.03."
        }),
        e("textarea", {
          rows: 3,
          value: spreadText,
          onChange: (ev) => {
            const lines = ev.target.value.split("\n");
            const newSpread = {};
            lines.forEach((line) => {
              const parts = line.split("=");
              if (parts.length === 2) {
                const k = parts[0].trim();
                const v = parts[1].trim();
                if (k && v) newSpread[k] = v;
              }
            });
            handleChange("spread", newSpread);
          }
        })
      ),

      // BOTÃO SALVAR
      e(
        "button",
        { type: "submit", disabled: saving },
        saving ? "Salvando..." : "Salvar"
      )
    )
  );
}
