from flask import Flask, render_template_string, request
import requests
import re
import os
import pytesseract
from PIL import Image

app = Flask(__name__)

# Google Apps Script Web App URL'in
GOOGLE_SCRIPT_URL = "BURAYA_GOOGLE_APPS_SCRIPT_URL_ADRESINI_YAPISTIR"

def evaluate_and_calculate(data, rapor_metni):
    ad_soyad = data.get('ad_soyad', 'Belirtilmemiş')
    rapor_metni = str(rapor_metni).lower()
    
    try:
        kisi_sayisi = int(data.get('kisi_sayisi', 3))
    except:
        kisi_sayisi = 3

    # --- 1. KİRA TUTARI (Kira kelimesinin yanındaki rakam - Gelire ASLA eklenmez) ---
    kira_tutari_str = "Belirtilmemiş"
    kira_val = 0.0
    
    rent_matches = re.findall(r'(\d+(?:[.,]\d+)*)\s*(?:tl|lira|₺)[^\.\n]*kira', rapor_metni)
    if not rent_matches:
        rent_matches = re.findall(r'kira[^\.\n]*?(\d+(?:[.,]\d+)*)\s*(?:tl|lira|₺)', rapor_metni)
    if not rent_matches:
        rent_matches = re.findall(r'kira[^\d]*(\d+(?:[.,]\d+)?)', rapor_metni)

    if rent_matches:
        try:
            clean_kira = str(rent_matches[0]).replace('.', '').replace(',', '.')
            kira_val = float(clean_kira)
        except:
            pass

    if kira_val > 0:
        kira_tutari_str = f"{kira_val:,.2f} TL".replace(',', 'X').replace('.', ',').replace('X', '.')

    # --- 2. HANE GELİRİ HESABI (Yardımlar + Maaşlar) ---
    sentences = re.split(r'[\.\!\?\;]+', rapor_metni)
    total_income = 0.0

    forbidden_words = ['borç', 'borcu', 'kredi borcu', 'borçlanma', 'borçları']

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue

        # Borç geçen cümleleri tamamen atla
        if any(fw in sent for fw in forbidden_words):
            continue

        # Kira cümlesiyse gelir hesabına katma!
        if 'kira' in sent:
            continue

        # Sabit Yardımlar ve Maaşlar
        if 'asgari ücret' in sent:
            total_income += 28075.0
        if 'yaşlılık' in sent or 'yaşlı aylığı' in sent:
            total_income += 7257.0
        if 'emekli' in sent or 'emekli aylığı' in sent:
            total_income += 23552.0
        if 'ölüm aylığı' in sent:
            total_income += 14650.0
        if 'yetim aylığı' in sent or 'yetim maaşı' in sent:
            total_income += 5800.0
        if 'engelli yakını' in sent:
            total_income += 5793.0
        elif 'engelli' in sent:
            total_income += 7250.0
        if 'evde bakım' in sent or 'evde bakım aylığı' in sent:
            total_income += 7250.0
        if 'sed' in sent:
            total_income += 11000.0

        # "Maaş", "gelir", "aylık" geçen cümlelerdeki serbest rakamları hane gelirine ekle
        money_matches = re.findall(r'([\d\.,]+)\s*(?:tl|lira|₺)', sent)
        for m in money_matches:
            try:
                val = float(m.replace('.', '').replace(',', '.'))
                income_keywords = ['gelir', 'maaş', 'aylık', 'yardım', 'destek', 'yevmiye', 'ödenen', 'aldığı']
                if any(kw in sent for kw in income_keywords) and val > 500:
                    if val not in [28075.0, 7257.0, 23552.0, 14650.0, 5800.0, 7250.0, 5793.0, 11000.0]:
                        total_income += val
            except:
                pass

    hane_geliri_str = f"{total_income:,.2f} TL".replace(',', 'X').replace('.', ',').replace('X', '.') if total_income > 0 else "0,00 TL"
    
    per_capita = total_income / kisi_sayisi if kisi_sayisi > 0 else 0.0
    kisi_basi_gelir_str = f"{per_capita:,.2f} TL".replace(',', 'X').replace('.', ',').replace('X', '.')

    # --- 3. KRİTERLER (SOSYAL MARKET & GIDA) ---
    is_definitely_tenant = any(kw in rapor_metni for kw in ['kiracı', 'kira öder', 'kira ödüyor', 'ev sahibi değil']) or (kira_val > 0)
    is_ev_sahibi = False
    if not is_definitely_tenant:
        if 'ev sahibi' in rapor_metni or 'mülk var' in rapor_metni:
            is_ev_sahibi = True
        if 'akraba' in rapor_metni and ('kira ödemiyor' in rapor_metni or 'bedelsiz' in rapor_metni):
            is_ev_sahibi = True

    has_car = any(kw in rapor_metni for kw in ['araç', 'otomobil', 'araba', 'motosiklet'])
    has_old_car = False
    years_found = re.findall(r'\b(20[0-9]{2}|19[0-9]{2})\b', rapor_metni)
    for y in years_found:
        if int(y) <= 2015:
            has_old_car = True

    income_exceeded = 'gelir sınırı aşıldı' in rapor_metni

    # Sosyal Market
    sm_reasons = []
    if is_ev_sahibi: sm_reasons.append("Ev Sahibi / Kira Ödemiyor")
    if has_car: sm_reasons.append("Araç Bulundu")
    if income_exceeded: sm_reasons.append("Gelir Sınırı Aşıldı")
    sosyal_market = "Uygun Değil" if sm_reasons else "Uygun"

    # Gıda Desteği
    gida_reasons = []
    if income_exceeded: gida_reasons.append("Gelir Sınırı Aşıldı")
    if has_car and not has_old_car: gida_reasons.append("Model Yılı 2015 Üzeri Araç")
    gida = "Uygun Değil" if gida_reasons else "Uygun"

    return {
        "ad_soyad": ad_soyad,
        "kisi_sayisi": str(kisi_sayisi),
        "hane_geliri": hane_geliri_str,
        "kisi_basi_gelir": kisi_basi_gelir_str,
        "sosyal_market": sosyal_market,
        "gida": gida,
        "kira_tutari": kira_tutari_str
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
            <span class="text-white-50 small">Mobil Saha Sistemi v6.0 (OCR Destekli)</span>
        </div>
    </nav>

    <div class="container py-4">
        <div class="row justify-content-center">
            <div class="col-md-8">
                <div class="card card-custom p-4 mb-4 bg-white">
                    <h5 class="fw-bold text-primary mb-3">📋 Sosyal İnceleme & Kamera / Belge Analizi</h5>
                    <form method="POST" enctype="multipart/form-data">
                        <div class="mb-3">
                            <label class="form-label small fw-bold text-secondary">Vatandaş Adı Soyadı / Hane:</label>
                            <input type="text" class="form-control" name="ad_soyad" placeholder="Örn: Ahmet Yılmaz" required>
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-bold text-secondary">Hane Kişi Sayısı:</label>
                            <input type="number" class="form-control" name="kisi_sayisi" value="3" required>
                        </div>
                        
                        <div class="mb-3 p-3 border rounded bg-light">
                            <label class="form-label small fw-bold text-dark">📷 Rapor Kağıdı Fotoğrafı Çek / Yükle (İsteğe Bağlı):</label>
                            <input type="file" class="form-control" name="rapor_dosyasi" accept="image/*" capture="environment">
                            <div class="form-text small text-muted">Bilgisayar çıktısı raporun fotoğrafını yüklerseniz sistem otomatik okur.</div>
                        </div>

                        <div class="mb-3">
                            <label class="form-label small fw-bold text-secondary">Veya Manuel Rapor Metni Yazın / Düzenleyin:</label>
                            <textarea class="form-control" name="rapor_metni" rows="4" placeholder="İsterseniz metni buraya da yazabilir veya fotoğraftan okunan metni buradan kontrol edebilirsiniz..."></textarea>
                        </div>

                        <button type="submit" name="action" value="evaluate" class="btn btn-primary-custom w-100 py-2 fw-bold text-white mb-2">🔍 Analiz Et ve Hesapla</button>
                    </form>
                </div>

                {% if result %}
                <div class="card card-custom p-4 bg-white border-start border-4 border-info">
                    <h5 class="fw-bold text-dark mb-3">📊 Analiz Sonuçları</h5>
                    <ul class="list-group list-group-flush mb-3">
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <strong>Toplam Hane Geliri:</strong> <span class="badge bg-secondary fs-6">{{ result.hane_geliri }}</span>
                        </li>
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <strong>Kişi Başı Gelir:</strong> <span class="badge bg-secondary fs-6">{{ result.kisi_basi_gelir }}</span>
                        </li>
                        <li class="list-group-item d-flex justify-content-between align-items-center">
                            <strong>Kira Tutarı:</strong> <span class="badge bg-secondary fs-6">{{ result.kira_tutari }}</span>
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
            rapor_metni = ""
            
            # Fotoğraf/Dosya yüklenmiş mi kontrol et
            file = request.files.get('rapor_dosyasi')
            if file and file.filename != '':
                try:
                    img = Image.open(file.stream)
                    # OCR ile görselden metni oku (Türkçe destekli)
                    extracted_text = pytesseract.image_to_string(img, lang='tur')
                    rapor_metni = extracted_text
                except Exception as e:
                    print("OCR Okuma Hatası:", e)
            
            # Eğer fotoğraf yüklenmemişse veya OCR boş döndüyse manuel yazılan metni al
            if not rapor_metni.strip():
                rapor_metni = request.form.get('rapor_metni', '')

            result = evaluate_and_calculate(request.form, rapor_metni)

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