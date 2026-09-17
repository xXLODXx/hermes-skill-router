# Changelog

Alle nennenswerten Änderungen am Skill-Router-Plugin. Format orientiert sich an
Keep a Changelog; Versionierung: SemVer-PoC (0.x).

## 0.8.2 — 2026-09-16

### Changed
- **Spezifitäts-Gewichtung (Katalog-Frequenz):** Tag-, Beschreibungs- und
  Teilwort-Evidenz wird mit der Häufigkeit des getroffenen Katalog-Worts
  skaliert (`min(1, 6/df)`). Ein Wort, das ein großer Teil des Katalogs teilt,
  kann allein kein Kandidat mehr werden und verdrängt keine echten Treffer
  mehr aus dem Budget. Namen bleiben unskaliert (explizite Signale).
  Messung an den echten Katalogen (195/57/127 Skills, 14 Tasks): Passer pro
  Task z. B. 35→26, 13→4, 18→12, 9→2; Budget-Verwerfungen entsprechend
  (API-Audit 10→1); Top-Treffer in allen 42 Task×Katalog-Prüfungen stabil.

### Added
- Neuer Audit-Grund `generisches Signal (katalogweit häufig)` in `top_rejected`
  — macht skaliert-verworfene Massenwörter für künftiges Tuning sichtbar.
- Tests: generisches Tag allein triggert nicht; Massen-Tags verbrauchen kein
  Budget; spezifisches Tag/Desc-Korroboration triggert weiter (RED→GRÜN:
  3 → 0 Fehler).

## 0.8.1 — 2026-09-16

### Fixed
- **Audit-Ablage folgt der Session:** Records werden gegen die Installation
  des Session-Profils aufgelöst (`<home>/plugins/skill-router/data/`, Marker:
  `plugin.yaml`), Fallback bleibt die geladene Kopie. In Multiplex-Hosts
  (ein Prozess, mehrere Profile) landeten Fremd-Sessions zuvor im
  Datenordner der ausführenden Kopie; seit 0.800 waren die Routing-Daten
  korrekt session-gebunden, die Ablage zieht jetzt nach.

### Added
- Tests: Pfad-Auflösung (Session-Install bevorzugt; Fallback ohne Install)
  und End-to-End-Record im Session-Install (RED→GRÜN: 7 → 0 Fehler).

## 0.800 — 2026-09-16

### Added
- **Context rescue:** ein Follow-up-Turn ohne eigenen Treffer („mach weiter“)
  wird gegen den begrenzten Session-Kontext (letzte 2 Tool-Ergebnisse,
  500 Zeichen je; letzte Assistant-Antwort, 800 Zeichen) erneut geprüft —
  RAM-only, harte Caps, abschaltbar über `SKILL_ROUTER_CONTEXT_RESCUE=0`.
- **Fallback-Hinweis** wird jetzt tatsächlich emittiert: einmalig im ersten
  Turn einer Session, wenn nichts matcht (vorher: nur Audit, README behauptete
  fälschlich eine Ausgabe).
- **Audit-Events angereichert:** `catalog_size`, `profile`, `matrix_source`,
  `rescue`, `fallback_emitted`, `rendered_chars`, `top_rejected` — macht
  Profil-/Katalog-Fehlbindungen und Ranking-Grenzfälle direkt sichtbar.
- **Katalog- und Matrix-Cache** (mtime-/size-gekeyt): keine wiederholten
  Datei-Reads pro Turn bei unverändertem Bestand.
- `SKILL_ROUTER_SESSION_TTL` (Default 3600 s) konfigurierbar.

### Changed
- **Profil-sichere Home-Auflösung:** `engine.hermes_home()` nutzt jetzt den
  context-lokalen Host-Resolver `hermes_constants.get_hermes_home()`
  (Multiplex-sicher); Standalone-Fallback: `HERMES_HOME` → Plugin-Layout
  (`<home>/plugins/<name>`) → `~/.hermes`.
- **Kompaktes Injektionsformat:** `- <pfad> — <decision>, <conf> (<kinds>)`.
  Messung an 236 Live-Injektionen: −19 Zeichen/Zeile und −28 Zeichen Header,
  zusammen **−25 %** (⌀ 369 → 276 Zeichen).
- Version aus einer Quelle (`plugin.yaml` → `skill_router/version.py`);
  Dashboard-API liest sie statt eines Literals.
- Mirror-Test kennt profil-lokale Installationen (`SKILL_ROUTER_INSTALL_DIR`
  Override; Selbst-Erkennung im `plugins/`-Layout).
- Tests isolieren den Audit-Pfad (vorher schrieben Hook-Tests in den echten
  Datenordner).

### Fixed
- Default-Sessions konnten in Multiplex-Hosts mit dem Katalog eines anderen
  Profils geroutet werden (os.environ-Leak, verifiziert 2026-09-16).

## 0.7.1 — 2026-09-10

- Matrix-`Pflicht`-Skills sind vom Discover-Budget (max. 3) ausgenommen.
- Matrix-Resolution pro Profil (aktive Workflow-Matrix als Default).
- Katalogscan folgt Symlink-Verzeichnissen (`os.walk(followlinks=True)`);
  `rglob` hatte 35 von 57 Skills im App-Profil übersehen.

## 0.7.0 — 2026-09-09

- v2-Runtime: session-sichere, evidenzbasierte Routing-Pipeline
  (Katalog → Evidenz → Selektor → Render), Privacy-Audit-JSONL,
  Mission-Control-Dashboard.
