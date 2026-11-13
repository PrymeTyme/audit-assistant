import re
import fitz
from pydantic import BaseModel, Field
from typing import List, Literal
import ollama
from rapidocr_onnxruntime import RapidOCR

ocr_engine = RapidOCR()


class BelegDaten(BaseModel):
    dokument_typ: Literal["Rechnung", "Lieferschein", "Sonstiges"] = Field(
        description="Zwingend 'Rechnung', 'Lieferschein' oder 'Sonstiges' (nur bei Protokollen/Verträgen)."
    )
    beleg_nr: str = Field(description="Rechnungsnummer (z.B. R-2025-101) oder Lieferscheinnummer (z.B. LS-501)")
    auftrags_nr: str = Field(description="Zugehörige Auftragsnummer (z.B. A-1001, A-1002, A-1004)")
    datum: str = Field(description="Datum im Format YYYY-MM-DD")
    lieferant_oder_kunde: str = Field(description="Name der ausstellenden Firma")
    betrag_netto: float = Field(description="Nettobetrag ohne Steuer als Zahl (z.B. 1000.0). Bei Lieferschein 0.0")
    mwst_satz_prozent: float = Field(description="MwSt/USt-Satz in Prozent als Zahl (z.B. 20.0). Bei Lieferschein 0.0")
    mwst_betrag: float = Field(description="MwSt/USt-Betrag in EUR als Zahl (z.B. 200.0). Bei Lieferschein 0.0")
    gesamtbetrag_brutto: float = Field(description="Gesamtbetrag/Endbetrag Brutto inkl. MwSt als Zahl (z.B. 1200.0). Bei Lieferschein 0.0")
    artikel_liste: List[str] = Field(description="Liste der gelieferten oder berechneten Positionen")


class VRThema(BaseModel):
    thema_kurz: str = Field(description="Kurzer Titel des Themas oder Beschlusses")
    zusammenfassung_pruefung: str = Field(description="Zusammenfassung für die Prüfungsunterlagen")
    genannter_betrag_eur: float = Field(description="Genannter Euro-Betrag oder Streitwert zu diesem Thema (0.0 falls kein Betrag genannt)")


class VRProtokoll(BaseModel):
    sitzungs_nr: str = Field(description="Nummer des Protokolls oder der Sitzung")
    datum: str = Field(description="Datum der Sitzung im Format YYYY-MM-DD")
    anwesende: List[str] = Field(description="Liste der anwesenden Personen")
    themen_extrakt: List[VRThema] = Field(description="Liste aller besprochenen Themen, Beschlüsse und Risiken inkl. Betrag")


