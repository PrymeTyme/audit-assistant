import io
import ollama
import fitz
from PIL import Image, ImageDraw
from rapidocr_onnxruntime import RapidOCR
import streamlit as st
import pandas as pd
from modules.mapper import clean_and_map_csv, run_risk_analysis
from modules.doc_parser import parse_beleg_with_ollama, parse_protokoll_with_ollama
from modules.matcher import perform_three_way_match, build_vr_dataframe, export_audit_excel


@st.cache_resource
def get_ocr_engine():
    return RapidOCR()


# Getrennte Reset-Zähler pro Tab (verhindert, dass Tab 2 den Upload von Tab 1 löscht)
for key in ["rc_tab1", "rc_tab2", "rc_tab3"]:
    if key not in st.session_state:
        st.session_state[key] = 0


def reset_all():
    st.session_state["rc_tab1"] += 1
    st.session_state["rc_tab2"] += 1
    st.session_state["rc_tab3"] += 1
    for k in ["df_clean", "df_buchungen", "pdf_store", "extracted_docs", "df_match", "skipped_docs", "protokoll_meta", "df_vr"]:
        st.session_state.pop(k, None)


def reset_tab1():
    for k in ["df_clean", "df_buchungen", "df_match"]:
        st.session_state.pop(k, None)
    st.session_state["rc_tab1"] += 1


def reset_tab2():
    for k in ["pdf_store", "extracted_docs", "df_match", "skipped_docs"]:
        st.session_state.pop(k, None)
    st.session_state["rc_tab2"] += 1


def reset_tab3():
    for k in ["protokoll_meta", "df_vr"]:
        st.session_state.pop(k, None)
    st.session_state["rc_tab3"] += 1


