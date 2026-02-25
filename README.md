# Battery SmartFlow AI

**Intelligente, wirtschaftliche und stabile Steuerung für Zendure SolarFlow Systeme in Home Assistant**

---

## Was macht diese Integration?

**Battery SmartFlow AI** steuert dein Zendure SolarFlow System automatisch – basierend auf:

- ☀️ PV-Erzeugung
- 🏠 Realer Hauslast
- 🔋 Batterie-SoC
- 💶 Dynamischen Strompreisen (optional)
- ⚙️ Gerätespezifischen Regelprofilen

Die Integration kombiniert diese Daten zu einer **physikalisch stabilen und wirtschaftlich optimierten Lade- und Entladestrategie**.

Ziel:

> Minimaler Netzbezug.  
> Maximale Wirtschaftlichkeit.  
> Keine hektischen Richtungswechsel.

---

# 🧠 Kernfunktionen (V2 Architektur)

- Adaptive Peak-Erkennung (individuell einstellbar)
- Preis-Vorplanung mit Valley-Erkennung
- Dynamische Netzregelung (Regelung statt Vollgas)
- Geräteprofile pro Modell
- Hard-Sync mit realem AC-Modus
- Transparenz-Sensoren für Preislogik
- Gewinn-/Ersparnis-Berechnung
- Saisonale Logik (Sommer/Winter)

---

# ⚠️ Zwingende Voraussetzungen

Damit die Integration korrekt arbeitet, **müssen** folgende Punkte erfüllt sein:

---

## 1️⃣ Zendure Original-App

In der Zendure App:

- Ladeleistung → Maximum
- Entladeleistung → Maximum
- HEMS → deaktivieren
- Keine parallelen Automationen

⚠️ Die Steuerung erfolgt ausschließlich über Home Assistant.

---

## 2️⃣ Zendure Home Assistant Integration

Folgende Einstellungen sind zwingend erforderlich:

- Kein P1-Sensor auswählen
- Energie-Export: **Erlaubt**
- Zendure Manager → Betriebsmodus **AUS**

Falsche Einstellungen führen zu:

- Blockierten AC-Modi
- Entladeabbrüchen
- Instabiler Regelung

---

## 3️⃣ Netzsensor korrekt konfigurieren

Empfohlen:

- Split-Modus mit separatem Bezug & Einspeisung  
  (z. B. Shelly Pro 3EM)

---

## 4️⃣ Strompreis-Integration (optional)

Unterstützt:

- Tibber
- EPEX
- Octopus (inkl. deutscher Forecast API)

Ohne Strompreis funktioniert PV- und lastbasierte Steuerung weiterhin.

---

# 🛠 Installation (HACS)

[![HACS Repository](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=PalmManiac&repository=battery-smartflow-ai&category=integration)

1. HACS öffnen  
2. ⋮ → Benutzerdefinierte Repositories  
3. Repository hinzufügen:  
   `https://github.com/PalmManiac/battery-smartflow-ai`  
4. Typ: Integration  
5. Installieren  
6. Home Assistant neu starten

---

# ⚙️ Konfiguration

Nach der Installation:

**Einstellungen → Geräte & Dienste → Integration hinzufügen → Battery SmartFlow AI**

---

## 1️⃣ Hauptkonfiguration

<img width="635" height="1186" alt="Screenshot 2026-02-19 134834" src="https://github.com/user-attachments/assets/541d5438-d41f-4595-8456-b93a5f5f41b7" /><img width="633" height="1228" alt="Screenshot 2026-02-25 141115" src="https://github.com/user-attachments/assets/23c3cc0b-938d-44b7-800a-7ad5fdc11711" />

Hier werden ausgewählt:

- Geräteprofil
- Batterie-SoC Sensor
- PV-Leistung
- Strompreis (optional)
- Preisverlauf (optional)
- Zendure AC-Modus
- Lade- & Entlade-Entitäten
- Netzmodus

📖 Detaillierte Erklärungen findest du in der **Anleitung (V2)**.

---

## 2️⃣ Netzmessung

<img width="631" height="708" alt="Screenshot 2026-02-25 141200" src="https://github.com/user-attachments/assets/c86a8dce-c792-426a-8b33-9b01ffbba776" />

Du kannst wählen zwischen:

- Kein Netzsensor
- Ein kombinierter Sensor (+/-)
- Zwei Sensoren (Bezug & Einspeisung)

Empfohlen: **Zwei Sensoren**.

---

## 3️⃣ Split-Sensor Auswahl

<img width="421" height="475" alt="Screenshot 2026-02-25 141224" src="https://github.com/user-attachments/assets/d0dc939a-be84-4b70-8053-29207e3612ba" />

Hier werden:

- Netzbezug
- Netzeinspeisung

separat ausgewählt.

---

# ⚙️ Geräteprofile

Die Integration nutzt modellabhängige Regelparameter.

Aktuell unterstützt:

- SF800Pro
- SF1600AC+
- SF2400AC

Das Profil beeinflusst u. a.:

- Ziel-Netzbezug
- Regelgeschwindigkeit
- Export-Toleranz
- Hardware-Grenzen

---

# 🧠 Peak-Faktor (Adaptive Peak)

Der Peak-Faktor ist über die GUI einstellbar und beeinflusst die Erkennung von Preisspitzen.

Formel:

Peak-Schwelle = max(
Durchschnittspreis × Peak-Faktor,
Durchschnittspreis + 0,03 €
)

Standard: **1.35**

- Niedriger → erkennt mehr Peaks (sensitiver)
- Höher → erkennt nur starke Preisspitzen (konservativer)

---

# 📊 Transparenz-Sensoren (V2)

V2 macht die Preislogik sichtbar, z. B.:

- Ø Tagespreis
- Aktuelle Peak-Schwelle
- Engine-Status
- Adaptive Peak aktiv

---

# 💶 Gewinn / Ersparnis

Die Integration kann:

- Ø Ladepreis (gewichteter Durchschnitt)
- Entladene Energie
- Preis-Differenz
- Gesamtgewinn in €

sichtbar machen.

Hinweis: Details zur Berechnung stehen in der **Anleitung (V2)**.

---

# 🔄 Betriebsmodi

## Automatik (empfohlen)
Preis + PV + Last kombiniert.

## Sommer
Autarkie-Fokus, ohne Preisplanung.

## Winter
Wirtschaftlichkeits-Fokus, mit Preisplanung.

## Manuell
Keine KI-Eingriffe, Laden/Entladen/Standby manuell.

---

# 🛡 Sicherheitsmechanismen

- SoC-Minimum / SoC-Maximum
- BMS-Limit-Erkennung (SoC-Limit Status)
- Notladefunktion (Emergency)
- Hard-Sync mit realem Zendure AC-Modus

---

# 📖 Dokumentation

Diese README bietet eine Übersicht.

Für Details (inkl. Screenshots, Beispiele, FAQ) siehe:

- **Anleitung (V2)**

---

# Support & Mitwirkung

- GitHub Issues für Bugs & Feature-Wünsche
- Pull Requests willkommen

---

**Battery SmartFlow AI – erklärbar, stabil, wirtschaftlich.**
