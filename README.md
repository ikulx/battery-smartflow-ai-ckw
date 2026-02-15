# Battery SmartFlow AI

**Intelligente, preis-, PV- und lastbasierte Steuerung für Zendure SolarFlow Systeme in Home Assistant**

---

## 🇩🇪 Deutsch

---

## Version 1.5.0

## ⚠️ Wichtiger Hinweis (ab Version 1.5.0)

Die Integration wurde von  
**„Zendure SmartFlow AI“**  
in  
**„Battery SmartFlow AI“**  
umbenannt.

### ❗ Einmalige Neuinstallation erforderlich

Bitte vor dem Update:

1. In **HACS → Benutzerdefinierte Repositories**  
   den alten Eintrag entfernen  
2. Home Assistant neu starten  
3. Repository erneut hinzufügen:  
   `https://github.com/PalmManiac/battery-smartflow-ai`
4. Integration neu installieren

Andernfalls funktionieren zukünftige Updates nicht korrekt, da sich die Domain der Integration geändert hat.

---

## Überblick

**Battery SmartFlow AI** ist eine Home-Assistant-Integration zur **stabilen, wirtschaftlichen und transparenten** Steuerung von **Zendure SolarFlow** Batteriesystemen.

Ab Version **1.5.x** kombiniert die Integration:

- ☀️ PV-Erzeugung  
- 🏠 Reale Hauslast (inkl. Batterieanteil)  
- 🔋 Batterie-SoC  
- 💶 Dynamische Strompreise (optional, inkl. Vorplanung)  
- ⚙️ Geräteprofile mit modellabhängiger Regelung  

zu kontextbasierten Lade- und Entladeentscheidungen.

Ziel:

> Nicht maximale Aktivität – sondern maximaler Nutzen.

- Laden, wenn es wirtschaftlich sinnvoll ist  
- Entladen, wenn Netzbezug vermieden werden kann  
- Stillstand, wenn keine Verbesserung möglich ist  
- Keine hektischen Richtungswechsel  

---

# ⚙️ Geräteprofile (ab 1.5.0)

Die Integration nutzt modellabhängige Profile aus `device_profiles.py`.

Aktuell unterstützt:

{% for profile in ["SF800Pro", "SF2400AC"] %}
- **{{ profile }}**
{% endfor %}

Neue Modelle können ergänzt werden, ohne den ConfigFlow anzupassen.  
Die Profilauswahl wird automatisch generiert.

---

# 🧠 Preis-Vorplanung (Price Planning 2.0)

Die Integration analysiert:

- Kommende Preisstruktur
- Relevante Preisspitzen
- Das optimale Lade-Tal davor

## Verbesserungen ab 1.5.x

- Valley-basierte Tal-Erkennung  
- Preis-Toleranz statt Einzel-Slot-Logik  
- Schutz vor Peak-Erkennung in der Vergangenheit  
- Anti-Flutter-Latch  
- Vollständige Ausnutzung des Ladefensters  
- Kein vorzeitiger Abbruch durch nachfolgende Peak-Planung  

Ziel:

> Vor einer Preisspitze vollständig laden –  
aber nur wenn wirtschaftlich sinnvoll.

---

# ⚡ Sehr teure Strompreise

Bei Überschreiten der konfigurierten „Sehr-teuer-Schwelle“:

- Entladung hat höchste Priorität  
- SoC-Reserve wird berücksichtigt  
- Keine Beeinflussung durch PV  
- Keine Instabilität durch Planungswechsel  

---

# 🔄 Netzgeführtes Laden

Die Ladeleistung orientiert sich an der realen Netzbilanz.

Ergebnis:

- Minimale Rest-Einspeisung  
- Kein 1-kW-Dauerexport während Ladevorgängen  
- Verhalten entspricht manuellem Gegenregeln  

---

# Betriebsmodi

## 🔹 Automatik (empfohlen)

- PV-Nutzung  
- Preisplanung aktiv  
- Entladung bei teurem Strom  
- Sehr-teuer-Priorität  

## 🔹 Sommer

- Fokus auf Autarkie  
- Keine Preisplanung  
- Entladung bei Defizit  

## 🔹 Winter

- Fokus auf Wirtschaftlichkeit  
- Preisplanung aktiv  

## 🔹 Manuell

- Keine KI-Eingriffe  
- Laden / Entladen / Standby manuell  

---

# 🛡 Sicherheitsmechanismen

## SoC-Minimum
Kein Entladen unterhalb dieses Wertes.

## SoC-Maximum
Kein Laden oberhalb dieses Wertes.

## SoC-Limit (BMS)
Hardware-Grenzen werden strikt respektiert.

## Fault-Level Sensor
- 0 → Normal  
- 1 → Warnung  
- 2 → Fehler / Schutz aktiv  

---

# 🔧 Hard-Sync mit Hardware

Ab Version 1.5.x folgt die interne Logik strikt dem realen Zendure-AC-Modus:

- INPUT = Laden  
- OUTPUT = Entladen  
- 0 W = Idle  

Keine Software-/Hardware-Abweichungen.

---

# 🧯 Notladefunktion

- Aktivierung bei kritischem SoC  
- Laden bis SoC-Minimum  
- Automatische Freigabe  
- Kein Dauerbetrieb  

---

# ⚠️ Zwingende Voraussetzungen

## 1️⃣ Zendure Original-App

- Lade-/Entladeleistung auf Maximum setzen  
- HEMS deaktivieren  
- Keine parallelen Steuerungen  

Die Steuerung erfolgt ausschließlich über Home Assistant.

---

## 2️⃣ Zendure Home-Assistant Integration

Erforderliche Einstellungen:

- Kein P1-Sensor auswählen  
- Energie-Export: „Erlaubt“  
- Zendure Manager → Betriebsmodus AUS  

Falsche Einstellungen führen zu:

- Entladeabbrüchen  
- Blockierten AC-Modi  
- Falschen Zuständen  

---

## 3️⃣ Strompreis-Integration (optional)

Kompatibel mit:

- Tibber  
- EPEX Spot Integrationen  

---

# Installation (HACS)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=PalmManiac&repository=battery-smartflow-ai&category=integration)

1. HACS öffnen  
2. ⋮ → Benutzerdefinierte Repositories  
3. Repository hinzufügen:  
   `https://github.com/PalmManiac/battery-smartflow-ai`  
4. Typ: Integration  
5. Installieren  
6. Home Assistant neu starten  

---

# 🛣 Roadmap

Version 1.6.x geplant:

- Überarbeitung der Prioritätslogik  
- Planning-Charge-Lock  
- Klare Hierarchie der Entscheidungsquellen  
- Strukturelle Optimierung der State-Maschine  

---

# Support & Mitwirkung

- GitHub Issues für Bugs & Feature-Wünsche  
- Pull Requests willkommen  
- Community-Projekt  

---

**Battery SmartFlow AI – erklärbar, stabil, wirtschaftlich.**
