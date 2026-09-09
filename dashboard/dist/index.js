(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;
  const h = SDK.React.createElement;
  const { Card, CardContent, Badge } = SDK.components;
  const { useState, useEffect } = SDK.hooks;
  const API = "/api/plugins/skill-router";

  function fetchJSON(path) {
    return fetch(API + path).then(function (r) {
      if (!r.ok) throw new Error(r.status + " " + r.statusText);
      return r.json();
    });
  }

  function Stat({ label, value, detail, tone }) {
    return h("div", { className: "sr2-stat sr2-stat--" + (tone || "neutral") },
      h("div", { className: "sr2-stat-value" }, String(value)),
      h("div", { className: "sr2-stat-label" }, label),
      detail ? h("div", { className: "sr2-stat-detail" }, detail) : null
    );
  }

  function Progress({ label, value, max, suffix }) {
    const ratio = max ? Math.min(1, Math.max(0, value / max)) : 0;
    return h("div", { className: "sr2-progress" },
      h("div", { className: "sr2-progress-head" }, h("span", null, label), h("strong", null, value + (suffix || ""))),
      h("div", { className: "sr2-track" }, h("div", { className: "sr2-fill", style: { width: (ratio * 100) + "%" } }))
    );
  }

  function Evidence({ evidence }) {
    const entries = Object.keys(evidence || {}).map(function (key) { return [key, evidence[key]]; });
    if (!entries.length) return h("div", { className: "sr2-empty" }, "Noch keine Evidenzereignisse.");
    const max = Math.max.apply(null, entries.map(function (x) { return x[1]; }));
    return h("div", { className: "sr2-evidence" }, entries.map(function (entry) {
      return h(Progress, { key: entry[0], label: entry[0], value: entry[1], max: max });
    }));
  }

  function EventRow({ event }) {
    const time = event.ts ? new Date(event.ts * 1000).toLocaleTimeString() : "—";
    const state = event.fallback ? "fallback" : event.accepted_count ? "injected" : "observed";
    return h("div", { className: "sr2-event sr2-event--" + state },
      h("div", { className: "sr2-event-dot" }),
      h("div", { className: "sr2-event-main" },
        h("div", { className: "sr2-event-title" },
          state === "injected" ? "Routing-Injektion" : state === "fallback" ? "Sicherer Fallback" : "Beobachtung",
          h("span", { className: "sr2-event-time" }, time)
        ),
        event.accepted && event.accepted.length
          ? h("div", { className: "sr2-event-skills" }, event.accepted.map(function (name) { return h("span", { className: "sr2-pill", key: name }, name); }))
          : h("div", { className: "sr2-event-muted" }, event.fallback || "Keine Skills injiziert"),
        h("div", { className: "sr2-event-meta" },
          event.accepted_count + " Kandidaten · " + event.estimated_chars + " Zeichen · Confidence " + event.confidence
        )
      )
    );
  }

  function Page() {
    const [metrics, setMetrics] = useState(null);
    const [overview, setOverview] = useState(null);
    const [error, setError] = useState(null);
    function load() {
      Promise.all([fetchJSON("/runtime-metrics"), fetchJSON("/overview")])
        .then(function (values) { setMetrics(values[0]); setOverview(values[1]); setError(null); })
        .catch(function (e) { setError(String(e && e.message || e)); });
    }
    useEffect(function () { load(); const timer = setInterval(load, 5000); return function () { clearInterval(timer); }; }, []);
    if (error) return h("div", { className: "sr2-error" }, "Mission-Control-API nicht erreichbar: " + error);
    if (!metrics || !overview) return h("div", { className: "sr2-loading" }, "Mission Control wird geladen …");

    const healthy = metrics.events === 0 || metrics.avg_confidence >= 0.5;
    return h("div", { className: "sr2-page" },
      h("div", { className: "sr2-hero" },
        h("div", null,
          h("div", { className: "sr2-kicker" }, "SKILL ROUTER · MISSION CONTROL"),
          h("h1", null, "Routing-Zustand auf einen Blick"),
          h("p", null, "Live-Runtime, Evidenzqualität und Fehlersignale getrennt vom historischen Lernbestand.")
        ),
        h(Badge, { className: "sr2-health sr2-health--" + (healthy ? "ok" : "warn") }, healthy ? "● BETRIEBSBEREIT" : "● PRÜFEN")
      ),
      h("div", { className: "sr2-grid sr2-grid--stats" },
        h(Stat, { label: "Plugin-Version", value: metrics.version, detail: "aktiver V2-Vertrag", tone: "blue" }),
        h(Stat, { label: "Routing-Events", value: metrics.events, detail: "anonymisierte Auditspur" }),
        h(Stat, { label: "Injektionen", value: metrics.injections, detail: "mit Kandidaten", tone: "green" }),
        h(Stat, { label: "Fallbacks", value: metrics.fallbacks, detail: (metrics.fallback_rate * 100).toFixed(1) + "% aller Events", tone: metrics.fallbacks ? "amber" : "green" }),
        h(Stat, { label: "Ø Confidence", value: metrics.avg_confidence.toFixed(2), detail: "Entscheidungsqualität", tone: metrics.avg_confidence >= 0.7 ? "green" : "amber" }),
        h(Stat, { label: "Ø Injektion", value: metrics.avg_chars, detail: "Zeichen pro Event" })
      ),
      h("div", { className: "sr2-grid sr2-grid--main" },
        h(Card, { className: "sr2-card" }, h(CardContent, null,
          h("div", { className: "sr2-card-head" }, h("h2", null, "Routing-Funnel"), h("span", { className: "sr2-card-note" }, "seit Aktivierung")),
          h(Progress, { label: "Events", value: metrics.events, max: Math.max(metrics.events, 1) }),
          h(Progress, { label: "Akzeptierte Kandidaten", value: metrics.accepted_candidates, max: Math.max(metrics.accepted_candidates + metrics.rejected_candidates, 1) }),
          h(Progress, { label: "Verworfene Kandidaten", value: metrics.rejected_candidates, max: Math.max(metrics.accepted_candidates + metrics.rejected_candidates, 1) }),
          h(Progress, { label: "Budget-Verwerfungen", value: metrics.budget_rejections, max: Math.max(metrics.rejected_candidates, 1) })
        )),
        h(Card, { className: "sr2-card" }, h(CardContent, null,
          h("div", { className: "sr2-card-head" }, h("h2", null, "Evidenzprofil"), h("span", { className: "sr2-card-note" }, "welche Signale tragen")),
          h(Evidence, { evidence: metrics.evidence }),
          h("div", { className: "sr2-callout" }, "Subword-Signale sind unterstützend und lösen allein keine Injektion aus.")
        ))
      ),
      h(Card, { className: "sr2-card" }, h(CardContent, null,
        h("div", { className: "sr2-card-head" }, h("h2", null, "Letzte Routing-Entscheidungen"), h("span", { className: "sr2-card-note" }, "aktualisiert alle 5 Sekunden")),
        metrics.recent && metrics.recent.length ? h("div", { className: "sr2-events" }, metrics.recent.map(function (event, i) { return h(EventRow, { event: event, key: String(event.ts) + i }); })) : h("div", { className: "sr2-empty" }, "Noch keine Routing-Events. Die Ansicht füllt sich mit den nächsten Sessions." )
      )),
      h(Card, { className: "sr2-card sr2-card--learning" }, h(CardContent, null,
        h("div", { className: "sr2-card-head" }, h("h2", null, "Historischer Lernbestand"), h("span", { className: "sr2-card-note" }, "separat vom Live-Routing")),
        h("div", { className: "sr2-learning" },
          h(Stat, { label: "Tool-Starts", value: overview.total_calls }),
          h(Stat, { label: "Lexikon-Wörter", value: overview.lexicon_size }),
          h(Stat, { label: "Verfolgte Tools", value: overview.tools_tracked }),
          h(Stat, { label: "Lift", value: overview.lift_active ? "aktiv" : "beobachtet" })
        )
      ))
    );
  }

  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("skill-router", Page);
  }
})();
