import io
import os
import re
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font


def _normalize_order_id(val: str) -> str:
    """Extrahiert 'A-1001' deterministisch, auch wenn Zusatztext vorhanden ist."""
    s = str(val or "").strip()
    match = re.search(r"A-\d{3,5}", s, re.IGNORECASE)
    return match.group(0).upper() if match else s.upper()


def validate_vat_calculation(r_doc: dict, default_rate: float = 20.0, calc_missing_vat: bool = False) -> tuple:
    if not r_doc:
        return 0.0, 0.0, 0.0, "Kein Rechnungsbeleg"

    brutto = float(r_doc.get("gesamtbetrag_brutto") or 0.0)
    netto_beleg = float(r_doc.get("betrag_netto") or 0.0)
    mwst_beleg = float(r_doc.get("mwst_betrag") or 0.0)
    satz = float(r_doc.get("mwst_satz_prozent") or default_rate)
    if satz <= 0:
        satz = default_rate

    # Fall 1: Netto und MwSt sind auf dem Beleg gedruckt -> Rechnerische Verprobung
    if netto_beleg > 0 and mwst_beleg > 0 and not r_doc.get("_partial_missing_vat"):
        erwartet_mwst = round(netto_beleg * (satz / 100.0), 2)
        erwartet_brutto = round(netto_beleg + mwst_beleg, 2)
        if abs(erwartet_brutto - brutto) <= 0.05 and abs(erwartet_mwst - mwst_beleg) <= 0.05:
            return netto_beleg, mwst_beleg, satz, f"OK - MwSt ({satz:.0f}%) korrekt ausgewiesen"
        return netto_beleg, mwst_beleg, satz, f"FEHLER - Rechenfehler auf Beleg (Erwartet: {erwartet_mwst:.2f} €)"

    # Fall 2: Nur Brutto auf Beleg vorhanden (oder Teilrechnung ohne MwSt-Ausweis)
    if brutto > 0:
        if calc_missing_vat:
            berechnet_netto = round(brutto / (1.0 + satz / 100.0), 2)
            berechnet_mwst = round(brutto - berechnet_netto, 2)
            return berechnet_netto, berechnet_mwst, satz, f"INFO - Kalkulatorisch ({satz:.0f}%), Ausweis fehlt"
        else:
            return 0.0, 0.0, 0.0, "MANGEL - Kein MwSt-Ausweis auf Beleg (§ 11 UStG)"

    return 0.0, 0.0, 0.0, "Keine Beträge"


def _is_vr_match(auftrag: str, kreditor: str, gezahlt: float, full_text: str, betrag_vr: float) -> bool:
    """Prüft deterministisch, ob ein VR-Thema zu einer Buchung gehört."""
    if auftrag and auftrag != "UNBEKANNT" and auftrag.lower() in full_text:
        return True
    first_word = kreditor.lower().split()[0] if kreditor else ""
    if len(first_word) >= 4 and first_word in full_text:
        return True
    if betrag_vr > 0 and abs(betrag_vr - abs(gezahlt)) < 0.01:
        return True
    return False


def find_vr_link_for_booking(auftrag: str, kreditor: str, gezahlt: float, protokoll_obj) -> str:
    if not protokoll_obj or not getattr(protokoll_obj, "themen_extrakt", None):
        return "Noch kein VR-Protokoll geladen"

    for item in protokoll_obj.themen_extrakt:
        full_text = f"{item.thema_kurz} {item.zusammenfassung_pruefung}".lower()
        betrag_vr = float(item.genannter_betrag_eur or 0.0)
        if _is_vr_match(auftrag, kreditor, gezahlt, full_text, betrag_vr):
            return f"VR-Bezug ({protokoll_obj.sitzungs_nr}): {item.thema_kurz}"

    return "Kein VR-Beschluss gefunden"


