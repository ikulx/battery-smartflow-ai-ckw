# Battery SmartFlow AI

**Intelligente, preis-, PV- und lastbasierte Steuerung für Zendure SolarFlow Systeme in Home Assistant**

---

## 🇩🇪 Deutsch

## Überblick

**Battery SmartFlow AI** ist eine Home-Assistant-Integration zur **stabilen, wirtschaftlichen und transparenten** Steuerung von **Zendure SolarFlow** Batteriesystemen.

Ab **Version 1.4.x** kombiniert die Integration:

- ☀️ **PV-Erzeugung**
- 🏠 **Hauslast (realer Gesamtverbrauch)**
- 🔋 **Batterie-SoC**
- 💶 **Dynamische Strompreise (optional, inkl. intelligenter Vorplanung)**

zu **kontextbasierten Lade- und Entladeentscheidungen**, die **stabil**, **vorhersehbar** und **praxisnah** funktionieren.

👉 Ziel ist **nicht maximale Aktivität**, sondern **maximaler Nutzen**:
- Laden, wenn es wirtschaftlich sinnvoll ist
- Entladen, wenn Netzbezug vermieden werden kann
- Stillstand, wenn keine Verbesserung möglich ist

---

## Warum diese Integration?

Viele bestehende Lösungen arbeiten mit:
- festen Zeitplänen
- starren Preisgrenzen
- simplen Wenn-Dann-Regeln
- instabilen Umschaltlogiken (Laden ↔ Entladen)

**Zendure SmartFlow AI** verfolgt bewusst einen anderen Ansatz:

> **Kontext statt Regeln.**

Jede Entscheidung basiert auf der **aktuellen Gesamtsituation**:
- Wie hoch ist die reale Hauslast?
- Gibt es Netzbezug oder Einspeisung?
- Wie voll ist der Akku?
- Wie teuer ist Strom **jetzt** – und **in Kürze**?

---

## Grundprinzip (die „KI“)

Die Integration bewertet zyklisch:

- PV-Leistung
- Hauslast (Netzbezug + Eigenverbrauch)
- Netzdefizit / Einspeiseüberschuss
- Batterie-SoC
- aktuellen Strompreis (optional)

Daraus ergeben sich drei mögliche Aktionen:
- 🔌 **Laden**
- 🔋 **Entladen**
- ⏸️ **Nichts tun**

Die Logik ist **bewusst erklärbar**:
- Keine unnötigen Aktionen
- Keine hektischen Richtungswechsel
- Sicherheit & Wirtschaftlichkeit haben Vorrang

---

## Support & Mitwirkung

- GitHub Issues für Bugs & Feature-Wünsche
- Pull Requests willkommen
- Community-Projekt

---

**Zendure SmartFlow AI – erklärbar, stabil, wirtschaftlich.**
