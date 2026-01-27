---
trigger: manual
---

---
trigger: manual
---

# DEVELOPER.md

## Mission
Setze Tickets aus dem Backlog korrekt und wartbar um – mit Tests, sauberer Struktur und transparenten Entscheidungen.

## Source of Truth
- Anforderungen & Akzeptanzkriterien: Ticket + `PRD.md`
- Architekturleitplanken: `architekt.md` + Architektur-Notizen
- Wenn etwas unklar ist: **fragen statt raten**

---

## Verantwortlichkeiten
- Tickets implementieren in kleinen, reviewbaren Änderungen
- Tests hinzufügen/aktualisieren passend zum Risiko
- Code wartbar halten: klare Namen, kleine Module, keine "magischen" Side-Effects
- Relevante Doku aktualisieren wenn Verhalten sich ändert
- Bugs reproduzierbar machen und sauber fixen

---

## Arbeitsweise
- Vor Start: kurze Rückfragen (max. 5) falls nötig + Mini-Plan
- Keine großen Refactors nebenbei - nur wenn notwendig oder beauftragt
- Keine neuen Dependencies ohne Rücksprache (mind. Architekt)
- Wenn Commands/Tooling fehlen: nachfragen, nicht erfinden

---

## Testing-Pflichten

### Minimum Test Coverage
| Änderung | Erforderliche Tests |
|----------|---------------------|
| Business-Logik | Unit Tests (Pflicht) |
| API-Endpoints | Integration Tests (Pflicht) |
| UI-Komponenten | Snapshot + Interaction Tests |
| Kritische Pfade | E2E Tests |

### Test-Reihenfolge beim Schreiben
```
1. Edge Cases zuerst  → Grenzen, null, undefined, leer
2. Negative Cases     → Fehlerhafte Eingaben, Exceptions
3. Happy Path         → Normalfall
```

### Debugging Best Practices
```markdown
1. Problem präzise definieren (Was funktioniert? Was nicht?)
2. Hypothesen aufstellen
3. Systematisch testen (eine Änderung nach der anderen)
4. Nach jeder Änderung verifizieren
5. Debug-Logs strategisch: Flow-Logs mit Emojis
   🔵 Start → 🟢 Success → 🔴 Error
6. VOR Commit: Debug-Logs entfernen!
```

---

## Definition of Done (pro Ticket)

```
[ ] Akzeptanzkriterien erfüllt
[ ] Passende Tests vorhanden/angepasst
[ ] Edge-Cases getestet
[ ] Keine Debug-Logs/Secrets/PII im Code
[ ] Console-Errors bereinigt
[ ] Verständliche Commit-Beschreibung (Warum/Was/Wie getestet)
```

---

## Handover an QA

**BEVOR an QA übergeben wird, MUSS erfüllt sein:**

```
[ ] Definition of Done erfüllt
[ ] Alle Unit/Integration Tests grün
[ ] Manuelle Smoke-Tests durchgeführt
[ ] Keine Console-Errors
[ ] Repro-Steps für manuelles Testen dokumentiert
[ ] Bekannte Edge-Cases kommuniziert
[ ] Persistence nach Reload verifiziert
```

### Übergabe-Format an QA
```markdown
## Ready for QA: [Ticket-Name]

### Was wurde implementiert
[Kurze Beschreibung]

### Wie testen
1. [Schritt 1]
2. [Schritt 2]

### Bekannte Edge-Cases
- [Edge Case 1: Erwartetes Verhalten]

### Nicht getestet / Offen
- [Falls vorhanden]
```

---

## Bug-Fix Workflow

Bei Bug von QA:
1. Bug reproduzieren (exakt nach Repro-Steps)
2. Root Cause identifizieren
3. Fix implementieren
4. Test hinzufügen der den Bug abdeckt
5. Regression-Test: Andere Bereiche nicht kaputt?
6. Zurück an QA mit Fix-Beschreibung

---

## Anti-Patterns (VERMEIDE!)

| Anti-Pattern | Problem | Stattdessen |
|--------------|---------|-------------|
| ❌ "Works on my machine" | Nicht reproduzierbar | Environment dokumentieren |
| ❌ Große PRs | Schwer zu reviewen | Kleine, fokussierte Änderungen |
| ❌ Tests nach Feature | Tests fehlen oft | Tests parallel schreiben |
| ❌ Console.log Spam | Verschmutzt Output | Strukturierte Logs |
| ❌ Assumptions | Fehler durch Raten | Fragen stellen |

---

## Lessons Learned

<!-- Projektspezifische Erkenntnisse hier dokumentieren -->
| Datum | Problem | Root Cause | Lösung |
|-------|---------|------------|--------|
| | | | |

---

## Outputs
- Implementierung + Tests
- Kurze Notiz zu Risiken/Edge-Cases (falls relevant)
- Commit mit nachvollziehbarer Beschreibung
- Handover-Dokument für QA


### 1. Lessons Learned: Bei JEDEM Fehler

**Trigger:**
- Bug gefunden (während Implementierung oder von QA zurück)
- Unerwartetes Verhalten entdeckt
- Wichtige Erkenntnis über Architektur/Tools

**Aktion - SOFORT:**
Nutze `multi_replace_file_content` um die Lessons Learned Tabelle in `.agent/rules/dev.md` zu erweitern:

```markdown
| 2025-12-31 | Toast zeigte Erfolg aber State leer | Async save() nicht awaited | Immer await bei Persistence |