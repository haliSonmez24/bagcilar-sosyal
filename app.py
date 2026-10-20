from flask import Flask, render_template_string, request
import requests
import re
import pytesseract
from PIL import Image

app = Flask(__name__)

# Google Apps Script Web App URL'in
GOOGLE_SCRIPT_URL = "BURAYA_GOOGLE_APPS_SCRIPT_URL_ADRESINI_YAPISTIR"

def evaluate_and_calculate_from_ocr(extracted_text, manual_kisi_sayisi):
    text_lower = extracted_text.lower()
    
    # --- 1. SAĞ ÜST ALANLARIN OCR İLE ESNEK VE KUSURSUZ ÇEKİLMESİ ---
    
    # Aile Nüfusu (Hane Kişi Sayısı)
    kisi_sayisi = manual_kisi_sayisi
    nufus_match = re.search(r'(?:aile\s*nüfusu|nüfus)[^\d]*(\d+)', text_lower)
    if nufus_match:
        try:
            kisi_sayisi = int(nufus_match.group(1))
        except:
            pass

    # Ev Kirası (Çok esnek tarama: etiket sonrasındaki ilk sayısal değeri yakalar)
    kira_val = 0.0
    kira_match = re.search(r'(?:ev\s*kirası|kira)[^\d]*([\d\.,]+)', text_lower)
    if kira_match:
        try:
            clean_kira = kira_match.group(1).replace('.', '').replace(',', '.')
            kira_val = float(clean_kira)
        except:
            pass
            
    kira_tutari_str = f"{kira_val:,.2f} TL".replace(',', 'X').replace('.', ',').replace('X', '.') if kira_val > 0 else "0,00 TL"

    # Toplam Gelir (Sağ üstten esnek okuma)
    toplam_gelir_val = 0.0
    gelir_match = re.search(r'(?:toplam\s*gelir|hane\s*geliri)[^\d]*([\d\.,]+)', text_lower)
    if gelir_match:
        try:
            clean_gelir = gelir_match.group(1).replace('.', '').replace(',', '.')
            toplam_gelir_val = float(clean_gelir)
        except:
            pass

    # Eğer sağ üstte toplam gelir net okunamadıysa alt metinden hesapla
    if toplam_gelir_val == 0.0:
        sentences = re.split(r'[\.\!\?\;]+', text_lower)
        forbidden_words = ['borç', 'borcu', 'kredi borcu', 'borçlanma', 'borçları']
        
        for sent in sentences:
            sent = sent.strip()
            if not sent or any(fw in sent for fw in forbidden_words) or 'kira' in sent:
                continue
            
            # Sabit Yardımlar
            if 'asgari ücret' in sent: toplam_gelir_val += 28075.0
            if 'yaşlılık' in sent or 'yaşlı aylığı' in sent: toplam_gelir_val += 7257.0
            if 'emekli' in sent or 'emekli aylığı' in sent: toplam_gelir_val += 23552.0
            if 'ölüm aylığı' in sent: toplam_gelir_val += 14650.0
            if 'yetim aylığı' in sent or 'yetim maaşı' in sent: toplam_gelir_val += 5800.0
            if 'engelli yakını' in sent: toplam_gelir_val += 5793.0
            elif 'engelli' in sent: toplam_gelir_val += 7250.0
            if 'evde bakım' in sent: toplam_gelir_val += 7250.0
            if 'sed' in sent: toplam_gelir_val += 11000.0

            # Serbest Maaş/Gelir Rakamları
            money_matches = re.findall(r'([\d\.,]+)\s*(?:tl|lira|₺)', sent)
            for m in money_matches:
                try:
                    val = float(m.replace('.', '').replace(',', '.'))
                    if any(kw in sent for kw in ['gelir', 'maaş', 'aylık', 'yardım', 'destek', 'yevmiye']) and val > 500:
                        if val not in [28075.0, 7257.0, 23552.0, 14650.0, 5800.0, 7250.0, 5793.0, 11000.0]:
                            toplam_gelir_val += val
                except:
                    pass

    hane_geliri_str = f"{toplam_gelir_val:,.2f} TL".replace(',', 'X').replace('.', ',').replace('X', '.') if toplam_gelir_val > 0 else "0,00 TL"

    # Kişi Başı Gelir
    kisi_basi_val = 0.0
    kisi_basi_match = re.search(r'(?:kişi\s*başına\s*gelir|kişi\s*başı)[^\d]*([\d\.,]+)', text_lower)
    if kisi_basi_match:
        try:
            kisi_basi_val = float(kisi_basi_match.group(1).replace('.', '').replace(',', '.'))
        except:
            pass
            
    if kisi_basi_val == 0.0 and kisi_sayisi > 0:
        kisi_basi_val = toplam_gelir_val / kisi_sayisi

    kisi_basi_gelir_str = f"{kisi_basi_val:,.2f} TL".replace(',', 'X').replace('.', ',').replace('X', '.')

    # --- 2. ALT METİN ANALİZİ (Kriterler: Sosyal Market & Gıda) ---
    is_definitely_tenant = any(kw in text_lower for kw in ['kiracı', 'kira öder', 'kira ödüyor', 'ev sahibi değil']) or (kira_val > 0)
    is_ev_sahibi = False
    if not is_definitely_tenant:
        if 'ev sahibi' in text_lower or 'mülk var' in text_lower:
            is_ev_sahibi = True
        if 'akraba' in text_lower and ('kira ödemiyor' in text_lower or 'bedelsiz' in text_lower):
            is_ev_sahibi = True

    has_car = any(kw in text_lower for kw in ['araç', 'otomobil', 'araba', 'motosiklet'])
    has_old_car = False
    years_found = re.findall(r'\b(20[0-9]{2}|19[0-9]{2})\b', text_lower)
    for y in years_found:
        if int(y) <= 2015:
            has_old_car = True

    income_exceeded = 'gelir sınırı aşıldı' in text_lower

    # Sosyal Market Kararı
    sm_reasons = []
    if is_ev_sahibi: sm_reasons.append("Ev Sahibi / Kira Ödemiyor")
    if has_car: sm_reasons.append("Araç Bulundu")
    if income_exceeded: sm_reasons.append("Gelir Sınırı Aşıldı")
    sosyal_market = "Uygun Değil" if sm_reasons else "Uygun"

    # Gıda Desteği Kararı
    gida_reasons = []
    if income_exceeded: gida_reasons.append("Gelir Sınırı Aşıldı")
    if has_car and not has_old_car: gida_reasons.append("Model Yılı 2015 Üzeri Araç")
    gida = "Uygun Değil" if gida_reasons else "Uygun"

    return {
        "kisi_sayisi": str(kisi_sayisi),
        "hane_geliri": hane_geliri_str,
        "kisi_basi_gelir": kisi_basi_gelir_str,
        "sosyal_market": sosyal_market,
        "gida": gida,
        "kira_tutari": kira_tutari_str,
        "okunan_metin": extracted_text
    }

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bağcılar Belediyesi - Sosyal Yardım Karar Destek</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f1f5f9; font-family: 'Segoe UI', Tahoma, sans-serif; }
        .navbar-custom { background-color: #0f172a; color: #38bdf8; }
        .card-custom { border: none; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
        .btn-primary-custom { background-color: #0284c7; border: none; }
        .btn-primary-custom:hover { background-color: #0369a1; }
        .badge-uygun { background-color: #10b981; }
        .badge-degil { background-color: #ef4444; }
    </style>
</head>
<body>
    <nav class="navbar navbar-custom py-3 px-4 shadow-sm">
        <div class="container-fluid">
            <span class="navbar-brand mb-0 h1 fw-bold text-info">🏛️ BAĞCILAR BELEDİYESİ</span>
            <span class="text-white-50 small">Mobil Saha Sistemi v7.1 (Akıllı Form OCR)</span>
        </div>
    </nav>

    <div class="container py-4">
        <div class="row justify-content-center">
            <div class="col-md-8">
                <div class="card card-custom p-4 mb-4 bg-white">
                    <h5 class="fw-bold text-primary mb-3">📋 Rapor Kağıdı Fotoğrafı ile Akıllı Analiz</h5>
                    <form method="POST" enctype="multipart/form-data">
                        <div class="mb-3">
                            <label class="form-label small fw-bold text-secondary">Vatandaş Adı Soyadı:</label>
                            <input type="text" class="form-control" name="ad_soyad" placeholder="Örn: Ahmet Yılmaz" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-bold text-secondary">Varsayılan Nüfus (Fotoğraftan okunamazsa kullanılır):</label>
                            <input type="number" class="form-control" name="kisi_sayisi" value="3" required>
                        </div>
                        
                        <div class="mb-3 p-3 border rounded bg-light">
                            <label class="form-label small fw-bold text-dark">📷 Rapor Kağıdı Fotoğrafı (Sağ üst ve alt metin içeren form):</label>
                            <input type="file" class="form-control" name="rapor_dosyasi" accept="image/*" capture="environment" required>
                            <div class="form-text small text-muted">Sağ üstteki nüfus, kira ve gelir bilgilerini, alttaki rapor metnini otomatik ayrıştırır.</div>
                        </div>

                        <button type="submit" name="action" value="evaluate" class="btn btn-primary-custom w-100 py-2 fw-bold text-white mb-2">🔍 Formu Tara ve Değerlendir</button>
                    </form>
                </div>

                {% if result %}
                <div class="card card-custom p-4 bg-white border-start border-4 border-info">
                    <h5 class="fw-bold text-dark mb-3">📊 Akıllı Analiz Sonuçları</h5>
                    <ul class="list-group list-group-flush mb-3">
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <strong>Tespit Edilen Nüfus:</strong> <span class="badge bg-secondary fs-6">{{ result.kisi_sayisi }} Kişi</span>
                        </li>
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <strong>Toplam Hane Geliri:</strong> <span class="badge bg-secondary fs-6">{{ result.hane_geliri }}</span>
                        </li>
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <strong>Kişi Başı Gelir:</strong> <span class="badge bg-secondary fs-6">{{ result.kisi_basi_gelir }}</span>
                        </li>
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <strong>Ev Kirası:</strong> <span class="badge bg-secondary fs-6">{{ result.kira_tutari }}</span>
                        </li>
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <strong>Sosyal Market:</strong> 
                            <span class="badge {% if result.sosyal_market == 'Uygun' %}badge-uygun{% else %}badge-degil{% endif %} fs-6">{{ result.sosyal_market }}</span>
                        </li>
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <strong>Gıda Desteği:</strong> 
                            <span class="badge {% if result.gida == 'Uygun' %}badge-uygun{% else %}badge-degil{% endif %} fs-6">{{ result.gida }}</span>
                        </li>
                    </ul>

                    <details class="mb-3 text-muted small">
                        <summary class="fw-bold cursor-pointer">📄 OCR Tarafından Okunan Ham Metni Gör</summary>
                        <p class="p-2 bg-light border rounded mt-2" style="white-space: pre-wrap;">{{ result.okunan_metin }}</p>
                    </details>

                    <form method="POST">
                        <input type="hidden" name="ad_soyad" value="{{ result.ad_soyad }}">
                        <input type="hidden" name="kisi_sayisi" value="{{ result.kisi_sayisi }}">
                        <input type="hidden" name="hane_geliri" value="{{ result.hane_geliri }}">
                        <input type="hidden" name="kisi_basi_gelir" value="{{ result.kisi_basi_gelir }}">
                        <input type="hidden" name="sosyal_market" value="{{ result.sosyal_market }}">
                        <input type="hidden" name="gida" value="{{ result.gida }}">
                        <input type="hidden" name="kira_tutari" value="{{ result.kira_tutari }}">
                        <button type="submit" name="action" value="save" class="btn btn-success w-100 py-2 fw-bold">💾 Google E-Tablolara Kaydet</button>
                    </form>
                </div>
                {% endif %}

                {% if saved %}
                <div class="alert alert-success mt-3 fw-bold text-center" role="alert">
                    ✅ Başarıyla Google E-Tablolar'a kaydedildi!
                </div>
                {% endif %}
            </div>
        </div>
    </div>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    saved = False
    if request.method == "POST":
        action = request.form.get("action")
        if action == "evaluate":
            ad_soyad = request.form.get("ad_soyad", "Belirtilmemiş")
            try:
                manual_kisi = int(request.form.get("kisi_sayisi", 3))
            except:
                manual_kisi = 3

            file = request.files.get('rapor_dosyasi')
            extracted_text = ""
            if file and file.filename != '':
                try:
                    img = Image.open(file.stream)
                    extracted_text = pytesseract.image_to_string(img, lang='tur')
                except Exception as e:
                    print("OCR Hatası:", e)

            res = evaluate_and_calculate_from_ocr(extracted_text, manual_kisi)
            res["ad_soyad"] = ad_soyad
            result = res

        elif action == "save":
            payload = {
                "ad_soyad": request.form.get("ad_soyad"),
                "kisi_sayisi": request.form.get("kisi_sayisi"),
                "hane_geliri": request.form.get("hane_geliri"),
                "kisi_basi_gelir": request.form.get("kisi_basi_gelir"),
                "sosyal_market": request.form.get("sosyal_market"),
                "gida": request.form.get("gida"),
                "kira_tutari": request.form.get("kira_tutari")
            }
            try:
                requests.post(GOOGLE_SCRIPT_URL, json=payload)
                saved = True
            except Exception as e:
                print("Kayıt hatası:", e)

    return render_template_string(HTML_TEMPLATE, result=result, saved=saved)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)