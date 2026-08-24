# ==============================================================================
# KONTEYNER VE OOG (OUT OF GAUGE) KONTROL MOTORU
# ==============================================================================

EQUIPMENT_RULES = {
    # Standard Dry / Box Containers (Kapalı Sistem)
    "20GP": {"max_len": 590, "max_width": 235, "max_height": 239, "is_open": False},
    "40GP": {"max_len": 1203, "max_width": 235, "max_height": 239, "is_open": False},
    "40HC": {"max_len": 1203, "max_width": 235, "max_height": 269, "is_open": False},
    
    # Open Top Containers (Üstü Açılabilir)
    "20OT": {"max_len": 589, "max_width": 234, "max_height": 234, "is_open": True, "top_open": True},
    "40OT": {"max_len": 1202, "max_width": 234, "max_height": 234, "is_open": True, "top_open": True},
    
    # Flatrack Containers (Taban + Dikme Limitli)
    "20FR": {"oog_len": 563, "oog_width": 243, "oog_height": 221, "is_flatrack": True},
    "40FR_STD": {"oog_len": 1160, "oog_width": 243, "oog_height": 192, "is_flatrack": True},
    
    # Platform (Dikmesiz / Açık Taban)
    "PLATFORM": {"max_len_front_back_overflow": 1160, "max_width_front_back_overflow": 216, "is_platform": True}
}

HAPAG_LLOYD_LASHING_NOTES = [
    "Madde 16 - Hidrolik Sistemler: Hidrolikler sıfır seviyesine indirilmeden lashing yapılmamalıdır. Lashing'den 2 saat sonra bağlantılar tekrar kontrol edilmelidir. Hidrolik ayaklar kirişlere basmıyorsa takozlama yapılmalıdır.",
    "Madde 17 - Trafo Yüklemeleri: Azot tüpü basıncı >2 bar ise DG (Tehlikeli Yük) etiketlemesi yapılmalıdır. Basınç göstergesi okunabilir pozisyonda olmalıdır.",
    "Madde 18 - Araç & İş Makinesi: Akü kutup başları sökülmeli, depoda yakıt olmadığı belgelenmelidir. Aksi halde DG prosedürleri uygulanır.",
    "Madde 19/20 - Flatrack Yükleme: En fazla 4 parça yüklenebilir. Parçaların üzerine çok katlı/yekpare ek yükleme yapılamaz. Yükler kasa yapılarak sabitlenmelidir.",
    "Madde 21 - Cam İçeren Yükler: Temperli olmayan cam yüzeyler strafor veya kontrplak ile darbelere karşı korumaya alınmalıdır.",
    "Madde 22 - Platform Yüklemeleri: Önden ve arkadan taşma yapan yüklerde genişlik 216 cm'yi geçmemelidir."
]

def check_cargo_compatibility(equipment_code, cargo_len, cargo_width, cargo_height):
    """
    Kargo ölçülerini (cm) seçilen ekipman limitlerine göre denetler.
    """
    eq = EQUIPMENT_RULES.get(equipment_code)
    if not eq:
        return {"status": "ERROR", "message": "Geçersiz ekipman kodu!"}

    oog_status = []
    
    # Flatrack Kontrolü
    if eq.get("is_flatrack"):
        if cargo_len > eq["oog_len"]:
            oog_status.append(f"Boydan Taşma (Over Length) - Limitsiz/Dikme Dışı (> {eq['oog_len']} cm)")
        if cargo_width > eq["oog_width"]:
            oog_status.append(f"Enden Taşma (Over Width) (> {eq['oog_width']} cm)")
        if cargo_height > eq["oog_height"]:
            oog_status.append(f"Yüksekten Taşma (Over Height) (> {eq['oog_height']} cm)")
            
    # Platform Kontrolü (Hapag Madde 22 kuralı entegre)
    elif eq.get("is_platform"):
        if cargo_len > eq["max_len_front_back_overflow"] and cargo_width > eq["max_width_front_back_overflow"]:
            oog_status.append(f"Hapag Madde 22 İhlali: Önden/arkadan taşan yüklerde genişlik {eq['max_width_front_back_overflow']} cm'yi geçemez!")
            
    # Standard / Open Top Kontrolü
    else:
        if cargo_len > eq["max_len"]:
            oog_status.append("Uzunluk Kapasitesi Aşıldı")
        if cargo_width > eq["max_width"]:
            oog_status.append("Genişlik Kapasitesi Aşıldı")
        if cargo_height > eq["max_height"]:
            if eq.get("top_open"):
                oog_status.append(f"Üstten Taşma (Over Height - Open Top) (> {eq['max_height']} cm)")
            else:
                oog_status.append("Yükseklik Kapasitesi Aşıldı")

    return {
        "equipment": equipment_code,
        "is_oog": len(oog_status) > 0,
        "warnings": oog_status if oog_status else ["Kargo standart ölçüler dahilindedir."],
        "lashing_info_notes": HAPAG_LLOYD_LASHING_NOTES
    }

# --- ÖRNEK TEST ---
# 40 Flatrack için: 1200 cm uzunluk, 240 cm genişlik, 200 cm yükseklik testi
test_result = check_cargo_compatibility("40FR_STD", cargo_len=1200, cargo_width=240, cargo_height=200)

print(f"Ekipman: {test_result['equipment']}")
print(f"OOG Durumu: {test_result['is_oog']}")
print("Uyarılar:", test_result['warnings'])
