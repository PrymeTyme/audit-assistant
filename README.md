#  KI-gestützter Audit- & 3-Way-Matching-Assistent (On-Premise)

Ein lokal ausführbarer Prototyp für die Wirtschaftsprüfung und Steuerberatung zur automatisierten **Belegverprobung (3-Way-Match)**, **USt-Prüfung nach § 11 UStG**, **Materialitätsanalyse** und **Auswertung von Verwaltungsratsprotokollen**.

Entwickelt mit Fokus auf **100 % Datenschutz & Kanzleiverschwiegenheit**: Alle Berechnungen, OCR-Scans und KI-Extraktionen laufen vollständig lokal über **Ollama** – kein einziges Mandantendokument verlässt das System.

---

## Kernfunktionen im Prüfungsprozess

###  CSV-Journal-Mapping & Risikoanalyse (Tab 1)
* **BMD/Klienten-Import:** Automatische Normalisierung deutscher und internationaler Währungs- und Datumsformate.
* **Dynamische Wesentlichkeitsgrenze:** Einstufung aller Buchungen nach frei definierbarer Materialitätsschwelle (z. B. `>= 12.000 €` → `WESENTLICH`).
* **Fraud- & Risiko-Indikatoren:** Automatische Markierung von Wochenendbuchungen und fehlenden Buchungsdaten.

###  Hybrid-KI 3-Way-Match & § 11 UStG Rechencheck (Tab 2)
* **Hybride Extraktions-Pipeline (Python + LLM + OCR):** Kombination aus `PyMuPDF`, `RapidOCR` (für gescannte Belege), `Llama 3.1` (via Ollama/Pydantic) und deterministischer Python-Nachkontrolle.
* **Automatisierter 3-Way-Match:** Abgleich von Buchungsjournal (CSV), Eingangsrechnung (PDF) und Lieferschein (PDF) anhand normalisierter Auftragsreferenzen.
* **Formale & rechnerische MwSt-Verprobung:**
  * Trennt strikt zwischen *Beleg-Ist-Zustand* und *kalkulatorischer Nachberechnung*.
  * Deckt fehlende Steuerausweise (z. B. *„inkl. USt“* ohne Betragsausweis bei Rechnungen > 400 € gem. § 11 UStG) als `MANGEL` auf.
  * Optionaler Prüfer-Toggle zur kalkulatorischen Herausrechnung der USt unter Beibehaltung des Prüfungsvermerks.
* **In-App Beleg-Inspektor (DataSnipper-Style):** Direktes Anklicken einer Buchungszeile öffnet die verknüpften PDF-Belege und hebt Auftragsnummer sowie Bruttobetrag im Dokument farblich hervor.

###  VR-Protokoll-Extrakt & Cross-Referenzierung (Tab 3)
* **Strukturierte Sitzungsauswertung:** Zerlegt mehrseitige Verwaltungsratsprotokolle in einzelne Beschlüsse, Risiken und Streitwerte.
* **Bidirektionales Cross-Linking:** Verknüpft genehmigte Investitionen oder Rückstellungen aus dem VR-Protokoll automatisch rückwärts mit den tatsächlichen Buchungen im 3-Way-Match.

### Export für die Prüfungsakte
* Generiert per Klick eine formatierte **Excel-Prüfakte (`.xlsx`)** mit zwei Arbeitsblättern (*3-Way-Match* & *VR-Extrakt*), Ampel-Farbcodierung und direkten Dateiverknüpfungen zu den geprüften PDF-Belegen.

---

## Tech-Stack & Architektur

* **Frontend & UI:** Streamlit (Interaktive Dataframes, Live-PDF-Highlighting)
* **Lokale KI / LLM:** Ollama (`llama3.1` / `mistral` / `qwen2.5`) mit strikter JSON-Schema-Validierung via `Pydantic`
* **PDF & OCR:** `PyMuPDF (fitz)`, `RapidOCR (ONNX Runtime)`, `Pillow`
* **Datenverarbeitung & Export:** `Pandas`, `OpenPyXL`

### Architektur-Prinzip: Determinismus vor Probabilistik
Um LLM-Halluzinationen bei Zahlen auszuschließen, arbeitet das System zweistufig:
1. **Vorab-Klassifizierung:** Python-Filter blockieren falsch hochgeladene Dokumenttypen (z. B. Protokoll in Rechnungs-Tab) in 0 ms vor dem LLM-Aufruf.
2. **Mathematisches Veto-Recht:** Regex-basierte Betrags- und Referenzextraktion überprüft und korrigiert die LLM-Ausgabe deterministisch.

---