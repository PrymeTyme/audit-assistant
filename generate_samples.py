import os
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from PIL import Image, ImageDraw, ImageFont
import io


os.makedirs("sample_data/pdfs", exist_ok=True)

# 1. Buchungsexport (CSV)
csv_data = {
    "Buchungsdatum_Klient": ["2025-03-10", "2025-03-12", "2025-03-16", "2025-03-18"],
    "Ref_Auftrag": ["A-1001", "A-1002", "A-1003", "A-1004"],
    "Kreditor_Name": ["AlpenTech GmbH", "BüroProfi AG", "Consulting X", "IT-Solutions KG"],
    "Gezahlter_Betrag_EUR": ["1200,00", "950,00", "15000,00", "450,00"],
    "Buchungstext": [
        "Zahlung Server-Racks",
        "Zahlung Bürostühle",
        "Sonderberatung (Sonntagsbuchung!)",
        "Monatsgebühr Cloud"
    ]
}
pd.DataFrame(csv_data).to_csv("sample_data/klienten_buchungen_export.csv", sep=";", index=False)


# LAYOUT A: AlpenTech GmbH (Modernes Design mit dunkelblauem Header-Block & Tabellen-Linien)
def create_alpentech_invoice(filename):
    c = canvas.Canvas(f"sample_data/pdfs/{filename}", pagesize=A4)
    # Dunkelblauer Logo-Header
    c.setFillColor(colors.HexColor("#1B365D"))
    c.rect(0, 760, 600, 90, fill=True, stroke=False)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(40, 800, "ALPENTECH")
    c.setFont("Helvetica", 10)
    c.drawString(40, 780, "IT-Infrastruktur & Serverlösungen | Industriestr. 5 | 6850 Dornbirn")

    # Metadaten rechtsbündig im Kasten
    c.setFillColor(colors.black)
    c.setStrokeColor(colors.grey)
    c.rect(350, 640, 200, 90, fill=False, stroke=True)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(360, 710, "RECHNUNG / INVOICE")
    c.setFont("Helvetica", 10)
    c.drawString(360, 690, "Beleg-Nr.: R-2025-101")
    c.drawString(360, 675, "Kunden-Order: A-1001")
    c.drawString(360, 660, "Ausstellungsdatum: 2025-03-08")

    # Tabellen-Kopf mit Trennlinien
    c.line(40, 580, 550, 580)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(45, 565, "Pos.")
    c.drawString(90, 565, "Artikelbeschreibung")
    c.drawString(380, 565, "Menge")
    c.drawString(470, 565, "Summe")
    c.line(40, 555, 550, 555)

    # Tabellen-Inhalt
    c.setFont("Helvetica", 10)
    c.drawString(45, 535, "01")
    c.drawString(90, 535, "Server-Rack 19 Zoll (42 HE, schallgedämmt)")
    c.drawString(380, 535, "2 Stk.")
    c.drawString(470, 535, "1000.00 EUR")
    c.line(40, 515, 550, 515)

    # Summenblock unten rechts
    c.drawString(360, 490, "Nettobetrag: 1000.00 EUR")
    c.drawString(360, 475, "20% MwSt: 200.00 EUR")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(360, 450, "Endbetrag Brutto: 1200.00 EUR")
    c.save()


def create_alpentech_delivery(filename):
    c = canvas.Canvas(f"sample_data/pdfs/{filename}", pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, 790, "ALPENTECH GmbH - LIEFERSCHEIN")
    c.setLineWidth(2)
    c.line(40, 780, 550, 780)

    c.setFont("Helvetica", 10)
    c.drawString(40, 750, "Lieferschein-Nr.: LS-501")
    c.drawString(250, 750, "Gehört zu Auftrag: A-1001")
    c.drawString(430, 750, "Versand am: 2025-03-07")
    c.line(40, 740, 550, 740)

    c.drawString(40, 700, "Gelieferte Packstücke (ohne Preisangabe):")
    c.rect(40, 640, 510, 50)
    c.drawString(55, 665, "[x] 2 Stück - Server-Rack 19 Zoll (Seriennr. AT-991, AT-992) - Vollständig geliefert")
    c.save()


# LAYOUT B: BüroProfi AG (Klassisches Kasten-/Grid-Layout mit komplett anderen Feldbezeichnungen)
def create_bueroprofi_invoice(filename):
    c = canvas.Canvas(f"sample_data/pdfs/{filename}", pagesize=A4)
    # Grünes Logo-Badge rechts oben
    c.setFillColor(colors.HexColor("#2E7D32"))
    c.roundRect(380, 760, 170, 55, 8, fill=True, stroke=False)
    c.setFillColor(colors.white)
    c.setFont("Courier-Bold", 15)
    c.drawString(395, 785, "BüroProfi AG")
    c.setFont("Courier", 8)
    c.drawString(395, 770, "6900 Bregenz | Bahnhofstr. 12")

    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, 720, "Faktura / Ausgangsrechnung Nr. R-884")

    # Info-Leiste mit vertikalen Trennstrichen und anderer Terminologie ("Kommission")
    c.setFillColor(colors.HexColor("#F2F2F2"))
    c.rect(40, 665, 510, 35, fill=True, stroke=True)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 9)
    c.drawString(50, 680, "Ihre Kommission / Bestell-Ref.: A-1002")
    c.line(250, 665, 250, 700)
    c.drawString(260, 680, "Rechnungsdatum: 2025-03-11")
    c.line(420, 665, 420, 700)
    c.drawString(430, 680, "Kunden-ID: K-77")

    # Positionen im Kasten
    c.rect(40, 550, 510, 95, fill=False, stroke=True)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, 625, "Berechnete Leistungen:")
    c.setFont("Helvetica", 10)
    c.drawString(50, 600, "4x Ergonomischer Bürostuhl 'Comfort Pro' Schwarz (Einzelpreis 200.00 EUR)")
    c.line(40, 580, 550, 580)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, 560, "Zu zahlender Rechnungsbetrag (inkl. USt): 800.00 EUR")
    c.save()