def _to_float(num_str: str) -> float:
    """Wandelt '1.200,00', '15.000' oder '1200.00' sicher in Float um."""
    s = num_str.strip()
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if s.count(",") > 1 or re.match(r"^\d{1,3},\d{3}$", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif "." in s:
        if s.count(".") > 1 or re.match(r"^\d{1,3}\.\d{3}$", s):
            s = s.replace(".", "")
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def _extract_amounts_from_text(raw_text: str) -> tuple[float, float, float, float]:
    """
    Deterministischer Python-Parser für den exakten IST-Zustand auf dem Beleg.
    Filtert vorab Prozentsätze, Daten und IDs heraus, damit '20%' niemals als 20,00 € gelesen wird.
    """
    netto, satz, mwst, brutto = 0.0, 0.0, 0.0, 0.0

    for line in raw_text.splitlines():
        line_l = line.lower()

        # 1. Steuersatz (z.B. '20%' oder '20 %') vorab sichern
        pct_match = re.search(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", line_l)
        if pct_match and any(k in line_l for k in ["mwst", "ust", "steuer"]):
            satz = _to_float(pct_match.group(1))

        # 2. Störzahlen (Prozente, Datum, Auftrags-/Rechnungs-IDs) aus der Zeile entfernen
        clean_line = re.sub(r"\d{1,2}(?:[.,]\d{1,2})?\s*%", " ", line)
        clean_line = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{2}\.\d{2}\.\d{4}\b", " ", clean_line)
        clean_line = re.sub(r"\b[A-Za-z]+-[\d-]+\b", " ", clean_line)

        nums = re.findall(r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b|\b\d+\b", clean_line)
        floats = [_to_float(n) for n in nums if _to_float(n) > 0]

        if not floats:
            continue

        val = floats[-1]

        # 3. Zuordnung nach Schlüsselwörtern
        if any(k in line_l for k in ["brutto", "endbetrag", "gesamtbetrag", "zahlbetrag", "zu zahlen", "inkl"]):
            brutto = val
        elif any(k in line_l for k in ["mwst", "ust", "mehrwertsteuer", "umsatzsteuer"]) and "inkl" not in line_l:
            mwst = val
        elif any(k in line_l for k in ["netto", "zwischensumme"]) and "inkl" not in line_l:
            netto = val

    return netto, satz, mwst, brutto


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if len(doc) == 0:
                raise ValueError("Die PDF-Datei enthält keine Seiten.")

            full_text = ""
            for page in doc:
                page_text = page.get_text().strip()
                if len(page_text) > 20:
                    full_text += page_text + "\n"
                else:
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    ocr_result, _ = ocr_engine(pix.tobytes("png"))
                    if ocr_result:
                        full_text += "\n".join([line[1] for line in ocr_result]) + "\n"
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Ungültige oder beschädigte PDF-Datei: {e}")

    if len(full_text.strip()) < 10:
        raise ValueError("Kein lesbarer Text im PDF gefunden.")
    return full_text


def parse_beleg_with_ollama(pdf_bytes: bytes, model_name: str = "llama3.1") -> BelegDaten:
    raw_text = extract_text_from_pdf(pdf_bytes)
    text_lower = raw_text.lower()

    # 1. Protokolle sofort OHNE LLM abweisen
    protokoll_keywords = ["verwaltungsratsprotokoll", "sitzungsprotokoll", "tagesordnung", "anwesende mitglieder"]
    if any(k in text_lower for k in protokoll_keywords):
        return BelegDaten(
            dokument_typ="Sonstiges",
            beleg_nr="Kein Beleg (Protokoll)",
            auftrags_nr="Unbekannt",
            datum="",
            lieferant_oder_kunde="Unbekannt",
            betrag_netto=0.0,
            mwst_satz_prozent=0.0,
            mwst_betrag=0.0,
            gesamtbetrag_brutto=0.0,
            artikel_liste=[]
        )

    # 2. LLM-Extraktion
    prompt = f"""
    Du bist ein Wirtschaftsprüfungs-Assistent. Extrahiere die Belegdaten aus dem Text.
    WICHTIG bei Rechnungen: Lies 'betrag_netto' (z.B. 1000.0), 'mwst_satz_prozent' (z.B. 20.0), 
    'mwst_betrag' (z.B. 200.0) und 'gesamtbetrag_brutto' (z.B. 1200.0) exakt als Zahl aus!
    Falls auf einer Rechnung nur der Bruttobetrag mit 'inkl. USt' ohne separaten MwSt-Betrag steht,
    setze betrag_netto und mwst_betrag auf 0.0.
    
    Dokumententext:
    {raw_text}
    """
    try:
        response = ollama.chat(
            model=model_name,
            messages=[{'role': 'user', 'content': prompt}],
            format=BelegDaten.model_json_schema(),
            options={'temperature': 0}
        )
        parsed = BelegDaten.model_validate_json(response['message']['content'])
    except Exception as e:
        raise RuntimeError(f"Lokale KI ({model_name}) Fehler: {e}")

    # 3. Deterministische Nachkontrolle in Python
    order_match = re.search(r"\bA-\d{3,5}\b", raw_text, re.IGNORECASE)
    if order_match:
        parsed.auftrags_nr = order_match.group(0).upper()
    else:
        parsed.auftrags_nr = str(parsed.auftrags_nr or "Unbekannt").strip().upper()

    if "lieferschein" in text_lower or "warenbegleitschein" in text_lower:
        parsed.dokument_typ = "Lieferschein"
        parsed.betrag_netto = 0.0
        parsed.mwst_satz_prozent = 0.0
        parsed.mwst_betrag = 0.0
        parsed.gesamtbetrag_brutto = 0.0
        return parsed

    parsed.dokument_typ = "Rechnung"

    # Einmaliger Aufruf des deterministischen Python-Parsers
    py_netto, py_satz, py_mwst, py_brutto = _extract_amounts_from_text(raw_text)

    if py_brutto > 0:
        parsed.gesamtbetrag_brutto = round(py_brutto, 2)
        parsed.betrag_netto = round(py_netto, 2)
        parsed.mwst_betrag = round(py_mwst, 2)
        parsed.mwst_satz_prozent = round(py_satz, 2)
    else:
        parsed.betrag_netto = round(float(parsed.betrag_netto or 0.0), 2)
        parsed.mwst_betrag = round(float(parsed.mwst_betrag or 0.0), 2)
        parsed.gesamtbetrag_brutto = round(float(parsed.gesamtbetrag_brutto or 0.0), 2)
        parsed.mwst_satz_prozent = round(float(parsed.mwst_satz_prozent or 0.0), 2)

    return parsed


def parse_protokoll_with_ollama(pdf_bytes: bytes, model_name: str = "llama3.1") -> VRProtokoll:
    raw_text = extract_text_from_pdf(pdf_bytes)
    text_lower = raw_text.lower()

    protokoll_merkmale = ["protokoll", "sitzung", "tagesordnung", "beschlüsse", "beschluesse", "anwesend"]
    if not any(k in text_lower for k in protokoll_merkmale):
        raise ValueError(
            "Kein gültiges Verwaltungsratsprotokoll erkannt! Falls es sich um eine Rechnung oder einen Lieferschein handelt, bitte in Tab 2 hochladen."
        )

    prompt = f"""
    Du bist ein Wirtschaftsprüfer. Analysiere dieses Verwaltungsratsprotokoll.
    Zerlege alle Tagesordnungspunkte, Beschlüsse und Risiken in einzelne Themen-Blöcke (themen_extrakt)
    für die Prüfungsunterlagen und extrahiere zu jedem Punkt den genannten Geldbetrag in EUR (z.B. 1200, 15000, 45000).
    
    Protokolltext:
    {raw_text}
    """
    try:
        response = ollama.chat(
            model=model_name,
            messages=[{'role': 'user', 'content': prompt}],
            format=VRProtokoll.model_json_schema(),
            options={'temperature': 0}
        )
        return VRProtokoll.model_validate_json(response['message']['content'])
    except Exception as e:
        raise RuntimeError(f"Lokale KI ({model_name}) konnte das Protokoll nicht verarbeiten: {e}")