def perform_three_way_match(
    df_buchungen: pd.DataFrame,
    extracted_docs: list,
    threshold: float = 12000.0,
    protokoll_obj=None,
    calc_missing_vat: bool = False
) -> pd.DataFrame:
    rechnungen = {}
    lieferscheine = {}

    for d in extracted_docs:
        key = _normalize_order_id(d.get("auftrags_nr", ""))
        if not key or key == "UNBEKANNT":
            continue

        doc_type = str(d.get("dokument_typ", "")).lower()
        if "rechnung" in doc_type or "faktura" in doc_type:
            has_missing_vat = float(d.get("gesamtbetrag_brutto") or 0.0) > 0 and float(d.get("mwst_betrag") or 0.0) == 0.0
            if key not in rechnungen:
                rechnungen[key] = d.copy()
                rechnungen[key]["_partial_missing_vat"] = has_missing_vat
            else:
                rechnungen[key]["betrag_netto"] = round(float(rechnungen[key].get("betrag_netto") or 0.0) + float(d.get("betrag_netto") or 0.0), 2)
                rechnungen[key]["mwst_betrag"] = round(float(rechnungen[key].get("mwst_betrag") or 0.0) + float(d.get("mwst_betrag") or 0.0), 2)
                rechnungen[key]["gesamtbetrag_brutto"] = round(float(rechnungen[key].get("gesamtbetrag_brutto") or 0.0) + float(d.get("gesamtbetrag_brutto") or 0.0), 2)
                rechnungen[key]["dateiname"] = f"{rechnungen[key]['dateiname']}, {d['dateiname']}"
                if has_missing_vat:
                    rechnungen[key]["_partial_missing_vat"] = True
        elif "lieferschein" in doc_type or "warenbegleitschein" in doc_type:
            if key not in lieferscheine:
                lieferscheine[key] = d.copy()
            else:
                lieferscheine[key]["dateiname"] = f"{lieferscheine[key]['dateiname']}, {d['dateiname']}"

    results = []
    for _, row in df_buchungen.iterrows():
        auftrag = _normalize_order_id(row["auftrag_nr"])
        kreditor = str(row["kreditor"]).strip()
        gezahlt = float(row["betrag_gezahlt"])

        r_doc = rechnungen.get(auftrag)
        l_doc = lieferscheine.get(auftrag)

        r_betrag = float(r_doc.get("gesamtbetrag_brutto") or 0.0) if r_doc else 0.0
        r_file = r_doc.get("dateiname") if r_doc else "FEHLT"
        l_file = l_doc.get("dateiname") if l_doc else "FEHLT"

        netto, mwst, satz, mwst_check = validate_vat_calculation(r_doc, calc_missing_vat=calc_missing_vat)
        ist_wesentlich = max(abs(gezahlt), abs(r_betrag)) >= threshold
        materialitaet = "WESENTLICH" if ist_wesentlich else "Unwesentlich"

        if r_doc and l_doc:
            if abs(gezahlt - r_betrag) < 0.01:
                status = "OK - 3-Way-Match erfolgreich"
                differenz = 0.0
            else:
                status = "ABWEICHUNG - Betragsdifferenz"
                differenz = gezahlt - r_betrag
        elif not r_doc and not l_doc:
            status = "KRITISCH - Keine Belege vorhanden"
            differenz = gezahlt
        else:
            status = "UNVOLLSTÄNDIG - Teilbelege fehlen"
            differenz = gezahlt - r_betrag

        vr_ref = find_vr_link_for_booking(auftrag, kreditor, gezahlt, protokoll_obj)

        results.append({
            "Auftrag_Nr": auftrag,
            "Buchungsdatum": row["datum"],
            "Kreditor": kreditor,
            "Materialitaet": materialitaet,
            "Gezahlt_Brutto_EUR": round(gezahlt, 2),
            "Rechnung_Netto_EUR": round(netto, 2),
            "MwSt_Satz_%": round(satz, 2),
            "MwSt_Betrag_EUR": round(mwst, 2),
            "Rechnung_Brutto_EUR": round(r_betrag, 2),
            "MwSt_Rechen_Check": mwst_check,
            "Differenz_EUR": round(differenz, 2),
            "Match_Status": status,
            "VR_Protokoll_Referenz": vr_ref,
            "Ref_Rechnung_PDF": r_file,
            "Ref_Lieferschein_PDF": l_file,
            "Risiko_Hinweis": row.get("Risiko_Hinweis", "")
        })

    return pd.DataFrame(results)


