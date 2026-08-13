/**
 * Skill Router — Dashboard Plugin
 *
 * Zeigt den Zustand des skill-router Plugins: getrackte
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

  const API = "/api/plugins/skill-router";

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

    const W = 1100, H = 760, cx = W / 2, cy = H / 2;
    const n = cands.length;
    const kR = 195;   // Kandidaten-Ring
    const iconR = 85; // Status-Icon-Ring

    const items = cands.map(function (c, i) {
      const a = (i / n) * 2 * Math.PI - Math.PI / 2;
      const kx = cx + kR * Math.cos(a), ky = cy + kR * Math.sin(a);
      const label = truncate(c.tool, 22) + " (" + c.count + ")";
      const kw = Math.max(72, label.length * 6.4 + 18);
      return {
        cand: c, i: i, a: a, label: label,
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
        h("text", { x: it.kx, y: it.ky + 4, textAnchor: "middle", className: "sr-mtext-alt" }, it.label)
      ));

      // Pro/Contra entlang der Radialrichtung: nach aussen vom Kandidaten,
      // leicht seitlich versetzt (Pro +Winkel, Contra -Winkel), gestaffelt.
      // So bleibt jeder Knoten in seinem 60°-Sektor — keine Überlappungen.
      let pi = 0, ci = 0;
      it.cand.pro.forEach(function (p) {
        const ra = it.a + 0.24;
        const rr = kR + 34 + pi * 36;
        const px = cx + rr * Math.cos(ra), py = cy + rr * Math.sin(ra);
        const txt = truncate(p.word, 12) + " " + p.count + "× · " + p.lift;
        const w = txt.length * 5.6 + 14;
        nodes.push(h("path", { key: "lp" + it.i + pi, d: curve(it.kx, it.ky, px, py, 6), className: "sr-mline-sub" }));
        nodes.push(h("g", { key: "p" + it.i + pi },
          h("rect", { x: px - w / 2, y: py - 11, width: w, height: 22, rx: 6, className: "sr-mnode-sub sr-mnode-pro" }),
          h("text", { x: px, y: py + 3.5, textAnchor: "middle", className: "sr-mtext-sub sr-mtext-pro" }, txt)
        ));
        pi++;
      });
      it.cand.contra.forEach(function (c) {
        const ra = it.a - 0.24;
        const rr = kR + 34 + ci * 36;
        const px = cx + rr * Math.cos(ra), py = cy + rr * Math.sin(ra);
        const txt = truncate(c.word, 12) + " " + c.count + "×";
        const w = txt.length * 5.6 + 14;
        nodes.push(h("path", { key: "lc" + it.i + ci, d: curve(it.kx, it.ky, px, py, 6), className: "sr-mline-sub" }));
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

  // ── Cluster-Ansicht (alle kausalen Cluster, Zeilen-Layout) ────────────────
  // Zeile pro Skill: Skill-Box links, Wort-Chips rechts. Chip-Farbe = Status
  // (kausal ✓ grün, generisch ✕ rot, beobachtet ! orange — gleiches Schema
  // wie die Mindmap-Badges), Lift als Zahl im Chip.

  function ClusterChip({ item }) {
    const meta = STATUS_META[item.status] || STATUS_META.beobachtet;
    return h("span", {
      className: "sr-chip",
      style: {
        borderColor: meta.color,
        color: meta.color,
      },
      title: item.word + " · Lift " + item.lift + " · " + meta.label,
    },
      meta.sym + " " + item.word + " (" + item.lift + ")"
    );
  }

  function ClusterView({ clusters }) {
    const list = Array.isArray(clusters) ? clusters : [];
    if (list.length === 0) {
      return h("div", { className: "sr-empty" },
        "Noch keine Skills sichtbar — sobald Skill-Routing aktiv ist, erscheinen hier alle Skills mit ihren kausal assoziierten Wörtern.");
    }
    return h("div", { className: "sr-clusters" },
      list.map(function (c) {
        const hasWords = Array.isArray(c.words) && c.words.length > 0;
        return h("div", { className: "sr-cluster-row" + (hasWords ? "" : " sr-cluster-row--empty"), key: c.tool },
          h("div", { className: "sr-cluster-skill" },
            h("span", { className: "sr-cluster-name" }, c.tool),
            h("span", { className: "sr-cluster-count" + (hasWords ? "" : " sr-cluster-count--empty") }, c.count)
          ),
          hasWords
            ? h("div", { className: "sr-cluster-words" },
                c.words.map(function (w) {
                  return h(ClusterChip, { item: w, key: w.word });
                }),
                c.more > 0 ? h("span", { className: "sr-cluster-more" }, "+" + c.more) : null
              )
            : h("div", { className: "sr-cluster-empty-hint" },
                "noch keine Lern-Daten — erscheint nach erster Nutzung")
        );
      })
    );
  }

  function LastInjection({ inj }) {
    if (!inj || !inj.exists) {
      return h("div", { className: "sr-empty" },
        "Noch keine Injektion aufgezeichnet — beim nächsten Skill-Routing erscheint hier die zuletzt verwendete Kombination.");
    }
    const when = inj.ts ? new Date(inj.ts * 1000).toLocaleTimeString() : "?";
    return h("div", { className: "sr-injection" },
      h("div", { className: "sr-injection-head" },
        h("span", { className: "sr-injection-task" },
          "Task: „" + truncate(inj.message || "—", 90) + "\""),
        h("span", { className: "sr-injection-time" }, "zuletzt " + when)
      ),
      inj.topics && inj.topics.length > 0
        ? h("div", { className: "sr-injection-topics" },
            inj.topics.map(function (t) {
              return h("span", { className: "sr-chip sr-chip--topic", key: t }, "✓ " + t);
            }))
        : null,
      inj.skills && inj.skills.length > 0
        ? h("div", { className: "sr-injection-skills" },
            inj.skills.map(function (s) {
              return h("span", { className: "sr-chip sr-chip--skill", key: s }, s);
            }))
        : null
    );
  }

  function Page() {
    const [overview, setOverview] = useState(null);
    const [decision, setDecision] = useState(null);
    const [clusters, setClusters] = useState(null);
    const [lastInj, setLastInj] = useState(null);
    const [err, setErr] = useState(null);

    // Dynamisch: alle 5s neu laden, damit neue Injektionen und Cluster
    // ohne Reload erscheinen.
    function loadAll() {
      fetchJSON(API + "/overview")
        .then(setOverview)
        .catch(function (e) { setErr(String((e && e.message) || e)); });
      fetchJSON(API + "/decision")
        .then(setDecision)
        .catch(function (e) { setErr(String((e && e.message) || e)); });
      fetchJSON(API + "/clusters")
        .then(function (d) { setClusters(d && d.clusters); })
        .catch(function (e) { setErr(String((e && e.message) || e)); });
      fetchJSON(API + "/last-injection")
        .then(setLastInj)
        .catch(function (e) { setErr(String((e && e.message) || e)); });
    }

    useEffect(function () {
      loadAll();
      const iv = setInterval(loadAll, 5000);
      return function () { clearInterval(iv); };
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
          h(LastInjection, { inj: lastInj }),
          h(Mindmap, { decision: decision })
        )
      ),
      h(Card, null,
        h(CardContent, null,
          h("h3", { className: "sr-section-title" },
            "Cluster-Ansicht: alle Skills mit kausalen Wörtern (live, scrollbar" +
            (clusters && clusters.length ? " — " + clusters.length + " Skills" : "") + ")"),
          h(ClusterView, { clusters: clusters })
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
    window.__HERMES_PLUGINS__.register("skill-router", Page);
  }
})();
