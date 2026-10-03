(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;
  const h = SDK.React.createElement;
  const { Card, CardContent, Badge } = SDK.components;
  const { useState, useEffect } = SDK.hooks;
  const API = "/api/plugins/skill-router";
  const copy = {
    eyebrow: "SKILL ROUTER / ROUTING INTELLIGENCE",
    title: "A clearer view of skill routing",
    subtitle: "See what the router selected, why it qualified, and how much context it used.",
    healthy: "SYSTEM HEALTHY",
    attention: "NEEDS ATTENTION",
    latest: "LATEST DECISION",
    noDecision: "No routing activity yet",
    injected: "Skills selected",
    fallback: "No skills needed",
    noMatch: "No skill met the relevance threshold. The normal skill index remains available.",
    direct: "directly requested skill(s) protected",
    inferred: "Selected from matching workflow and skill evidence.",
    budget: "CONTEXT BUDGET",
    defaultBudget: "Default discovery budget",
    expandedBudget: "Expanded for explicit intent or required workflow skills",
    activity: "Recent activity",
    live: "LIVE · REFRESHES EVERY 5 SECONDS",
    allEvents: "All routing events",
    selected: "selected",
    fallbackRow: "fallback",
    noSkills: "No skill injection",
    details: "Routing diagnostics",
    hideDetails: "Close diagnostics",
    diagnosticsNote: "Aggregated operational data. User prompts and raw session IDs are never shown.",
    eventCount: "Events",
    injectionRate: "Injection rate",
    fallbacks: "Fallbacks",
    confidence: "Avg. confidence",
    explicit: "Explicit skills protected",
    discoveryRejects: "Discovery candidates trimmed",
    matrixRejects: "Required skills over budget",
    version: "Runtime version",
    versions: "versions in history",
    noHistory: "No recent decisions yet.",
    loading: "Loading routing insights…",
    error: "Routing data is temporarily unavailable: "
  };

  function fetchJSON(path) {
    return fetch(API + path).then(function (response) {
      if (!response.ok) throw new Error(response.status + " " + response.statusText);
      return response.json();
    });
  }

  function Metric(props) {
    return h("div", { className: "sr2-metric sr2-metric--" + (props.tone || "neutral") },
      h("strong", null, String(props.value)),
      h("span", null, props.label),
      props.detail ? h("small", null, props.detail) : null
    );
  }

  function SkillChips(props) {
    const skills = props.skills || [];
    if (!skills.length) return h("p", { className: "sr2-empty-note" }, props.empty || copy.noSkills);
    return h("div", { className: "sr2-skill-list" }, skills.map(function (skill) {
      return h("span", { className: "sr2-skill-chip", key: skill }, skill);
    }));
  }

  function BudgetMeter(props) {
    const budget = Math.min(6, Math.max(3, Number(props.value || 3)));
    const cells = [];
    for (let index = 1; index <= 6; index += 1) {
      const kind = index <= budget ? (index <= 3 ? "standard" : "expanded") : "unused";
      cells.push(h("span", { className: "sr2-budget-cell sr2-budget-cell--" + kind, key: index }));
    }
    return h("div", { className: "sr2-budget" },
      h("div", { className: "sr2-budget-topline" },
        h("span", null, copy.budget),
        h("strong", null, budget + " / 6")
      ),
      h("div", { className: "sr2-budget-cells", "aria-label": copy.budget + " " + budget + " of 6" }, cells),
      h("p", null, budget > 3 ? copy.expandedBudget : copy.defaultBudget)
    );
  }

  function DecisionHero(props) {
    const event = props.event;
    if (!event) {
      return h("section", { className: "sr2-decision sr2-decision--empty" },
        h("span", { className: "sr2-section-label" }, copy.latest),
        h("h2", null, copy.noDecision),
        h("p", null, copy.noHistory)
      );
    }
    const hasSkills = Boolean(event.accepted_count);
    const subtitle = hasSkills
      ? (event.explicit_skill_count ? event.explicit_skill_count + " " + copy.direct : copy.inferred)
      : copy.noMatch;
    return h("section", { className: "sr2-decision" },
      h("div", { className: "sr2-decision-copy" },
        h("span", { className: "sr2-section-label" }, copy.latest),
        h("div", { className: "sr2-decision-title-row" },
          h("h2", null, hasSkills ? copy.injected : copy.fallback),
          h(Badge, { className: "sr2-version-badge" }, event.plugin_version || props.version || "—")
        ),
        h("p", { className: "sr2-decision-subtitle" }, subtitle),
        h(SkillChips, { skills: event.accepted, empty: event.fallback || copy.noSkills }),
        h("div", { className: "sr2-decision-meta" },
          h("span", null, "Confidence " + event.confidence),
          h("span", null, (event.estimated_chars || 0) + " chars"),
          h("span", null, event.explicit_skill_count ? event.explicit_skill_count + " explicit" : "discovery")
        )
      ),
      h(BudgetMeter, { value: event.candidate_budget })
    );
  }

  function ActivityRow(props) {
    const event = props.event;
    const time = event.ts ? new Date(event.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—";
    const hasSkills = Boolean(event.accepted_count);
    return h("div", { className: "sr2-activity-row" },
      h("time", { className: "sr2-activity-time" }, time),
      h("span", { className: "sr2-activity-status sr2-activity-status--" + (hasSkills ? "selected" : "fallback") },
        hasSkills ? event.accepted_count + " " + copy.selected : copy.fallbackRow
      ),
      h("span", { className: "sr2-activity-skills" }, (event.accepted || []).join(", ") || copy.noSkills),
      h("span", { className: "sr2-activity-budget" }, (event.candidate_budget || 3) + " / 6")
    );
  }

  function Diagnostics(props) {
    const metrics = props.metrics;
    const [open, setOpen] = useState(false);
    return h("section", { className: "sr2-diagnostics" },
      h("button", { className: "sr2-diagnostics-toggle", type: "button", onClick: function () { setOpen(!open); }, "aria-expanded": open },
        h("span", null, copy.details),
        h("span", { className: "sr2-toggle-icon" }, open ? "−" : "+")
      ),
      open ? h("div", { className: "sr2-diagnostics-body" },
        h("p", { className: "sr2-privacy-note" }, copy.diagnosticsNote),
        h("div", { className: "sr2-diagnostic-grid" },
          h(Metric, { label: copy.eventCount, value: metrics.events }),
          h(Metric, { label: copy.injectionRate, value: (metrics.injection_rate * 100).toFixed(1) + "%" }),
          h(Metric, { label: copy.fallbacks, value: metrics.fallbacks }),
          h(Metric, { label: copy.confidence, value: metrics.avg_confidence.toFixed(2) }),
          h(Metric, { label: copy.explicit, value: metrics.explicit_skill_mentions }),
          h(Metric, { label: copy.discoveryRejects, value: metrics.budget_rejections }),
          h(Metric, { label: copy.matrixRejects, value: metrics.matrix_required_budget_rejections }),
          h(Metric, { label: copy.version, value: metrics.version })
        ),
        h("p", { className: "sr2-version-history" }, Object.keys(metrics.version_distribution || {}).length + " " + copy.versions)
      ) : null
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
    if (error) return h("div", { className: "sr2-error" }, copy.error + error);
    if (!metrics) return h("div", { className: "sr2-loading" }, copy.loading);

    const latest = metrics.latest;
    const healthy = metrics.events === 0 || (metrics.avg_confidence >= 0.5 && !metrics.matrix_required_budget_rejections);
    const recent = (metrics.recent || []).slice(0, 5);
    return h("main", { className: "sr2-page" },
      h("header", { className: "sr2-header" },
        h("div", { className: "sr2-brand" },
          h("span", { className: "sr2-brand-mark", "aria-hidden": "true" }, "S"),
          h("span", { className: "sr2-brand-name" }, "SKILL ROUTER")
        ),
        h(Badge, { className: "sr2-status sr2-status--" + (healthy ? "healthy" : "attention") },
          h("span", { className: "sr2-status-dot" }), healthy ? copy.healthy : copy.attention
        )
      ),
      h("section", { className: "sr2-intro" },
        h("span", { className: "sr2-section-label" }, "ROUTING OVERVIEW"),
        h("h1", null, copy.title),
        h("p", null, copy.subtitle)
      ),
      h(DecisionHero, { event: latest, version: metrics.version }),
      h("section", { className: "sr2-summary", "aria-label": "Key routing metrics" },
        h(Metric, { label: "Skills selected", value: metrics.injections, tone: "accent" }),
        h(Metric, { label: "Safe fallbacks", value: metrics.fallbacks }),
        h(Metric, { label: "Average confidence", value: metrics.avg_confidence.toFixed(2) })
      ),
      h("section", { className: "sr2-activity" },
        h("div", { className: "sr2-section-heading" },
          h("div", null, h("span", { className: "sr2-section-label" }, "LIVE ACTIVITY"), h("h2", null, copy.activity)),
          h("span", { className: "sr2-live-indicator" }, h("i", null), copy.live)
        ),
        h("div", { className: "sr2-activity-list" }, recent.length
          ? recent.map(function (event, index) { return h(ActivityRow, { event: event, key: String(event.ts) + index }); })
          : h("p", { className: "sr2-empty-note" }, copy.noHistory))
      ),
      h(Diagnostics, { metrics: metrics })
    );
  }

  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("skill-router", Page);
  }
})();
