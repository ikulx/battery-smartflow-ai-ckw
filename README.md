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

## 🧠 Preis-Vorplanung (ab Version 1.4.x)

### Was bedeutet Preis-Vorplanung?

Die KI betrachtet **nicht nur den aktuellen Strompreis**, sondern analysiert **kommende Preisspitzen** im Tagesverlauf.

Ziel:

> **Vor bekannten Preisspitzen günstig Energie speichern –  
aber nur dann, wenn es wirklich sinnvoll ist.**

---

### Wie funktioniert das?

1. Analyse der kommenden Preisstruktur  
2. Erkennung einer relevanten Preisspitze:
   - **sehr teuer** oder  
   - **teuer + konfigurierbare Gewinnmarge**
3. Bewertung der günstigen Zeitfenster **vor** der Spitze  
4. Laden aus dem Netz **nur wenn**:
   - aktuell ein günstiges Zeitfenster aktiv ist  
   - kein relevanter PV-Überschuss vorhanden ist  
   - der Akku nicht voll ist  

➡️ **Keine Zeitpläne, kein Dauerladen, kein Zwang**

---

### Wichtiger Hinweis zu Sensoren

Sensoren wie **„Startzeit nächste Aktion“** oder **„Zeitstempel“** können korrekt auf **`unknown`** stehen.

Das bedeutet **keinen Fehler**, sondern:
- aktuell ist **keine Aktion notwendig**
- oder es existiert **keine wirtschaftlich sinnvolle Planung**

---

## ⚡ Sehr teure Strompreise (Prioritätslogik)

Bei **sehr teuren Strompreisen** gilt:

- Entladung hat **absolute Priorität**
- unabhängig vom Betriebsmodus
- unabhängig von PV-Ertrag
- begrenzt nur durch:
  - SoC-Minimum
  - Hardware-Grenzen (max. 2400 W)

➡️ Ziel: **Netzbezug bei extremen Preisen maximal vermeiden**

---

## Betriebsmodi

### 🔹 Automatik (empfohlen)

- PV-Überschuss wird genutzt
- Preis-Vorplanung aktiv
- Entladung bei teurem Strom
- Sehr teure Preise haben immer Vorrang

---

### 🔹 Sommer

- Fokus auf Autarkie
- Akku deckt Hauslast bei Defizit
- Keine Preis-Vorplanung
- Sehr teure Preise haben weiterhin Vorrang

---

### 🔹 Winter

- Fokus auf Kostenersparnis
- Frühere Entladung bei teurem Strom
- Preis-Vorplanung aktiv

---

### 🔹 Manuell

- Keine KI-Eingriffe
- Laden / Entladen / Standby manuell
- Ideal für Tests und Sonderfälle

---

## Sicherheitsmechanismen

### SoC-Minimum
- Unterhalb dieses Wertes wird **nicht entladen**

### SoC-Maximum
- Oberhalb dieses Wertes wird **nicht weiter geladen**

---

## 🧯 Notladefunktion (verriegelt)

- Aktivierung bei kritischem SoC
- Laden bis mindestens SoC-Minimum
- Automatische Deaktivierung
- Kein Dauer-Notbetrieb

---

## ⚠️ WICHTIG: Zwingende Voraussetzungen

Damit die Integration **stabil und korrekt** arbeitet, **müssen** folgende Punkte eingehalten werden.

### 1️⃣ Zendure Original-App

- **Lade- und Entladeleistung auf max. 2400 W setzen**
- **HEMS deaktivieren**
- ggf. vorhandene Stromsensoren **entfernen**

➡️ Die Steuerung erfolgt **ausschließlich** durch Home Assistant.

---

### 2️⃣ Zendure Home-Assistant Integration

- **Keinen P1-Sensor auswählen**
  
  <img width="445" height="361" alt="ZHA-Konfig" src="https://github.com/user-attachments/assets/c275982a-f960-478b-81fa-9232c7e5fd25" />

  - ggf. vorausgewählten Sensor **entfernen**
   
- **Energie-Export: „Erlaubt“**
  
  <img width="345" height="660" alt="ZHA-Einstellung" src="https://github.com/user-attachments/assets/07d73262-7a98-4bf9-a11a-39eb4c541ca5" />

- **Zendure Manager → Betriebsmodus: AUS**

  <img width="343" height="590" alt="ZHA Manager" src="https://github.com/user-attachments/assets/bb1cfecf-6176-4089-a651-2a9534a30aaa" />


⚠️ Falsche Einstellungen hier führen zu:
- Entladeabbrüchen
- falschen Ladezuständen
- blockierten AC-Modi

---

### 3️⃣ Strompreis-Integration (optional, empfohlen)

Unterstützt werden u. a.:

- **Tibber – Preisinformationen & Bewertungen**
- **EPEX Spot Preis-Integrationen**

➡️ Beide liefern kompatible Datenformate  
➡️ Keine zusätzliche Anpassung nötig  

---

## Installation

### Über HACS (empfohlen)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=PalmManiac&repository=battery-smartflow-ai&category=integration)

1. HACS muß in Home Assistant installiert sein  
2. HACS öffnen → oben rechts **⋮**  
3. **Benutzerdefinierte Repositories**  
4. Repository hinzufügen: https://github.com/PalmManiac/battery-smartflow-ai
Typ: **Integration**
5. Integration installieren und Home Assistant neu starten

---

## Support & Mitwirkung

- GitHub Issues für Bugs & Feature-Wünsche  
- Pull Requests willkommen  
- Community-Projekt  

---

**Zendure SmartFlow AI – erklärbar, stabil, wirtschaftlich.**