def create_bueroprofi_delivery(filename):
    c = canvas.Canvas(f"sample_data/pdfs/{filename}", pagesize=A4)
    c.setFont("Courier-Bold", 14)
    c.drawString(40, 780, "*** WARENBEGLEITSCHEIN / LIEFERSCHEIN ***")
    c.drawString(40, 760, "Aussteller: BüroProfi AG, Bregenz")
    c.line(40, 745, 550, 745)

    c.setFont("Courier", 10)
    c.drawString(40, 720, "Belegnummer Lieferschein : LS-990")
    c.drawString(40, 700, "Referenz zum Kundenauftrag: A-1002")
    c.drawString(40, 680, "Tag der Zustellung       : 2025-03-10")
    c.line(40, 660, 550, 660)
    c.drawString(40, 630, "Inhalt der Sendung: 4x Ergonomischer Bürostuhl 'Comfort Pro'")
    c.drawString(40, 610, "Warenwert auf Lieferschein: 0.00 EUR (Rechnung folgt separat)")
    c.save()


# VR-Protokoll erstellen
def create_vr_protokoll(filename):
    c = canvas.Canvas(f"sample_data/pdfs/{filename}", pagesize=A4)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(50, 800, "VERWALTUNGSRATSPROTOKOLL - Sitzung Nr. VR-2025-04")
    c.line(50, 792, 540, 792)
    c.setFont("Helvetica", 10)
    lines = [
        "Datum der Sitzung: 2025-03-01",
        "Anwesende Mitglieder: Dr. Markus Huber, Mag. Sandra König, Dipl.-Ing. Reto Lutz",
        "Tagesordnung & Beschlüsse:",
        "1. Die Anschaffung neuer Server-Racks (Auftrag A-1001) über 1.200 EUR wird genehmigt.",
        "2. Ein Beratervertrag mit Consulting X über pauschal 15.000 EUR wird kritisch diskutiert.",
        "Prüfungsrelevante Risiken: Es droht ein Rechtsstreit mit einem ehemaligen Lieferanten (Streitwert 45.000 EUR).",
        "Rückstellungen müssen in der Bilanz dringend geprüft werden."
    ]
    y = 765
    for line in lines:
        c.drawString(50, y, line)
        y -= 22
    c.save()


create_alpentech_invoice("Rechnung_AlpenTech_R101.pdf")
create_alpentech_delivery("Lieferschein_AlpenTech_L101.pdf")
create_bueroprofi_invoice("Rechnung_BueroProfi_R202.pdf")
create_bueroprofi_delivery("Lieferschein_BueroProfi_L202.pdf")
create_vr_protokoll("VR_Protokoll_Sitzung_04.pdf")

print("Neue PDFs mit unterschiedlichen Firmen-Layouts, Logos und Trennlinien erstellt!")


def create_scanned_image_pdf(filename):
    """
    Erzeugt ein reines Bild-PDF (ohne Textebene!) mit leichtem Scan-Winkel,
    um den OCR-Fallback für Auftrag A-1004 realistisch zu testen.
    """
    # 1. Weißes Bild erstellen (wie ein gescanntes A4-Blatt)
    img = Image.new("RGB", (1200, 1600), color=(248, 248, 245))
    draw = ImageDraw.Draw(img)
    
    # Standard-Schriftart größer skalieren
    font_title = ImageFont.load_default(size=36)
    font_body = ImageFont.load_default(size=26)
    
    # Text direkt als Pixel auf das Bild zeichnen
    draw.text((100, 120), "IT-Solutions KG - Cloud & Hosting", fill=(20, 20, 20), font=font_title)
    draw.line((100, 180, 1050, 180), fill=(100, 100, 100), width=3)
    
    lines = [
        "Dokumententyp: RECHNUNG (Gescanntes Original)",
        "Rechnungsnummer: R-2025-999",
        "Auftragsnummer: A-1004",
        "Rechnungsdatum: 2025-03-15",
        "------------------------------------------------------------",
        "Position 1: Monatliche Cloud-Server Gebuehr Maerz 2025",
        "------------------------------------------------------------",
        "Gesamtbetrag Brutto: 450.00 EUR",
        "Status: Per Lastschrift eingezogen"
    ]
    
    y = 240
    for line in lines:
        draw.text((100, y), line, fill=(30, 30, 30), font=font_body)
        y += 65
        
    # 2. Leicht schief drehen (1.5 Grad), wie auf einem echten Flachbettscanner
    img_rotated = img.rotate(1.5, expand=False, fillcolor=(248, 248, 245))
    
    # 3. Als reines Bild-PDF (ohne durchsuchbaren Text!) speichern
    img_rotated.save(f"sample_data/pdfs/{filename}", "PDF", resolution=150.0)

create_scanned_image_pdf("Scan_Rechnung_IT_Solutions_A1004.pdf")
print("Echter Scan-Beleg (ohne Textebene) für A-1004 erstellt!")