# Kapitel 1

# Was macht Battery SmartFlow AI?

**Battery SmartFlow AI** ist eine Home-Assistant-Integration zur intelligenten Steuerung von Zendure SolarFlow Batteriesystemen.

Sie verbindet Batterie, Photovoltaik, Hausverbrauch und – optional – dynamische Strompreise zu einem gemeinsamen Gesamtsystem.

Auf Basis dieser Informationen entscheidet die Integration automatisch:

- wann geladen wird  
- wann entladen wird  
- wie stark geladen oder entladen wird  
- wann Stillstand sinnvoller ist  

Das Ziel ist nicht maximale Aktivität, sondern ein ausgewogenes Zusammenspiel aus:

- Wirtschaftlichkeit  
- Netzstabilität  
- Autarkie  
- technischer Sicherheit  

Battery SmartFlow AI arbeitet vollständig transparent:  
Jede Entscheidung kann über Sensoren in Home Assistant nachvollzogen werden.

Die Integration greift nicht blind ein –  
sie bewertet kontinuierlich die aktuelle Situation und reagiert nur dann, wenn eine Verbesserung möglich ist.

> Das Ergebnis: geringere Stromkosten, saubere Netzbilanz und nachvollziehbares Systemverhalten.

# Kapitel 2 – Zwingende Voraussetzungen

Damit Battery SmartFlow AI korrekt und stabil arbeiten kann, müssen bestimmte Einstellungen zwingend beachtet werden.

Die Integration übernimmt die vollständige Steuerung des Zendure-Systems.  
Parallele oder widersprüchliche Steuerungen führen zu Instabilität.

---

## 1️⃣ Zendure Original-App

In der offiziellen Zendure-App müssen folgende Punkte geprüft werden:

- Ladeleistung auf Maximum setzen  
- Entladeleistung auf Maximum setzen  
- HEMS deaktivieren  
- Keine zeitgesteuerten Lade-/Entladepläne aktiv  
- Keine externe Leistungsbegrenzung aktiv  

### ⚠ Hardwareliste prüfen (sehr wichtig)

In der Zendure-App darf sich in der **Hardwareliste ausschließlich der Wechselrichter bzw. die Zendure-Hardware selbst** befinden.

Es dürfen **keine zusätzlichen Geräte** eingebunden sein, wie zum Beispiel:

- Shelly Pro 3EM  
- externe Smart Meter / Zähler  
- Zendure eigene Messsensoren  
- sonstige Leistungs- oder Netzsensoren  

Externe Messgeräte oder interne HEMS-Komponenten beeinflussen das Regelverhalten des Systems und führen zu unvorhersehbaren Eingriffen (z. B. blockierte AC-Modi, Leistungsbegrenzungen oder Richtungswechsel).

Battery SmartFlow AI benötigt eine „saubere“ Hardwarekonfiguration ohne parallele Steuerinstanzen.

---

## 2️⃣ Zendure Home-Assistant Integration

Folgende Einstellungen sind erforderlich:

- Energie-Export: **Erlaubt**  
- Kein P1-Sensor auswählen  
- Zendure Manager: **deaktiviert**  
- Keine parallelen Automationen, die AC-Modus oder Leistungsgrenzen verändern  

Falsche Einstellungen können führen zu:

- Entladeabbrüchen  
- blockierten AC-Modi  
- Wechsel zwischen INPUT/OUTPUT  
- falschen Zuständen / Fehlinterpretationen  

---

## 3️⃣ Strompreis-Integration (optional)

Für preisbasierte Planung ist eine kompatible Strompreis-Integration erforderlich.

Unterstützt werden unter anderem:

- Tibber  
- EPEX Spot Integrationen  
- Octopus (inkl. Forecast-Attribute)  

Ohne Preisdaten arbeitet die Integration weiterhin PV- und lastbasiert, jedoch ohne Preisoptimierung.

---

## Wichtig

Wenn das System nicht wie erwartet arbeitet, sollten zuerst diese Voraussetzungen überprüft werden.

In den meisten Fällen liegt die Ursache in widersprüchlichen Einstellungen außerhalb der Integration.

# Kapitel 3 – Installation

Battery SmartFlow AI wird über HACS (Home Assistant Community Store) installiert.

Es gibt zwei Möglichkeiten:

---

## 🚀 Schnellinstallation (empfohlen)

Über folgenden Button kann das Repository direkt in HACS geöffnet werden:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=PalmManiac&repository=battery-smartflow-ai&category=integration)

Nach dem Öffnen:

1. Repository hinzufügen  
2. Integration installieren  

---

## 🔧 Manuelle Installation über HACS

Falls der Direktlink nicht genutzt wird:

1. HACS öffnen  
2. ⋮ → **Benutzerdefinierte Repositories**  
3. Repository-URL einfügen:  
   `https://github.com/PalmManiac/battery-smartflow-ai`  
4. Typ: **Integration** auswählen  
5. Hinzufügen bestätigen  

Anschließend:

1. In HACS nach **Battery SmartFlow AI** suchen  
2. Installieren  

---

## 🔄 Neustart erforderlich

Nach der Installation muss Home Assistant neu gestartet werden.

Erst nach dem Neustart steht die Integration unter  
**Einstellungen → Geräte & Dienste → Integration hinzufügen**  
zur Verfügung.
