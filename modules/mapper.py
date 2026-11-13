import re
import pandas as pd


def _parse_currency(val) -> float:
    """Konvertiert DACH- ('15.000', '1.200,50', '500,00-') und US-Beträge ('1,200.50', '1200.50') sicher."""
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return round(float(val), 2)

    s = str(val).strip()
    if not s or s.lower() == "nan":
        return 0.0

    # Buchhalterisches Minus erkennen: '1.200,00-' oder '(1.200,00)' oder '-1.200,00'
    is_negative = s.startswith("-") or s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    s = re.sub(r"[^\d,.]", "", s)
    if not s:
        return 0.0

    # Fall 1: Punkt und Komma vorhanden -> letztes Trennzeichen ist das Dezimalzeichen
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    # Fall 2: Nur Komma vorhanden -> deutsches Dezimalkomma (oder US-Tausender wie '15,000')
    elif "," in s:
        if s.count(",") > 1 or re.match(r"^\d{1,3},\d{3}$", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    # Fall 3: Nur Punkt vorhanden -> prüfen auf deutschen Tausenderpunkt (z.B. '15.000' oder '1.200.000')
    elif "." in s:
        if s.count(".") > 1 or re.match(r"^\d{1,3}\.\d{3}$", s):
            s = s.replace(".", "")

    try:
        res = round(float(s), 2)
        return -res if is_negative else res
    except ValueError:
        return 0.0


def clean_and_map_csv(file, mapping_dict: dict) -> pd.DataFrame:
    df = None
    last_err = None

    # Encoding-Fallback für Excel/BMD-Exporte (UTF-8 mit BOM -> Windows-1252/Latin1)
    for enc in ["utf-8-sig", "cp1252", "latin1"]:
        try:
            file.seek(0)
            df = pd.read_csv(file, sep=None, engine="python", dtype=str, encoding=enc)
            break
        except UnicodeDecodeError as e:
            last_err = e
            continue
        except Exception as e:
            raise ValueError(f"Die CSV-Datei konnte nicht gelesen werden: {e}")

    if df is None:
        raise ValueError(f"Zeichenkodierung der CSV-Datei nicht lesbar: {last_err}")

    if df.empty:
        raise ValueError("Die hochgeladene CSV-Datei enthält keine Datenzeilen.")

    df.columns = [str(c).strip() for c in df.columns]

    missing_cols = [col for col in mapping_dict.keys() if col not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Falsches CSV-Format! Folgende Pflichtspalten fehlen: {', '.join(missing_cols)}"
        )

    df = df.rename(columns=mapping_dict)
    df["auftrag_nr"] = df["auftrag_nr"].fillna("UNBEKANNT").astype(str).str.strip().str.upper()
    df["kreditor"] = df["kreditor"].fillna("Unbekannt").astype(str).str.strip()
    df["betrag_gezahlt"] = df["betrag_gezahlt"].apply(_parse_currency)
    df["datum"] = pd.to_datetime(
        df["datum"].fillna("").astype(str).str.strip(),
        dayfirst=True,
        format="mixed",
        errors="coerce"
    )
    return df


def run_risk_analysis(df: pd.DataFrame, threshold: float = 12000.0) -> pd.DataFrame:
    df = df.copy()
    materialitaet = []
    risiken = []

    for _, row in df.iterrows():
        betrag = float(row["betrag_gezahlt"])
        # abs(betrag) prüft auch hohe Storno-/Gutschriftsbuchungen auf Wesentlichkeit
        ist_wesentlich = abs(betrag) >= float(threshold)
        materialitaet.append("WESENTLICH" if ist_wesentlich else "Unwesentlich")

        flags = []
        if ist_wesentlich:
            flags.append(f"Wesentlich (>= {threshold:,.0f} EUR)")
        if betrag < 0:
            flags.append("Negativbetrag / Storno")
        if pd.notnull(row["datum"]) and row["datum"].weekday() >= 5:
            flags.append("Wochenend-Buchung")
        elif pd.isnull(row["datum"]):
            flags.append("Ungültiges/Fehlendes Buchungsdatum")

        risiken.append(", ".join(flags) if flags else "Unauffällig")

    df["Materialitaet"] = materialitaet
    df["Risiko_Hinweis"] = risiken
    df["Stichprobe_ziehen"] = df["Materialitaet"] == "WESENTLICH"
    df["datum"] = df["datum"].dt.strftime("%Y-%m-%d").fillna("Unbekannt")
    return df