def build_vr_dataframe(protokoll_obj, threshold: float = 12000.0, df_buchungen: pd.DataFrame = None) -> pd.DataFrame:
    rows = []
    for item in protokoll_obj.themen_extrakt:
        betrag = round(float(item.genannter_betrag_eur or 0.0), 2)
        wesentlich = "WESENTLICH" if abs(betrag) >= threshold else "Unwesentlich"
        full_text = f"{item.thema_kurz} {item.zusammenfassung_pruefung}".lower()

        verknuepfte_buchung = "Keine Buchung in CSV (z.B. Rückstellung/Risiko)"
        if df_buchungen is not None and not df_buchungen.empty:
            for _, b_row in df_buchungen.iterrows():
                auftrag = _normalize_order_id(b_row["auftrag_nr"])
                kreditor = str(b_row["kreditor"]).strip()
                gezahlt = float(b_row["betrag_gezahlt"])
                if _is_vr_match(auftrag, kreditor, gezahlt, full_text, betrag):
                    verknuepfte_buchung = f"Verknüpft mit Buchung {auftrag} ({kreditor})"
                    break

        rows.append({
            "Sitzung_Nr": protokoll_obj.sitzungs_nr,
            "Datum": protokoll_obj.datum,
            "Thema_Beschluss": item.thema_kurz,
            "Zusammenfassung_Pruefungsunterlagen": item.zusammenfassung_pruefung,
            "Betrag_Streitwert_EUR": betrag,
            "Materialitaet_Bewertung": wesentlich,
            "Verknuepfte_Buchung_3Way": verknuepfte_buchung,
            "Pruefungs_Pflicht": "JA - In Prüfungsakte aufnehmen" if wesentlich == "WESENTLICH" else "Nein (Unwesentlich)"
        })
    return pd.DataFrame(rows)


def _style_worksheet(ws, df: pd.DataFrame, abs_pdf_folder: str):
    headers = list(df.columns)
    ws.append(headers)

    header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    ok_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    yellow_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    warn_fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
    info_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    link_font = Font(color="0563C1", underline="single")

    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font

    for row_idx, row in df.iterrows():
        excel_row = row_idx + 2
        for col_idx, value in enumerate(row, start=1):
            cell = ws.cell(row=excel_row, column=col_idx, value=value)
            col_name = headers[col_idx - 1]
            s_val = str(value)

            if isinstance(value, float):
                cell.number_format = "#,##0.00"

            if col_name in ["Match_Status", "MwSt_Rechen_Check"]:
                if "OK" in s_val:
                    cell.fill = ok_fill
                elif any(w in s_val for w in ["UNVOLLSTÄNDIG", "INFO", "MANGEL"]):
                    cell.fill = yellow_fill
                else:
                    cell.fill = warn_fill
            elif col_name in ["Materialitaet", "Materialitaet_Bewertung"]:
                cell.fill = warn_fill if value == "WESENTLICH" else ok_fill
            elif col_name in ["VR_Protokoll_Referenz", "Verknuepfte_Buchung_3Way"]:
                if "VR-Bezug" in s_val or "Verknüpft mit Buchung" in s_val:
                    cell.fill = info_fill

            if col_name in ["Ref_Rechnung_PDF", "Ref_Lieferschein_PDF"] and value != "FEHLT":
                first_pdf = s_val.split(",")[0].strip()
                full_pdf_path = os.path.join(abs_pdf_folder, first_pdf)
                if os.path.exists(full_pdf_path):
                    cell.hyperlink = f"file:///{full_pdf_path}"
                    cell.font = link_font
                cell.value = f"Siehe Beleg: {value}"

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = max(max_len + 3, 12)


def export_audit_excel(df_match: pd.DataFrame, df_vr: pd.DataFrame = None, pdf_folder_path: str = "sample_data/pdfs") -> bytes:
    wb = Workbook()
    abs_pdf_folder = os.path.abspath(pdf_folder_path)

    ws1 = wb.active
    ws1.title = "1_3WayMatch_MwSt_Materialitaet"
    if df_match is not None and not df_match.empty:
        _style_worksheet(ws1, df_match, abs_pdf_folder)

    if df_vr is not None and not df_vr.empty:
        ws2 = wb.create_sheet(title="2_VR_Protokoll_Pruefungsakte")
        _style_worksheet(ws2, df_vr, abs_pdf_folder)

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()