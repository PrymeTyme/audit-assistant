import re
import pandas as pd


def _parse_currency(val) -> float:
    """Konvertiert deutsche ('1.200,50') und englische ('1200.50') Beträge sicher in Float."""
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).strip()
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s:
        return 0.0

    # Fall 1: Punkt und Komma vorhanden -> letztes Trennzeichen ist das Dezimalzeichen
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    # Fall 2: Nur Komma vorhanden -> deutsches Dezimalkomma
    elif "," in s:
        s = s.replace(",", ".")

    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def clean_and_map_csv(file, mapping_dict: dict) -> pd.DataFrame:
    try:
        file.seek(0)
        df = pd.read_csv(file, sep=None, engine="python")
    except Exception as e:
        raise ValueError(f"Die CSV-Datei konnte nicht gelesen werden: {e}")

    if df.empty:
        raise ValueError("Die hochgeladene CSV-Datei enthält keine Datenzeilen.")

    # Spaltennamen von unsichtbaren Leerzeichen befreien
    df.columns = [str(c).strip() for c in df.columns]

    missing_cols = [col for col in mapping_dict.keys() if col not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Falsches CSV-Format! Folgende Pflichtspalten fehlen: {', '.join(missing_cols)}"
        )

    df = df.rename(columns=mapping_dict)
    df["auftrag_nr"] = df["auftrag_nr"].astype(str).str.strip().str.upper()
    df["kreditor"] = df["kreditor"].astype(str).str.strip()
    df["betrag_gezahlt"] = df["betrag_gezahlt"].apply(_parse_currency)
    df["datum"] = pd.to_datetime(df["datum"], errors="coerce")
    return df


def run_risk_analysis(df: pd.DataFrame, threshold: float = 12000.0) -> pd.DataFrame:
    df = df.copy()
    materialitaet = []
    risiken = []

    for _, row in df.iterrows():
        betrag = float(row["betrag_gezahlt"])
        ist_wesentlich = betrag >= float(threshold)
        materialitaet.append("WESENTLICH" if ist_wesentlich else "Unwesentlich")

        flags = []
        if ist_wesentlich:
            flags.append(f"Wesentlich (>= {threshold:,.0f} EUR)")
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