/**
 * Skill Router — Dashboard Plugin
 *
 * Zeigt den Zustand des workflow-router-autoload Plugins: getrackte
 * Tool-Starts, Lexikon-Größe, Wort-Tabelle mit Kausalitäts-Status (Lift)
 * und eine Entscheidungs-Mindmap im Stil einer klassischen Pro/Contra-
 * Mindmap: zentral "Task", radiale Skill-Kandidaten mit Status-Icons
 * (✓ kausal / ! beobachtet / ✕ generisch) und Pro/Contra-Unterknoten
 * mit den belegenden bzw. rauschigen Wörtern — die Funktionsweise des
 * Kausalitäts-Matchings auf einen Blick.
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
    kausal: { label: "kausal", sym: "✓", cls: "sr-badge sr-badge--causal", color: "#16a34a" },
    generisch: { label: "generisch", sym: "✕", cls: "sr-badge sr-badge--generic", color: "#dc2626" },
    beobachtet: { label: "beobachtet", sym: "!", cls: "sr-badge sr-badge--observed", color: "#f59e0b" },
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

  // ── Entscheidungs-Mindmap ─────────────────────────────────────────────────
  // Stil: zentraler Knoten "Task" (dunkelgrau), radiale Kandidaten (weiß,
  // schwarzer Rand), Status-Icons in Kreisen auf halber Strecke, gebogene
  // Linien, Pro/Contra-Unterknoten seitlich an den Kandidaten.

  function truncate(s, n) {
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  function curve(x1, y1, x2, y2, bend) {
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const dx = x2 - x1, dy = y2 - y1;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const bx = mx + (-dy / len) * bend;
    const by = my + (dx / len) * bend;
    return "M" + x1 + " " + y1 + " Q" + bx + " " + by + " " + x2 + " " + y2;
  }

  function Mindmap({ decision }) {
    const cands = (decision && decision.candidates) || [];
    if (cands.length === 0) {
      return h("div", { className: "sr-empty" },
        "Noch keine Kandidaten — nach etwas Tool-Nutzung erscheint hier die Entscheidungs-Mindmap (Task → Skills mit Pro/Contra).");
    }

    const W = 960, H = 640, cx = W / 2, cy = H / 2;
    const n = cands.length;
    const kR = 150;   // Kandidaten-Ring
    const pR = 205;   // Pro/Contra-Ring
    const iconR = 80; // Status-Icon-Ring

    const items = cands.map(function (c, i) {
      const a = (i / n) * 2 * Math.PI - Math.PI / 2;
      const kx = cx + kR * Math.cos(a), ky = cy + kR * Math.sin(a);
      const label = truncate(c.tool, 22) + " (" + c.count + ")";
      const kw = Math.max(72, label.length * 6.4 + 18);
      return {
        cand: c, i: i, a: a,
        kx: kx, ky: ky, kw: kw,
        ix: cx + iconR * Math.cos(a), iy: cy + iconR * Math.sin(a),
      };
    });

    const nodes = [];

    // Zentraler Contra-Knoten (globale Notiz direkt am Zentrum, wie im
    // Beispiel oben mittig) — erscheint, wenn der Lift noch inaktiv ist
    // oder generische Wörter auf ihre Bereinigung warten.
    if (decision) {
      let note = null;
      if (decision.total_calls < 25) {
        note = "Contra: Lift inaktiv (" + decision.total_calls + "/25 Calls)";
      } else if (decision.generic_words > 0) {
        note = "Contra: " + decision.generic_words + " generische Wörter (Bereinigung)";
      }
      if (note) {
        const nx = cx, ny = cy - 95;
        const w = note.length * 5.6 + 14;
        nodes.push(h("path", { key: "lnote", d: curve(cx, cy, nx, ny, 8), className: "sr-mline-sub" }));
        nodes.push(h("g", { key: "note" },
          h("rect", { x: nx - w / 2, y: ny - 11, width: w, height: 22, rx: 6, className: "sr-mnode-sub sr-mnode-contra" }),
          h("text", { x: nx, y: ny + 3.5, textAnchor: "middle", className: "sr-mtext-sub sr-mtext-contra" }, note)
        ));
      }
    }

    // Kanten + Icons + Kandidaten + Pro/Contra
    items.forEach(function (it) {
      const m = STATUS_META[it.cand.status] || STATUS_META.beobachtet;

      // gebogene Linie Zentrum -> Kandidat
      nodes.push(h("path", {
        key: "l" + it.i, d: curve(cx, cy, it.kx, it.ky, 26), className: "sr-mline",
      }));

      // Status-Icon (Kreis mit Symbol)
      nodes.push(h("g", { key: "i" + it.i },
        h("circle", { cx: it.ix, cy: it.iy, r: 14, className: "sr-micon", stroke: m.color }),
        h("text", { x: it.ix, y: it.iy + 4, textAnchor: "middle", className: "sr-micon-sym", fill: m.color }, m.sym)
      ));

      // Kandidat-Knoten (weiß, Rand)
      nodes.push(h("g", { key: "k" + it.i },
        h("rect", {
          x: it.kx - it.kw / 2, y: it.ky - 15, width: it.kw, height: 30,
          rx: 8, className: "sr-mnode-alt",
        }),
        h("text", { x: it.kx, y: it.ky + 4, textAnchor: "middle", className: "sr-mtext-alt" }, label)
      ));

      // Pro/Contra seitlich am Kandidaten
      const perp = it.a + Math.PI / 2;
      let pi = 0, ci = 0;
      it.cand.pro.forEach(function (p) {
        const px = it.kx + (pi + 1) * 44 * Math.cos(perp);
        const py = it.ky + (pi + 1) * 44 * Math.sin(perp);
        const txt = "Pro: " + truncate(p.word, 14) + " " + p.count + "× · " + p.lift;
        const w = txt.length * 5.6 + 14;
        nodes.push(h("path", { key: "lp" + it.i + pi, d: curve(it.kx, it.ky, px, py, 10), className: "sr-mline-sub" }));
        nodes.push(h("g", { key: "p" + it.i + pi },
          h("rect", { x: px - w / 2, y: py - 11, width: w, height: 22, rx: 6, className: "sr-mnode-sub sr-mnode-pro" }),
          h("text", { x: px, y: py + 3.5, textAnchor: "middle", className: "sr-mtext-sub sr-mtext-pro" }, txt)
        ));
        pi++;
      });
      it.cand.contra.forEach(function (c) {
        const px = it.kx - (ci + 1) * 44 * Math.cos(perp);
        const py = it.ky - (ci + 1) * 44 * Math.sin(perp);
        const txt = "Contra: " + truncate(c.word, 14) + " " + c.count + "×";
        const w = txt.length * 5.6 + 14;
        nodes.push(h("path", { key: "lc" + it.i + ci, d: curve(it.kx, it.ky, px, py, 10), className: "sr-mline-sub" }));
        nodes.push(h("g", { key: "c" + it.i + ci },
          h("rect", { x: px - w / 2, y: py - 11, width: w, height: 22, rx: 6, className: "sr-mnode-sub sr-mnode-contra" }),
          h("text", { x: px, y: py + 3.5, textAnchor: "middle", className: "sr-mtext-sub sr-mtext-contra" }, txt)
        ));
        ci++;
      });
    });

    // Zentrum zuletzt (liegt oben)
    nodes.push(h("g", { key: "center" },
      h("rect", { x: cx - 55, y: cy - 19, width: 110, height: 38, rx: 9, className: "sr-mnode-center" }),
      h("text", { x: cx, y: cy + 4.5, textAnchor: "middle", className: "sr-mtext-center" }, "Task")
    ));

    return h("div", { className: "sr-mindmap" },
      h("svg", { viewBox: "0 0 " + W + " " + H, className: "sr-svg" }, nodes),
      h("div", { className: "sr-legend" },
        h("span", { className: "sr-legend-item" }, h("i", { className: "sr-dot", style: { background: "#16a34a" } }), "✓ kausal (Lift ≥ 2)"),
        h("span", { className: "sr-legend-item" }, h("i", { className: "sr-dot", style: { background: "#f59e0b" } }), "! beobachtet (wenig Daten)"),
        h("span", { className: "sr-legend-item" }, h("i", { className: "sr-dot", style: { background: "#dc2626" } }), "✕ generisch (wird bereinigt)"),
        h("span", { className: "sr-legend-item" }, h("i", { className: "sr-dot", style: { background: "#22c55e" } }), "Pro: kausale Wörter"),
        h("span", { className: "sr-legend-item" }, h("i", { className: "sr-dot", style: { background: "#6b7280" } }), "Contra: Rausch-Indizien")
      )
    );
  }

  function Page() {
    const [overview, setOverview] = useState(null);
    const [decision, setDecision] = useState(null);
    const [err, setErr] = useState(null);

    useEffect(function () {
      fetchJSON(API + "/overview")
        .then(setOverview)
        .catch(function (e) { setErr(String((e && e.message) || e)); });
      fetchJSON(API + "/decision")
        .then(setDecision)
        .catch(function (e) { setErr(String((e && e.message) || e)); });
    }, []);

    if (err) {
      return h("div", { className: "sr-error" }, "API-Fehler: " + err);
    }
    if (!overview) {
      return h("div", { className: "sr-empty" }, "Lade Skill-Router-Daten…");
    }

    const liftBadge = overview.lift_active
      ? h(Badge, { className: "sr-badge sr-badge--causal" }, "Lift aktiv (≥25 Calls)")
      : h(Badge, { className: "sr-badge sr-badge--observed" },
          "Lift noch inaktiv (" + overview.total_calls + "/25 Calls)");

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
          h("h3", { className: "sr-section-title" }, "Funktionsweise: Task → Skill-Kandidaten (Pro/Contra)"),
          h(Mindmap, { decision: decision })
        )
      ),
      h(Card, null,
        h(CardContent, null,
          h("h3", { className: "sr-section-title" }, "Wort-Zustand (Kausalität via Lift)"),
          h(WordTable, { words: overview.words })
        )
      )
    );
  }

  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("workflow-router-autoload", Page);
  }
})();
