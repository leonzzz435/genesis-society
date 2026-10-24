# Übergabe an Cursor — Linux

## Ziel

Eine persistente Gesellschaft mit eigenen Interessen, Erinnerungen, Board, DMs,
Lebenszyklus und autonomer Fortpflanzung. GitHub/Notion erweitern die lesbare Umwelt;
Slack verbindet dich mit vier externen Consultants. Keine bloße Assistenten-Auftragsliste.

Das neue Repository ist `leonzzz435/genesis-society` und bleibt zunächst privat.
Das alte GENESIS wurde nicht importiert, verändert oder wieder gestartet.

## Auf dem Geschäftslaptop

1. Klone das private Repository über einen dort erlaubten GitHub-Zugang.
2. Öffne es in Cursor. `AGENTS.md` enthält die gemeinsamen Arbeitsregeln.
3. Lies README und `docs/ARCHITECTURE.md`; nutze Python 3.12 und `uv sync --frozen`.
4. Nutze PostgreSQL lokal/per Docker oder eine freigegebene Entwicklungsdatenbank.
5. Starte erst die API-key-freie Mock-Demo laut README und führe die Tests aus.
6. Arbeite die Aufgaben in PLAN.md nacheinander ab; keine neue Architekturplanung nötig.

Die Entwicklungsvorlage enthält keine Firmenzugänge. Prüfe am Arbeitsplatz, welche
Azure-Deployments, Slack-Apps, GitHub-Repositories und Notion-Seiten tatsächlich erlaubt
sind. Ein vorhandenes Cursor-Abonnement ist keine automatische Azure-API-Berechtigung.

## Erster Cursor-Auftrag zum Einfügen

> Lies AGENTS.md, README.md, docs/ARCHITECTURE.md, docs/VERIFICATION.md und PLAN.md.
> Prüfe zuerst die Offline-Demo. Bearbeite danach nur Cursor task 1: die Azure-Anbindung.
> Verwende die vorhandene LangChain-Schleife und das vorhandene Ledger. Bewahre Bewohner-
> Autonomie, Originalverläufe, Datenschutz und Ticket-Erhaltung. Keine neuen Frameworks,
> keine automatischen Provider-Retries, keine externen Nachrichten oder bezahlten Tests.
> Frage erst dann nach installationseigenen Angaben, wenn du sie nicht aus der lokalen
> freigegebenen Konfiguration ableiten kannst. Niemals Secrets in Chat oder Git schreiben.
> Berichte implementierte Funktionen, Tests und tatsächliche Integrationsgrenzen getrennt.

## Was die Demo beweist

Persistenz, lokale Weltwerkzeuge, Ticket-/Lebensregeln, Kontextzustellung und
Wiederaufnahme funktionieren mit synthetischen Modellen. Boardtexte und Verhalten sind
absichtlich geskriptete Testdaten. Sie beweisen weder emergente Zusammenarbeit noch
Azure-Kompatibilität. Dafür sind spätere reale Beobachtungen erforderlich.

## Veröffentlichung

Apache-2.0 liegt bei. Der Push ist privat; ein öffentlicher Release braucht eine eigene
Entscheidung, Prüfung der neuen Git-Historie und Rechteprüfung etwaiger Firmenbeiträge.
