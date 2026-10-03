(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;
  const h = SDK.React.createElement;
  const { Card, CardContent, Badge } = SDK.components;
  const { useState, useEffect } = SDK.hooks;
  const API = "/api/plugins/skill-router";

  function fetchJSON(path) {
    return fetch(API + path).then(function (response) {
      if (!response.ok) throw new Error(response.status + " " + response.statusText);
      return response.json();
    });
  }

  function Stat(props) {
    return h("div", { className: "sr2-stat sr2-stat--" + (props.tone || "neutral") },
      h("div", { className: "sr2-stat-value" }, String(props.value)),
      h("div", { className: "sr2-stat-label" }, props.label),
      props.detail ? h("div", { className: "sr2-stat-detail" }, props.detail) : null
    );
  }

  function Progress(props) {
    const ratio = props.max ? Math.min(1, Math.max(0, props.value / props.max)) : 0;
    return h("div", { className: "sr2-progress" },
      h("div", { className: "sr2-progress-head" }, h("span", null, props.label), h("strong", null, props.value + (props.suffix || ""))),
      h("div", { className: "sr2-track" }, h("div", { className: "sr2-fill", style: { width: (ratio * 100) + "%" } }))
    );
  }

  function BudgetRail(props) {
    const budget = Math.min(6, Math.max(3, Number(props.budget || 3)));
    const slots = [];
    for (let index = 1; index <= 6; index += 1) {
      const state = index <= budget ? (index <= 3 ? "base" : "extended") : "empty";
      slots.push(h("span", { className: "sr2-budget-slot sr2-budget-slot--" + state, key: index }, index));
    }
    return h("div", { className: "sr2-budget" },
      h("div", { className: "sr2-budget-head" },
        h("span", null, "Kandidatenbudget"),
        h("strong", null, budget + " von 6")
      ),
      h("div", { className: "sr2-budget-rail", "aria-label": "Dynamisches Kandidatenbudget" }, slots),
      h("p", { className: "sr2-budget-note" }, budget > 3
        ? "Erweitert durch explizite Nutzerabsicht oder Matrix-Pflichtskills."
        : "Drei Discovery-Plätze; Erweiterung nur bei klarer Priorität.")
    );
  }

  function Evidence(props) {
    const entries = Object.keys(props.evidence || {}).map(function (key) { return [key, props.evidence[key]]; });
    if (!entries.length) return h("div", { className: "sr2-empty" }, "Noch keine Evidenzereignisse.");
    const max = Math.max.apply(null, entries.map(function (entry) { return entry[1]; }));
    return h("div", { className: "sr2-evidence" }, entries.map(function (entry) {
      return h(Progress, { key: entry[0], label: entry[0], value: entry[1], max: max });
    }));
  }

  function EventRow(props) {
    const event = props.event;
    const time = event.ts ? new Date(event.ts * 1000).toLocaleTimeString() : "—";
    const state = event.fallback ? "fallback" : event.accepted_count ? "injected" : "observed";
    const meta = [
      event.accepted_count + " Skills",
      event.candidate_budget + "/6 Budget",
      event.explicit_skill_count ? event.explicit_skill_count + " explizit" : null,
      event.rescue ? "Kontext-Rettung" : null,
      "Confidence " + event.confidence,
    ].filter(Boolean);
    return h("div", { className: "sr2-event sr2-event--" + state },
      h("div", { className: "sr2-event-dot" }),
      h("div", { className: "sr2-event-main" },
        h("div", { className: "sr2-event-title" },
          state === "injected" ? "Routing-Injektion" : state === "fallback" ? "Sicherer Fallback" : "Beobachtung",
          h("span", { className: "sr2-event-time" }, time)
        ),
        event.accepted && event.accepted.length
          ? h("div", { className: "sr2-event-skills" }, event.accepted.map(function (name) {
              return h("span", { className: "sr2-pill", key: name }, name);
            }))
          : h("div", { className: "sr2-event-muted" }, event.fallback || "Keine Skills injiziert"),
        h("div", { className: "sr2-event-meta" }, meta.join(" · "))
      )
    );
  }

  function DecisionCard(props) {
    const latest = props.latest;
    if (!latest) return h("div", { className: "sr2-empty" }, "Noch keine Routingentscheidung aufgezeichnet.");
    const matrix = latest.stages && latest.stages.matrix_active;
    const matrixSkills = latest.stages && latest.stages.matrix_skill_count || 0;
    return h("div", { className: "sr2-decision" },
      h("div", { className: "sr2-decision-step" },
        h("span", { className: "sr2-step-index" }, "1"),
        h("div", null, h("strong", null, "Matrix-Gate"), h("p", null,
          matrix ? (matrixSkills ? matrixSkills + " Matrix-Skills qualifiziert" : "Matrix aktiv, kein Thema qualifiziert") : "Keine Matrix verfügbar"))
      ),
      h("div", { className: "sr2-decision-step" },
        h("span", { className: "sr2-step-index" }, "2"),
        h("div", null, h("strong", null, "Priorität"), h("p", null,
          latest.explicit_skill_count ? latest.explicit_skill_count + " explizit genannte Skill-ID(s) geschützt" : "Keine explizite Skill-ID erkannt"))
      ),
      h("div", { className: "sr2-decision-step" },
        h("span", { className: "sr2-step-index" }, "3"),
        h("div", null, h("strong", null, "Ergebnis"), h("p", null,
          latest.accepted_count ? latest.accepted_count + " Skills in den Prompt übernommen" : (latest.fallback || "Kein Kandidat qualifiziert")))
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
        .catch(function (exception) { setError(String(exception && exception.message || exception)); });
    }
    useEffect(function () {
      load();
      const timer = setInterval(load, 5000);
      return function () { clearInterval(timer); };
    }, []);
    if (error) return h("div", { className: "sr2-error" }, "Routing-Observatory-API nicht erreichbar: " + error);
    if (!metrics || !overview) return h("div", { className: "sr2-loading" }, "Routing Observatory wird geladen …");

    const latest = metrics.latest;
    const healthy = metrics.events === 0 || (metrics.avg_confidence >= 0.5 && !metrics.matrix_required_budget_rejections);
    const versionCount = Object.keys(metrics.version_distribution || {}).length;
    return h("div", { className: "sr2-page" },
      h("div", { className: "sr2-hero" },
        h("div", null,
          h("div", { className: "sr2-kicker" }, "SKILL ROUTER · ROUTING OBSERVATORY"),
          h("h1", null, "Entscheidungen verständlich machen"),
          h("p", null, "Datensparsame Live-Ansicht für Matrix, Priorität, Budget und Routingqualität.")
        ),
        h(Badge, { className: "sr2-health sr2-health--" + (healthy ? "ok" : "warn") }, healthy ? "● BETRIEBSBEREIT" : "● PRÜFEN")
      ),
      h("div", { className: "sr2-grid sr2-grid--stats" },
        h(Stat, { label: "Router-Version", value: metrics.version, detail: versionCount > 1 ? versionCount + " Versionen im Verlauf" : "einheitliche Auditspur", tone: "accent" }),
        h(Stat, { label: "Routing-Events", value: metrics.events, detail: "anonymisierte Auditspur" }),
        h(Stat, { label: "Injektionen", value: metrics.injections, detail: "mit Kandidaten", tone: "positive" }),
        h(Stat, { label: "Fallbacks", value: metrics.fallbacks, detail: (metrics.fallback_rate * 100).toFixed(1) + "% aller Events", tone: metrics.fallbacks ? "warning" : "positive" }),
        h(Stat, { label: "Ø Confidence", value: metrics.avg_confidence.toFixed(2), detail: "Evidenzstärke", tone: metrics.avg_confidence >= 0.7 ? "positive" : "warning" }),
        h(Stat, { label: "Explizit geschützt", value: metrics.explicit_skill_mentions, detail: "direkte Skillnennungen" })
      ),
      h("div", { className: "sr2-grid sr2-grid--main" },
        h(Card, { className: "sr2-card sr2-card--decision" }, h(CardContent, null,
          h("div", { className: "sr2-card-head" }, h("h2", null, "Letzter Entscheidungsweg"), h("span", { className: "sr2-card-note" }, latest ? latest.plugin_version : "—")),
          h(DecisionCard, { latest: latest }),
          h(BudgetRail, { budget: latest && latest.candidate_budget })
        )),
        h(Card, { className: "sr2-card" }, h(CardContent, null,
          h("div", { className: "sr2-card-head" }, h("h2", null, "Präzisionssignale"), h("span", { className: "sr2-card-note" }, "aggregiert, ohne Prompttexte")),
          h(Progress, { label: "Discovery-Budget verworfen", value: metrics.budget_rejections, max: Math.max(metrics.rejected_candidates, 1) }),
          h(Progress, { label: "Matrix-Pflicht begrenzt", value: metrics.matrix_required_budget_rejections, max: Math.max(metrics.events, 1) }),
          h("div", { className: "sr2-callout" }, "Hohe Budget-Verwerfungen zeigen eine zu breite Kandidatenfläche. Matrix-Überläufe bleiben sichtbar statt still zu verschwinden.")
        ))
      ),
      h("div", { className: "sr2-grid sr2-grid--main" },
        h(Card, { className: "sr2-card" }, h(CardContent, null,
          h("div", { className: "sr2-card-head" }, h("h2", null, "Routing-Funnel"), h("span", { className: "sr2-card-note" }, "seit Aktivierung")),
          h(Progress, { label: "Events", value: metrics.events, max: Math.max(metrics.events, 1) }),
          h(Progress, { label: "Übernommene Kandidaten", value: metrics.accepted_candidates, max: Math.max(metrics.accepted_candidates + metrics.rejected_candidates, 1) }),
          h(Progress, { label: "Verworfene Kandidaten", value: metrics.rejected_candidates, max: Math.max(metrics.accepted_candidates + metrics.rejected_candidates, 1) })
        )),
        h(Card, { className: "sr2-card" }, h(CardContent, null,
          h("div", { className: "sr2-card-head" }, h("h2", null, "Evidenzprofil"), h("span", { className: "sr2-card-note" }, "welche Signale tragen")),
          h(Evidence, { evidence: metrics.evidence }),
          h("div", { className: "sr2-callout" }, "Subword-Signale sind nur unterstützend; sie lösen allein keine Injektion aus.")
        ))
      ),
      h(Card, { className: "sr2-card" }, h(CardContent, null,
        h("div", { className: "sr2-card-head" }, h("h2", null, "Letzte Routing-Entscheidungen"), h("span", { className: "sr2-card-note" }, "aktualisiert alle 5 Sekunden")),
        metrics.recent && metrics.recent.length ? h("div", { className: "sr2-events" }, metrics.recent.map(function (event, index) {
          return h(EventRow, { event: event, key: String(event.ts) + index });
        })) : h("div", { className: "sr2-empty" }, "Noch keine Routing-Events. Die Ansicht füllt sich mit den nächsten Sessions.")
      )),
      h(Card, { className: "sr2-card sr2-card--learning" }, h(CardContent, null,
        h("div", { className: "sr2-card-head" }, h("h2", null, "Historischer Lernbestand"), h("span", { className: "sr2-card-note" }, "getrennt vom Live-Routing")),
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
