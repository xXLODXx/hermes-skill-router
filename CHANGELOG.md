# Changelog

Alle nennenswerten Änderungen am Skill-Router-Plugin. Format orientiert sich an
Keep a Changelog; Versionierung: SemVer-PoC (0.x).

## 0.8.5 — 2026-09-23

### Fixed
- **Matrix-Teilwort-Fehlrouting verhindert:** Matrix-Keywords werden jetzt als
  vollständige Tokens geprüft. Das kurze Flutter-Keyword `ui` matcht damit
  nicht mehr innerhalb von Wörtern wie `Build`; mehrteilige Keywords verlangen
  alle ihre Tokens. So werden falsche Pflicht-Injektionen verhindert.

### Added
- Regressionstest für die zuvor fehlerhafte Anfrage `Build a Python CLI.`.

## 0.8.4 — 2026-09-22

### Fixed
- **Confidence-Decke entfernt:** Die v2-Confidence saturierte ab starken
  Evidenzwerten bei `0.99`, wodurch Downstream-Consumer Top-1 und Top-2 nicht
  mehr unterscheiden konnten. Sie ist jetzt eine begrenzte, strikt monotone
  Transformation des kalibrierten Evidenzsignals und bleibt unter 1.
- **Korroborations-Rangfolge bewahrt:** Der frühere +0,12-Bonus für Evidenz aus
  mehreren Feldarten bleibt als äquivalenter +1,2-Bonus im kalibrierten Score
  erhalten; die Discovery-Budget-Reihenfolge regressiert dadurch nicht.

### Added
- `CandidateDecision.score` und `CandidateDecision.exact_score` stellen
  Consumern unveränderte bzw. Teilwort-bereinigte Scores bereit (mit Defaults
  am Ende der Datenklasse, daher positionskompatibel).
- Audit-Events führen `score_min`, `score_max` und `score_avg`; Top-Rejects
  enthalten ihren Rohscore.
- Tests für Ceiling-Kollisionen und die Cross-Kind-Korroborationsgrenze.

## 0.8.3 — 2026-09-17

### Fixed
- **Legacy-Scan folgt Symlinks:** `engine.scan_skills` (Dashboard-Cluster)
  nutzte `rglob` und übersah Skills hinter Symlink-Verzeichnissen — im
  Profil-Layout fehlten sie im Dashboard (ROT-Test gegen den Altstand belegt).
  Jetzt `os.walk(followlinks=True)` + derselbe Walk-Cache wie im v2-Katalog.
- **Toter Parameter entfernt:** `word_status(..., best_tool, ...)` nutzte den
  Wert nie; Signatur und alle 9 Aufrufer (Dashboard + Tests) bereinigt.

### Performance (gemessen am 195-Skill-Katalog)
- **Baum-Walk TTL-gecacht** (`SKILL_ROUTER_SCAN_TTL`, Default 15 s, 0 = aus):
  `scan_catalog` **18,5 ms → 0,8 ms** pro Turn; Inhaltsänderungen greifen
  weiterhin sofort (per-File-stat), Neuzugänge ≤ TTL.
- **Tokenizer memoisiert** (`lru_cache`, bounded): `select()` **20,4 → 14,9 ms**.
- Turn-Pfad gesamt (scan + select): **~38,9 → ~15,7 ms (−60 %)**.
- Dashboard-`runtime-metrics` jetzt mtime-gecacht (wie die übrigen Endpunkte).

### Housekeeping
- B007/C416 in Dashboard/Engine bereinigt; `zip(..., strict=False)` explizit
  (bewusstes Kurz-Abbrechen dokumentiert).

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
