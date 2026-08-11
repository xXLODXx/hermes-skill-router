/**
 * Skill Router — Dashboard Plugin
 *
 * Zeigt den Zustand des workflow-router-autoload Plugins: getrackte
 * Tool-Starts, Lexikon-Größe, Wort-Tabelle mit Kausalitäts-Status (Lift)
 * und eine Mindmap des bipartiten Graphen Wort <-> Tool.
 *
 * Plain IIFE, kein Build-Step. Nutzt window.__HERMES_PLUGIN_SDK__ (React +
 * shadcn primitives) und window.__HERMES_PLUGINS__.register().
 */
(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;

  const { React } = SDK;
  const h = React.createElement;
  const { Card, CardContent, Badge } = SDK.components;
  const { useState, useEffect } = SDK.hooks;

  const API = "/api/plugins/workflow-router-autoload";

  const STATUS_META = {
    kausal: { label: "kausal", cls: "sr-badge sr-badge--causal" },
    generisch: { label: "generisch", cls: "sr-badge sr-badge--generic" },
    beobachtet: { label: "beobachtet", cls: "sr-badge sr-badge--observed" },
  };

  function fetchJSON(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) {
        return r.text().then(function (t) {
          throw new Error(r.status + ": " + t);
        });
      }
      return r.json();
    });
  }

  function StatCard({ label, value, sub }) {
    return h(Card, { className: "sr-stat" },
      h(CardContent, null,
        h("div", { className: "sr-stat-value" }, value),
        h("div", { className: "sr-stat-label" }, label),
        sub ? h("div", { className: "sr-stat-sub" }, sub) : null
      )
    );
  }

  function StatusBadge({ status }) {
    const m = STATUS_META[status] || STATUS_META.beobachtet;
    return h(Badge, { className: m.cls }, m.label);
  }

  function WordTable({ words }) {
    if (!words || words.length === 0) {
      return h("div", { className: "sr-empty" },
        "Noch keine gelernten Wörter — das Lexikon füllt sich mit echter Tool-Nutzung.");
    }
    return h("div", { className: "sr-table-wrap" },
      h("table", { className: "sr-table" },
        h("thead", null,
          h("tr", null,
            h("th", null, "Wort"),
            h("th", null, "Status"),
            h("th", null, "Lift"),
            h("th", null, "Count"),
            h("th", null, "Top-Tool"),
            h("th", null, "Tools")
          )
        ),
        h("tbody", null,
          words.map(function (r) {
            return h("tr", { key: r.wort },
              h("td", { className: "sr-word" }, r.wort),
              h("td", null, h(StatusBadge, { status: r.status })),
              h("td", null, r.lift.toFixed(2)),
              h("td", null, r.count),
              h("td", { className: "sr-tool" }, r.top_tool || "—"),
              h("td", null, r.tools)
            );
          })
        )
      )
    );
  }

  // ── Mindmap ────────────────────────────────────────────────────────────────
  // Radial-Layout: Mitte "Task", Ring 1 = Tools, Ring 2 = Wörter (um ihr
  // Top-Tool gestreut). Kanten: Wort -> Top-Tool, grün wenn kausal.

  function Mindmap({ graph }) {
    if (!graph || graph.tools.length === 0) {
      return h("div", { className: "sr-empty" },
        "Noch keine Graph-Daten — nach etwas Tool-Nutzung erscheint hier die Wort-Tool-Mindmap.");
    }
    const W = 940, H = 580, cx = W / 2, cy = H / 2;
    const toolR = 150, wordR = 275;

    const toolPos = {};
    graph.tools.forEach(function (t, i) {
      const a = (i / graph.tools.length) * 2 * Math.PI - Math.PI / 2;
      toolPos[t] = { x: cx + toolR * Math.cos(a), y: cy + toolR * Math.sin(a) };
    });

    // Top-Tool je Wort + Streu-Index pro Tool
    const perTool = {};
    const wordMeta = {};
    graph.words.forEach(function (w) {
      let best = null, bestCount = -1;
      graph.edges.forEach(function (e) {
        if (e.word === w && e.count > bestCount) { best = e.tool; bestCount = e.count; }
      });
      if (!best || !toolPos[best]) return;
      const k = perTool[best] = (perTool[best] || 0) + 1;
      const n = graph.words.length;
      const tp = toolPos[best];
      const baseA = Math.atan2(tp.y - cy, tp.x - cx);
      const spread = (k - (n + 1) / 2) * 0.09;
      const a = baseA + spread;
      wordMeta[w] = {
        x: cx + wordR * Math.cos(a),
        y: cy + wordR * Math.sin(a),
        tool: best,
        causal: graph.edges.some(function (e) {
          return e.word === w && e.tool === best && e.causal;
        }),
      };
    });

    const lines = [];
    Object.keys(wordMeta).forEach(function (w) {
      const m = wordMeta[w];
      const tp = toolPos[m.tool];
      lines.push(h("line", {
        key: "l-" + w,
        x1: m.x, y1: m.y, x2: tp.x, y2: tp.y,
        className: m.causal ? "sr-edge sr-edge--causal" : "sr-edge",
      }));
    });

    const toolNodes = graph.tools.map(function (t) {
      const p = toolPos[t];
      return h("g", { key: "t-" + t },
        h("circle", { cx: p.x, cy: p.y, r: 14, className: "sr-node-tool" }),
        h("text", { x: p.x, y: p.y + 30, textAnchor: "middle", className: "sr-label-tool" }, t)
      );
    });

    const wordNodes = Object.keys(wordMeta).map(function (w) {
      const m = wordMeta[w];
      return h("g", { key: "w-" + w },
        h("circle", {
          cx: m.x, cy: m.y, r: 6,
          className: m.causal ? "sr-node-word sr-node-word--causal" : "sr-node-word",
        }),
        h("text", {
          x: m.x + 9, y: m.y + 3,
          textAnchor: "start", className: "sr-label-word",
        }, w)
      );
    });

    return h("div", { className: "sr-mindmap" },
      h("svg", { viewBox: "0 0 " + W + " " + H, className: "sr-svg" },
        lines,
        toolNodes,
        wordNodes,
        h("circle", { cx: cx, cy: cy, r: 26, className: "sr-node-center" }),
        h("text", { x: cx, y: cy + 4, textAnchor: "middle", className: "sr-label-center" }, "Task")
      ),
      h("div", { className: "sr-legend" },
        h("span", { className: "sr-legend-item" }, h("i", { className: "sr-dot sr-dot--tool" }), "Tool"),
        h("span", { className: "sr-legend-item" }, h("i", { className: "sr-dot sr-dot--causal" }), "Wort (kausal)"),
        h("span", { className: "sr-legend-item" }, h("i", { className: "sr-dot sr-dot--word" }), "Wort (beobachtet)"),
        h("span", { className: "sr-legend-item" }, h("i", { className: "sr-dot sr-dot--edge" }), "kausale Kante")
      )
    );
  }

  function Page() {
    const [overview, setOverview] = useState(null);
    const [graph, setGraph] = useState(null);
    const [err, setErr] = useState(null);

    useEffect(function () {
      fetchJSON(API + "/overview")
        .then(setOverview)
        .catch(function (e) { setErr(String((e && e.message) || e)); });
      fetchJSON(API + "/graph")
        .then(setGraph)
        .catch(function (e) { setErr(String((e && e.message) || e)); });
    }, []);

    if (err) {
      return h("div", { className: "sr-error" }, "API-Fehler: " + err);
    }
    if (!overview) {
      return h("div", { className: "sr-empty" }, "Lade Skill-Router-Daten…");
    }

    const liftBadge = overview.lift_active
      ? h(Badge, { className: "sr-badge sr-badge--causal" }, "Lift aktiv (≥" + 25 + " Calls)")
      : h(Badge, { className: "sr-badge sr-badge--observed" },
          "Lift noch inaktiv (" + overview.total_calls + "/" + 25 + " Calls)");

    return h("div", { className: "sr-page" },
      h("div", { className: "sr-stats" },
        h(StatCard, { label: "Getrackte Tool-Starts", value: overview.total_calls }),
        h(StatCard, { label: "Lexikon-Wörter", value: overview.lexicon_size }),
        h(StatCard, { label: "Verfolgte Wörter", value: overview.words_tracked }),
        h(StatCard, { label: "Verfolgte Tools", value: overview.tools_tracked }),
        h("div", { className: "sr-lift-badge" }, liftBadge)
      ),
      h(Card, null,
        h(CardContent, null,
          h("h3", { className: "sr-section-title" }, "Wort-Zustand (Kausalität via Lift)"),
          h(WordTable, { words: overview.words })
        )
      ),
      h(Card, null,
        h(CardContent, null,
          h("h3", { className: "sr-section-title" }, "Mindmap: Wort ↔ Tool"),
          h(Mindmap, { graph: graph })
        )
      )
    );
  }

  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("workflow-router-autoload", Page);
  }
})();
