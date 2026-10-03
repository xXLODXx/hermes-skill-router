(function () {
  "use strict";
  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;
  const h = SDK.React.createElement;
  const { Badge } = SDK.components;
  const { useState, useEffect } = SDK.hooks;
  const API = "/api/plugins/skill-router";
  const t = {
    title: "Every skill, exactly when it matters.",
    subtitle: "A privacy-safe view of how intent becomes the right working context.",
    healthy: "ROUTING HEALTHY", attention: "REVIEW SIGNALS", route: "LATEST ROUTE",
    pipeline: "ROUTING PIPELINE", performance: "ROUTING PERFORMANCE", activity: "RECENT ROUTES",
    selected: "Skills selected", fallback: "No skill injection needed", noActivity: "No routing activity yet.",
    loading: "Loading routing intelligence…", diagnostics: "Advanced diagnostics"
  };
  function api(path) { return fetch(API + path).then(function (r) { if (!r.ok) throw new Error(r.status + " " + r.statusText); return r.json(); }); }
  function percent(value) { return Math.max(0, Math.min(100, Math.round(Number(value || 0) * 100))); }
  function time(ts) { return ts ? new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"; }
  function Chips(props) {
    const skills = props.skills || [];
    return skills.length ? h("div", { className: "sr3-chips" }, skills.map(function (skill) { return h("span", { className: "sr3-chip", key: skill }, skill); })) : h("span", { className: "sr3-no-skill" }, props.empty || "No skill injection");
  }
  function Metric(props) {
    return h("div", { className: "sr3-metric sr3-metric--" + (props.tone || "neutral") }, h("span", null, props.label), h("strong", null, props.value), props.note ? h("small", null, props.note) : null);
  }
  function Budget(props) {
    const budget = Math.min(6, Math.max(3, Number(props.value || 3)));
    return h("div", { className: "sr3-budget" },
      h("div", { className: "sr3-budget-head" }, h("span", null, "CONTEXT BUDGET"), h("strong", null, budget + " / 6")),
      h("div", { className: "sr3-budget-track" }, [1,2,3,4,5,6].map(function (step) { return h("i", { key: step, className: step <= budget ? (step <= 3 ? "sr3-base" : "sr3-expand") : "" }); })),
      h("p", null, budget > 3 ? "Expanded for direct intent or a required workflow." : "Using the focused discovery baseline.")
    );
  }
  function Hero(props) {
    const event = props.event;
    const selected = Boolean(event && event.accepted_count);
    const score = percent(event && event.confidence);
    return h("section", { className: "sr3-hero" }, h("div", { className: "sr3-hero-copy" },
      h("div", { className: "sr3-kicker" }, h("span", null, t.route), event ? h(Badge, { className: "sr3-version" }, event.plugin_version || props.version) : null),
      h("h2", null, event ? (selected ? t.selected : t.fallback) : "Waiting for the first route"),
      h("p", null, event ? (selected ? "The router found focused, high-confidence context for this request." : "No skill crossed the relevance threshold. The regular skill index remains available.") : t.noActivity),
      h(Chips, { skills: event && event.accepted, empty: event && event.fallback }),
      event ? h("div", { className: "sr3-meta" }, h("span", null, h("b", null, event.explicit_skill_count || 0), " explicitly requested"), h("span", null, h("b", null, event.estimated_chars || 0), " context chars"), h("span", null, h("b", null, time(event.ts)), " latest event")) : null
    ), h("aside", { className: "sr3-hero-aside" },
      h("div", { className: "sr3-ring", style: { "--score": score + "%" } }, h("div", null, h("strong", null, score + "%"), h("span", null, "route confidence"))),
      h(Budget, { value: event && event.candidate_budget })
    ));
  }
  function Pipeline(props) {
    const e = props.event || {}, selected = Number(e.accepted_count || 0), reviewed = selected + Number(e.rejected_count || 0);
    const steps = [["01", "Intent signal", "Privacy-safe intent analysis", "Private by design"], ["02", "Evidence review", "Relevant skills ranked and checked", reviewed ? reviewed + " candidates reviewed" : "Ready to evaluate"], ["03", "Context ready", "Only useful context is added", selected ? selected + " skill" + (selected === 1 ? "" : "s") + " selected" : "No context added"]];
    return h("section", { className: "sr3-pipeline-section" }, h("div", { className: "sr3-heading" }, h("div", null, h("span", null, t.pipeline), h("h2", null, "How the latest decision was made")), h("small", null, "LAST SIGNAL · " + time(e.ts))), h("div", { className: "sr3-pipeline" }, steps.map(function (s, i) { return h("div", { className: "sr3-step", key: s[0] }, h("span", { className: "sr3-step-number" }, s[0]), h("div", null, h("h3", null, s[1]), h("p", null, s[2]), h("small", null, s[3])), i < 2 ? h("b", { className: "sr3-arrow" }, "→") : null); })));
  }
  function Activity(props) {
    const e = props.event, selected = Boolean(e.accepted_count);
    return h("div", { className: "sr3-activity-row" }, h("time", null, time(e.ts)), h("i", { className: "sr3-event-dot sr3-event-dot--" + (selected ? "selected" : "fallback") }), h("div", { className: "sr3-activity-body" }, h("strong", null, selected ? e.accepted_count + " skills selected" : t.fallback), h(Chips, { skills: e.accepted })), h("div", { className: "sr3-event-score" }, h("strong", null, percent(e.confidence) + "%"), h("span", null, "confidence")));
  }
  function Diagnostics(props) {
    const [open, setOpen] = useState(false), m = props.metrics;
    return h("section", { className: "sr3-diagnostics" }, h("button", { type: "button", onClick: function () { setOpen(!open); }, "aria-expanded": open }, h("span", null, t.diagnostics), h("b", null, open ? "−" : "+")), open ? h("div", { className: "sr3-diagnostic-panel" }, h("p", null, "Aggregated operational data only. User prompts and raw session IDs are never displayed."), h("div", { className: "sr3-diagnostic-grid" }, h(Metric, { label: "Events", value: m.events }), h(Metric, { label: "Explicit skills protected", value: m.explicit_skill_mentions }), h(Metric, { label: "Discovery candidates trimmed", value: m.budget_rejections }), h(Metric, { label: "Required skills over budget", value: m.matrix_required_budget_rejections }), h(Metric, { label: "Runtime version", value: m.version }))) : null);
  }
  function Page() {
    const [metrics, setMetrics] = useState(null), [error, setError] = useState(null);
    useEffect(function () { function load() { api("/runtime-metrics").then(function (data) { setMetrics(data); setError(null); }).catch(function (e) { setError(String(e.message || e)); }); } load(); const id = setInterval(load, 5000); return function () { clearInterval(id); }; }, []);
    if (error) return h("div", { className: "sr3-error" }, "Routing data is temporarily unavailable: " + error);
    if (!metrics) return h("div", { className: "sr3-loading" }, t.loading);
    const healthy = metrics.events === 0 || (metrics.avg_confidence >= 0.5 && !metrics.matrix_required_budget_rejections), rate = metrics.events ? Math.round(metrics.injections / metrics.events * 100) : 0;
    return h("main", { className: "sr3-page" },
      h("header", { className: "sr3-header" }, h("div", { className: "sr3-brand" }, h("i", null, "↗"), h("span", null, "SKILL ROUTER")), h("div", { className: "sr3-header-status" }, h("small", null, "v" + metrics.version), h(Badge, { className: "sr3-status sr3-status--" + (healthy ? "healthy" : "attention") }, h("i", null), healthy ? t.healthy : t.attention))),
      h("section", { className: "sr3-intro" }, h("span", null, "ROUTING INTELLIGENCE"), h("h1", null, t.title), h("p", null, t.subtitle)),
      h(Hero, { event: metrics.latest, version: metrics.version }), h(Pipeline, { event: metrics.latest }),
      h("section", { className: "sr3-performance" }, h("div", { className: "sr3-heading" }, h("div", null, h("span", null, t.performance), h("h2", null, "Quality at a glance"))), h("div", { className: "sr3-metric-grid" }, h(Metric, { label: "Routes with skills", value: metrics.injections, note: rate + "% of routes", tone: "accent" }), h(Metric, { label: "Safe fallbacks", value: metrics.fallbacks, note: "Relevance threshold preserved" }), h(Metric, { label: "Average confidence", value: percent(metrics.avg_confidence) + "%", note: "Across recorded routes" }), h(Metric, { label: "Average skills per route", value: metrics.avg_candidates.toFixed(1), note: "Focused context per route" }))),
      h("section", { className: "sr3-activity" }, h("div", { className: "sr3-heading" }, h("div", null, h("span", null, t.activity), h("h2", null, "Live decision feed")), h("small", { className: "sr3-live" }, h("i", null), "LIVE · REFRESHES EVERY 5 SECONDS")), h("div", { className: "sr3-activity-list" }, (metrics.recent || []).slice(0, 5).length ? metrics.recent.slice(0, 5).map(function (e, i) { return h(Activity, { event: e, key: String(e.ts) + i }); }) : h("p", { className: "sr3-empty" }, t.noActivity))),
      h(Diagnostics, { metrics: metrics })
    );
  }
  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") window.__HERMES_PLUGINS__.register("skill-router", Page);
})();
