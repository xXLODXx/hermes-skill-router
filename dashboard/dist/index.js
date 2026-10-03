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

  function Metric(props) {
    return h("div", { className: "sr2-metric" },
      h("strong", null, String(props.value)),
      h("span", null, props.label)
    );
  }

  function SkillPills(props) {
    const skills = props.skills || [];
    return skills.length
      ? h("div", { className: "sr2-pills" }, skills.map(function (skill) {
          return h("span", { className: "sr2-pill", key: skill }, skill);
        }))
      : h("p", { className: "sr2-muted" }, props.empty || "Keine Skills vorgeschlagen.");
  }

  function Budget(props) {
    const budget = Math.min(6, Math.max(3, Number(props.value || 3)));
    return h("div", { className: "sr2-budget" },
      h("span", null, "Budget"),
      h("strong", null, budget + " / 6"),
      budget > 3 ? h("em", null, "erweitert") : null
    );
  }

  function Decision(props) {
    const latest = props.latest;
    if (!latest) return h("p", { className: "sr2-muted" }, "Noch keine Routingentscheidung aufgezeichnet.");
    const status = latest.accepted_count ? "Skills vorgeschlagen" : "Sicherer Fallback";
    const explanation = latest.accepted_count
      ? latest.explicit_skill_count
        ? latest.explicit_skill_count + " direkt genannte Skill-ID(s) wurden geschützt."
        : "Aus passenden Matrix- und Katalogsignalen ausgewählt."
      : "Kein Skill war ausreichend passend – nichts wird unnötig geladen.";
    return h("div", { className: "sr2-decision" },
      h("div", { className: "sr2-decision-head" },
        h("div", null, h("span", { className: "sr2-eyebrow" }, "LETZTE ENTSCHEIDUNG"), h("h2", null, status)),
        h(Budget, { value: latest.candidate_budget })
      ),
      h(SkillPills, { skills: latest.accepted, empty: latest.fallback }),
      h("p", { className: "sr2-decision-copy" }, explanation),
      h("div", { className: "sr2-decision-meta" },
        "Confidence " + latest.confidence + " · " + latest.estimated_chars + " Zeichen · Router " + latest.plugin_version
      )
    );
  }

  function RecentRow(props) {
    const event = props.event;
    const time = event.ts ? new Date(event.ts * 1000).toLocaleTimeString() : "—";
    const label = event.accepted_count ? event.accepted_count + " Skill" + (event.accepted_count === 1 ? "" : "s") : "Fallback";
    return h("div", { className: "sr2-recent-row" },
      h("span", { className: "sr2-recent-time" }, time),
      h("span", { className: "sr2-recent-label" }, label),
      h("span", { className: "sr2-recent-skills" }, (event.accepted || []).join(", ") || "Keine Injektion")
    );
  }

  function Page() {
    const [metrics, setMetrics] = useState(null);
    const [error, setError] = useState(null);
    function load() {
      fetchJSON("/runtime-metrics")
        .then(function (data) { setMetrics(data); setError(null); })
        .catch(function (exception) { setError(String(exception && exception.message || exception)); });
    }
    useEffect(function () {
      load();
      const timer = setInterval(load, 5000);
      return function () { clearInterval(timer); };
    }, []);
    if (error) return h("div", { className: "sr2-error" }, "Router-Daten sind gerade nicht erreichbar: " + error);
    if (!metrics) return h("div", { className: "sr2-loading" }, "Skill Router wird geladen …");

    const latest = metrics.latest;
    const healthy = metrics.events === 0 || (metrics.avg_confidence >= 0.5 && !metrics.matrix_required_budget_rejections);
    return h("main", { className: "sr2-page" },
      h("header", { className: "sr2-header" },
        h("div", null,
          h("span", { className: "sr2-eyebrow" }, "SKILL ROUTER"),
          h("h1", null, "Einfacher Überblick"),
          h("p", null, "Was zuletzt ausgewählt wurde – ohne Prompttexte oder technische Überladung.")
        ),
        h(Badge, { className: "sr2-status" }, healthy ? "Aktiv" : "Prüfen")
      ),
      h(Card, { className: "sr2-card sr2-card--primary" }, h(CardContent, null, h(Decision, { latest: latest }))),
      h("section", { className: "sr2-metrics", "aria-label": "Routing Übersicht" },
        h(Metric, { value: metrics.injections, label: "Injektionen" }),
        h(Metric, { value: metrics.fallbacks, label: "Sichere Fallbacks" }),
        h(Metric, { value: metrics.avg_confidence.toFixed(2), label: "Ø Confidence" })
      ),
      h(Card, { className: "sr2-card" }, h(CardContent, null,
        h("div", { className: "sr2-section-head" }, h("h2", null, "Letzte Entscheidungen"), h("span", null, "automatisch aktualisiert")),
        h("div", { className: "sr2-recent" }, (metrics.recent || []).slice(0, 5).map(function (event, index) {
          return h(RecentRow, { event: event, key: String(event.ts) + index });
        }))
      )),
      h("details", { className: "sr2-details" },
        h("summary", null, "Technische Details anzeigen"),
        h("div", { className: "sr2-details-grid" },
          h(Metric, { value: metrics.events, label: "Audit-Events" }),
          h(Metric, { value: metrics.explicit_skill_mentions, label: "Explizit geschützt" }),
          h(Metric, { value: metrics.budget_rejections, label: "Discovery verworfen" }),
          h(Metric, { value: metrics.matrix_required_budget_rejections, label: "Matrix begrenzt" })
        ),
        h("p", { className: "sr2-muted" }, "Router-Version " + metrics.version + " · " + Object.keys(metrics.version_distribution || {}).length + " Version(en) im Verlauf")
      )
    );
  }

  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("skill-router", Page);
  }
})();