@st.cache_data(show_spinner=False)
def render_pdf_page_with_highlights(pdf_bytes: bytes, search_terms: tuple = ()) -> bytes:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    terms = [str(t).strip() for t in (search_terms or ()) if t and str(t).strip()]

    if len(page.get_text().strip()) > 20:
        for term in terms:
            for quad in page.search_for(term):
                annot = page.add_highlight_annot(quad)
                annot.update()
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        return pix.tobytes("png")

    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    img_bytes = pix.tobytes("png")
    if not terms:
        return img_bytes

    ocr_result, _ = get_ocr_engine()(img_bytes)
    if not ocr_result:
        return img_bytes

    base_img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    overlay = Image.new("RGBA", base_img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    for item in ocr_result:
        box, detected_text, _ = item
        if any(term.lower() in detected_text.lower() for term in terms):
            polygon = [(float(pt[0]), float(pt[1])) for pt in box]
            draw.polygon(polygon, fill=(255, 235, 0, 95), outline=(230, 180, 0, 220))

    combined = Image.alpha_composite(base_img, overlay).convert("RGB")
    out = io.BytesIO()
    combined.save(out, format="PNG")
    return out.getvalue()


def style_and_format_df(df: pd.DataFrame):
    def highlight_cells(val):
        s = str(val)
        if s == "WESENTLICH" or "KRITISCH" in s or "ABWEICHUNG" in s or "FEHLER" in s:
            return "background-color: #FCE4D6; color: #78281F; font-weight: bold;"
        if "UNVOLLSTÄNDIG" in s or "INFO -" in s or "MANGEL" in s:
            return "background-color: #FFF2CC; color: #7D6608;"
        if s == "Unwesentlich" or "OK -" in s:
            return "background-color: #E2EFDA; color: #145A32;"
        if "VR-Bezug" in s or "Verknüpft mit Buchung" in s:
            return "background-color: #D9E1F2; color: #1F4E78; font-weight: bold;"
        if s.endswith(".pdf"):
            return "color: #0563C1; text-decoration: underline; font-weight: bold;"
        return ""

    target_cols = [
        c for c in [
            "Materialitaet", "Materialitaet_Bewertung", "Match_Status",
            "MwSt_Rechen_Check", "VR_Protokoll_Referenz", "Verknuepfte_Buchung_3Way",
            "Ref_Rechnung_PDF", "Ref_Lieferschein_PDF"
        ] if c in df.columns
    ]

    num_cols = {col: "{:,.2f}" for col in df.select_dtypes(include=["float", "int"]).columns}
    return df.style.format(num_cols).map(highlight_cells, subset=target_cols)


st.set_page_config(page_title="SPT KI-Audit & 3-Way-Match", layout="wide")

col_title, col_reset = st.columns([5, 1], vertical_alignment="center")
with col_title:
    st.title("🛡️ KI-gestützter Audit- & 3-Way-Matching-Assistent")
    st.caption("100 % lokale & DSGVO-konforme Belegprüfung, MwSt-Verprobung, Materialitäts-Check & VR-Extrakt")
with col_reset:
    if st.button("🗑️ Alles zurücksetzen", width="stretch"):
        reset_all()
        st.rerun()


with st.container(border=True):
    col_p1, col_p2, col_p3 = st.columns([1.4, 2.6, 1.2], vertical_alignment="center")

    with col_p1:
        threshold = st.number_input(
            "🎯 Wesentlichkeitsgrenze (€)",
            value=12000.0,
            step=1000.0,
            help="Beträge ab dieser Grenze werden automatisch für die Prüfungsakte markiert."
        )

    with col_p2:
        st.markdown(
            f"""
            <div style="text-align: center; padding-top: 14px; font-size: 0.92rem;">
                <b>Aktive Regel:</b> Ab <b>{threshold:,.0f} €</b> → 
                <span style="background-color: #FADBD8; color: #78281F; padding: 2px 6px; border-radius: 4px; font-weight: bold;">WESENTLICH</span>
                &nbsp;|&nbsp; Darunter → 
                <span style="background-color: #D4EFDF; color: #145A32; padding: 2px 6px; border-radius: 4px;">Unwesentlich</span>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col_p3:
        try:
            installed_models = [m.model for m in ollama.list().models]
        except Exception:
            installed_models = ["llama3.1"]

        model_name = st.selectbox(
            "🤖 KI-Modell (Lokal)",
            options=installed_models or ["llama3.1"]
        )

tab1, tab2, tab3 = st.tabs([
    "1️⃣ CSV-Mapping & Materialität",
    "2️⃣ 3-Way-Match & MwSt-Rechencheck",
    "3️⃣ VR-Protokoll Extrakt (Prüfungsakte)"
])

# TAB 1: CSV-Mapping & Materialität
with tab1:
    col_t1_head, col_t1_rst = st.columns([4, 1], vertical_alignment="center")
    with col_t1_head:
        st.subheader(f"Klienten-Buchungsexport importieren & nach Materialität ({threshold:,.0f} €) einstufen")

    csv_file = st.file_uploader(
        "Buchungsexport (CSV) hochladen",
        type=["csv"],
        key=f"csv_up_{st.session_state['rc_tab1']}"
    )

    with col_t1_rst:
        if csv_file or "df_clean" in st.session_state:
            if st.button("🔄 CSV zurücksetzen", width="stretch", key="btn_rst_t1"):
                reset_tab1()
                st.rerun()

    if not csv_file and "df_clean" in st.session_state:
        st.session_state.pop("df_clean", None)
        st.session_state.pop("df_buchungen", None)

    if csv_file:
        mapping = {
            "Ref_Auftrag": "auftrag_nr",
            "Gezahlter_Betrag_EUR": "betrag_gezahlt",
            "Buchungsdatum_Klient": "datum",
            "Kreditor_Name": "kreditor"
        }
        try:
            df_clean = clean_and_map_csv(csv_file, mapping)
            st.session_state["df_clean"] = df_clean
        except Exception as e:
            st.error(f"❌ **Fehler in der CSV-Datei:** {e}")
            st.session_state.pop("df_clean", None)

    if "df_clean" in st.session_state:
        df_risk = run_risk_analysis(st.session_state["df_clean"], threshold=threshold)
        st.session_state["df_buchungen"] = df_risk

        wesentlich_count = int((df_risk["Materialitaet"] == "WESENTLICH").sum())
        m1, m2, m3 = st.columns(3)
        m1.metric("Geprüfte Buchungen", len(df_risk))
        m2.metric("Davon WESENTLICH (>= Grenze)", wesentlich_count)
        m3.metric("Davon Unwesentlich", len(df_risk) - wesentlich_count)

        with st.expander("📋 Bereinigte Buchungsdaten & Risiko-Einstufung (Ein-/Ausklappen)", expanded=True):
            st.dataframe(style_and_format_df(df_risk), width="stretch")

# TAB 2: KI-Belegparser, MwSt-Check & 3-Way-Match
with tab2:
    col_t2_head, col_t2_rst = st.columns([4, 1], vertical_alignment="center")
    with col_t2_head:
        st.subheader("PDF-Belege (inkl. MwSt-Separierung & Nachberechnung) mit Buchungen abgleichen")

    pdf_files = st.file_uploader(
        "Rechnungen & Lieferscheine (PDF) hochladen",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"pdf_up_{st.session_state['rc_tab2']}"
    )

    with col_t2_rst:
        if pdf_files or "extracted_docs" in st.session_state or "skipped_docs" in st.session_state:
            if st.button("🔄 Belege zurücksetzen", width="stretch", key="btn_rst_t2"):
                reset_tab2()
                st.rerun()

    if st.button("🚀 KI-Extraktion, MwSt-Check & 3-Way-Match starten") and pdf_files:
        if "df_buchungen" not in st.session_state:
            st.error("⚠️ Bitte zuerst in Tab 1 den CSV-Buchungsexport hochladen!")
        else:
            extracted_docs = []
            skipped_docs = []
            pdf_store = {}
            progress = st.progress(0)

            for idx, pdf in enumerate(pdf_files):
                try:
                    raw_bytes = pdf.getvalue()
                    with st.spinner(f"Analysiere {pdf.name} (inkl. Netto/MwSt/Brutto-Split)..."):
                        parsed = parse_beleg_with_ollama(raw_bytes, model_name=model_name)
                        doc_dict = parsed.model_dump()
                        doc_dict["dateiname"] = pdf.name

                        if doc_dict["dokument_typ"] == "Sonstiges":
                            skipped_docs.append(
                                f"**{pdf.name}**: Übersprungen – kein Rechnungs-/Lieferscheinbeleg erkannt ({doc_dict['beleg_nr']})."
                            )
                        else:
                            pdf_store[pdf.name] = raw_bytes
                            extracted_docs.append(doc_dict)
                except Exception as e:
                    skipped_docs.append(f"**{pdf.name}**: Fehler bei der Verarbeitung ({e})")

                progress.progress((idx + 1) / len(pdf_files))

            st.session_state["pdf_store"] = pdf_store
            st.session_state["extracted_docs"] = extracted_docs
            st.session_state["skipped_docs"] = skipped_docs

    if st.session_state.get("skipped_docs"):
        with st.expander("⚠️ Übersprungene oder fehlerhafte Dokumente", expanded=True):
            for msg in st.session_state["skipped_docs"]:
                st.warning(msg)

    if st.session_state.get("extracted_docs") and "df_buchungen" in st.session_state:
        with st.expander("1. Extrahierte Belegdaten (Unverfälschter PDF-Ist-Zustand)", expanded=False):
            st.dataframe(style_and_format_df(pd.DataFrame(st.session_state["extracted_docs"])), width="stretch")

        with st.expander("2. Ergebnis: 3-Way-Match, Materialität, MwSt-Check & VR-Verweis", expanded=True):
            col_info, col_toggle = st.columns([2.5, 1.5], vertical_alignment="center")
            with col_info:
                st.caption("💡 **Tipp:** Klicke links auf eine Zeile, um die zugehörigen PDF-Belege unten im Beleg-Inspektor zu öffnen.")
            with col_toggle:
                calc_vat_flag = st.toggle(
                    "🧮 Fehlende MwSt kalkulatorisch herausrechnen (20 %)",
                    value=False,
                    help="Berechnet Netto & MwSt für Belege ohne Steuerausweis nach, behält aber den Prüfungsvermerk bei."
                )

            st.session_state["df_match"] = perform_three_way_match(
                st.session_state["df_buchungen"],
                st.session_state["extracted_docs"],
                threshold=threshold,
                protokoll_obj=st.session_state.get("protokoll_meta"),
                calc_missing_vat=calc_vat_flag
            )

            selection_event = st.dataframe(
                style_and_format_df(st.session_state["df_match"]),
                width="stretch",
                on_select="rerun",
                selection_mode="single-row",
                key="match_table_select"
            )

        vr_done = "df_vr" in st.session_state and not st.session_state["df_vr"].empty
        btn_label_tab2 = (
            "📥 Komplette Excel-Prüfakte herunterladen (inkl. VR-Extrakt & Cross-Links)"
            if vr_done
            else "📥 Excel-Prüfakte herunterladen (3-Way-Match, Materialität & MwSt)"
        )

        excel_bytes = export_audit_excel(
            st.session_state["df_match"],
            st.session_state.get("df_vr")
        )
        st.download_button(
            label=btn_label_tab2,
            data=excel_bytes,
            file_name="SPT_Audit_3WayMatch.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_match_excel"
        )

        with st.expander("🔎 Live Beleg-Inspektor (In-App DataSnipper-Vorschau)", expanded=True):
            pdf_store = st.session_state.get("pdf_store", {})
            if pdf_store:
                all_pdfs = list(pdf_store.keys())
                linked_pdfs = []
                selected_auftrag = None

                selected_rows = selection_event.selection.rows if selection_event and selection_event.selection else []
                if selected_rows:
                    row_idx = selected_rows[0]
                    row_data = st.session_state["df_match"].iloc[row_idx]
                    selected_auftrag = row_data["Auftrag_Nr"]

                    for col_pdf in ["Ref_Rechnung_PDF", "Ref_Lieferschein_PDF"]:
                        val_str = str(row_data.get(col_pdf, ""))
                        for part in [p.strip() for p in val_str.split(",")]:
                            if part and part != "FEHLT" and part in pdf_store:
                                linked_pdfs.append(part)

                col_select, col_view = st.columns([1, 2])
                with col_select:
                    if selected_auftrag:
                        if linked_pdfs:
                            st.success(f"🔗 Gefiltert auf Auswahl: **Auftrag {selected_auftrag}**")
                            selected_pdf = st.radio(
                                "Verknüpfte Belege dieser Buchung:",
                                options=linked_pdfs,
                                key=f"radio_{selected_auftrag}"
                            )
                        else:
                            st.warning(f"⚠️ Für **Auftrag {selected_auftrag}** liegen keine PDF-Belege vor!")
                            selected_pdf = st.selectbox("Alle gültigen PDFs:", options=all_pdfs)
                    else:
                        selected_pdf = st.selectbox("PDF-Beleg auswählen (oder oben Zeile anklicken):", options=all_pdfs)

                    doc_info = next(
                        (d for d in st.session_state["extracted_docs"] if d["dateiname"] == selected_pdf),
                        None
                    )
                    if doc_info:
                        netto_val = float(doc_info.get("betrag_netto") or 0.0)
                        mwst_val = float(doc_info.get("mwst_betrag") or 0.0)
                        brutto_val = float(doc_info.get("gesamtbetrag_brutto") or 0.0)
                        satz_val = float(doc_info.get("mwst_satz_prozent") or 0.0)
                        st.info(
                            f"**Erkannte KI-Daten:**\n\n"
                            f"- **Typ:** {doc_info['dokument_typ']}\n"
                            f"- **Beleg-Nr.:** {doc_info['beleg_nr']}\n"
                            f"- **Auftrags-Nr.:** {doc_info['auftrags_nr']}\n"
                            f"- **Netto:** {netto_val:,.2f} €\n"
                            f"- **MwSt ({satz_val:.0f}%):** {mwst_val:,.2f} €\n"
                            f"- **Brutto:** {brutto_val:,.2f} €"
                        )
                with col_view:
                    highlights = []
                    if doc_info:
                        highlights.append(doc_info.get("auftrags_nr"))
                        if doc_info.get("gesamtbetrag_brutto"):
                            highlights.append(f"{float(doc_info['gesamtbetrag_brutto']):.2f}")
                    img_bytes = render_pdf_page_with_highlights(pdf_store[selected_pdf], search_terms=tuple(highlights))
                    st.image(img_bytes, caption=f"Vorschau: {selected_pdf}", width="stretch")

# TAB 3: Verwaltungsratsprotokoll (Prüfungsunterlagen-Extrakt & Cross-Link)
with tab3:
    col_t3_head, col_t3_rst = st.columns([4, 1], vertical_alignment="center")
    with col_t3_head:
        st.subheader(f"VR-Protokoll: Themen zusammenfassen & nach Materialität ({threshold:,.0f} €) filtern")

    vr_file = st.file_uploader(
        "VR-Protokoll (PDF) hochladen",
        type=["pdf"],
        key=f"vr_upload_{st.session_state['rc_tab3']}"
    )

    with col_t3_rst:
        if vr_file or "protokoll_meta" in st.session_state:
            if st.button("🔄 Protokoll zurücksetzen", width="stretch", key="btn_rst_t3"):
                reset_tab3()
                st.rerun()

    if st.button("🔍 Protokoll auswerten & Prüfungs-Extrakt erstellen") and vr_file:
        try:
            with st.spinner("Extrahiere Themen, Beträge und Materialität mit lokaler KI..."):
                protokoll = parse_protokoll_with_ollama(vr_file.getvalue(), model_name=model_name)
                st.session_state["protokoll_meta"] = protokoll
        except Exception as e:
            st.error(f"❌ **Fehler bei der Protokoll-Analyse:** {e}")

    if "protokoll_meta" in st.session_state:
        p = st.session_state["protokoll_meta"]
        df_vr = build_vr_dataframe(
            p,
            threshold=threshold,
            df_buchungen=st.session_state.get("df_buchungen")
        )
        st.session_state["df_vr"] = df_vr

        if "extracted_docs" in st.session_state and "df_buchungen" in st.session_state:
            st.session_state["df_match"] = perform_three_way_match(
                st.session_state["df_buchungen"],
                st.session_state["extracted_docs"],
                threshold=threshold,
                protokoll_obj=p
            )

        col1, col2, col3 = st.columns(3)
        col1.metric("Sitzungs-Nr.", p.sitzungs_nr)
        col2.metric("Sitzungsdatum", p.datum)
        col3.metric("Aktive Materialitätsgrenze", f"{threshold:,.0f} €")
        st.write("**Anwesende Personen:**", ", ".join(p.anwesende))

        with st.expander("📋 Strukturierter Themen-Extrakt für die Prüfungsunterlagen (inkl. Buchungs-Verweis)", expanded=True):
            st.dataframe(style_and_format_df(df_vr), width="stretch")

        match_done = "df_match" in st.session_state and not st.session_state["df_match"].empty
        btn_label_tab3 = (
            "📥 Komplette Excel-Prüfakte herunterladen (Blatt 1: 3-Way-Match + Blatt 2: VR-Extrakt)"
            if match_done
            else "📥 Nur VR-Protokoll Excel-Extrakt herunterladen"
        )

        excel_bytes_vr = export_audit_excel(
            st.session_state.get("df_match", pd.DataFrame()),
            df_vr
        )
        st.download_button(
            label=btn_label_tab3,
            data=excel_bytes_vr,
            file_name="SPT_Audit_Pruefakte_Komplett.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_vr_excel"
        )