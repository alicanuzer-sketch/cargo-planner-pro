import streamlit as st

# Sayfa Yapılandırması
st.set_page_config(
    page_title="Cargo Planner & OOG Checker",
    page_icon="📦",
    layout="wide"
)

# ==============================================================================
# VERİ YAPILARI & LİMİTLER
# ==============================================================================
EQUIPMENT_RULES = {
    "20GP": {"name": "20' Standard Dry", "max_len": 590, "max_width": 235, "max_height": 239, "type": "std"},
    "40GP": {"name": "40' Standard Dry", "max_len": 1203, "max_width": 235, "max_height": 239, "type": "std"},
    "40HC": {"name": "40' High Cube", "max_len": 1203, "max_width": 235, "max_height": 269, "type": "std"},
    "20OT": {"name": "20' Open Top", "max_len": 589, "max_width": 234, "max_height": 234, "type": "ot"},
    "40OT": {"name": "40' Open Top", "max_len": 1202, "max_width": 234, "max_height": 234, "type": "ot"},
    "20FR": {"name": "20' Flatrack", "oog_len": 563, "oog_width": 243, "oog_height": 221, "type": "fr"},
    "40FR_STD": {"name": "40' Standard Flatrack", "oog_len": 1160, "oog_width": 243, "oog_height": 192, "type": "fr"},
    "PLATFORM": {"name": "Platform", "max_len_overflow": 1160, "max_width_overflow": 216, "type": "plt"}
}

HAPAG_LLOYD_NOTES = [
    "Madde 16 - Hidrolik Sistemler: Hidrolikler sıfır seviyesine indirilmeden lashing yapılmamalıdır. 2 saat sonra tekrar kontrol edilmelidir.",
    "Madde 17 - Trafo Yüklemeleri: Azot tüpü basıncı >2 bar ise DG etiketlemesi yapılmalıdır. Gösterge okunabilir olmalıdır.",
    "Madde 18 - Araç & İş Makinesi: Akü kutup başları sökülmeli, depoda yakıt olmadığı belgelenmelidir.",
    "Madde 19/20 - Flatrack: En fazla 4 parça yüklenebilir. Yükler kasa yapılarak sabitlenmelidir.",
    "Madde 21 - Cam İçerik: Temperli olmayan cam yüzeyler strafor veya kontrplak ile kapatılmalıdır.",
    "Madde 22 - Platform: Önden/arkadan taşan yüklerde genişlik 216 cm'yi geçemez."
]

def check_cargo(equipment_code, cargo_len, cargo_width, cargo_height):
    eq = EQUIPMENT_RULES.get(equipment_code)
    if not eq:
        return {"is_oog": False, "warnings": ["Hata: Tanımsız ekipman kuralı."]}

    oog_status = []
    eq_type = eq.get("type")

    if eq_type == "fr":
        if cargo_len > eq["oog_len"]:
            oog_status.append(f"Boydan Taşma (Over Length) - Dikme Dışı (> {eq['oog_len']} cm)")
        if cargo_width > eq["oog_width"]:
            oog_status.append(f"Enden Taşma (Over Width) (> {eq['oog_width']} cm)")
        if cargo_height > eq["oog_height"]:
            oog_status.append(f"Yüksekten Taşma (Over Height) (> {eq['oog_height']} cm)")

    elif eq_type == "plt":
        if cargo_len > eq["max_len_overflow"] and cargo_width > eq["max_width_overflow"]:
            oog_status.append(f"Hapag Madde 22 İhlali: Taşmalı yüklerde genişlik {eq['max_width_overflow']} cm'yi geçemez!")

    elif eq_type == "ot":
        if cargo_len > eq["max_len"]: oog_status.append("Uzunluk Kapasitesi Aşıldı")
        if cargo_width > eq["max_width"]: oog_status.append("Genişlik Kapasitesi Aşıldı")
        if cargo_height > eq["max_height"]: oog_status.append(f"Üstten Taşma (Over Height - Open Top) (> {eq['max_height']} cm)")

    else:
        if cargo_len > eq["max_len"]: oog_status.append("Uzunluk Sınırı Aşıldı")
        if cargo_width > eq["max_width"]: oog_status.append("Genişlik Sınırı Aşıldı")
        if cargo_height > eq["max_height"]: oog_status.append("Yükseklik Sınırı Aşıldı")

    return {
        "is_oog": len(oog_status) > 0,
        "warnings": oog_status if oog_status else ["Kargo standart iç ölçülere uygundur (Taşma Yok)."]
    }

# ==============================================================================
# ARAYÜZ
# ==============================================================================
st.title("📦 Cargo Planner & OOG Kontrol Sistemi")

col1, col2 = st.columns(2)

with col1:
    selected_eq = st.selectbox(
        "Ekipman Tipi Seçiniz",
        options=list(EQUIPMENT_RULES.keys()),
        format_func=lambda x: EQUIPMENT_RULES[x]["name"]
    )
    cargo_len = st.number_input("Kargo Uzunluğu (cm)", min_value=1, value=1200)
    cargo_width = st.number_input("Kargo Genişliği (cm)", min_value=1, value=240)
    cargo_height = st.number_input("Kargo Yüksekliği (cm)", min_value=1, value=200)

with col2:
    st.subheader("Hesaplama Sonucu")
    if st.button("Kargoyu Denetle"):
        res = check_cargo(selected_eq, cargo_len, cargo_width, cargo_height)
        
        if res["is_oog"]:
            st.error("⚠️ OOG / TAŞMA TESPİT EDİLDİ")
            for w in res["warnings"]:
                st.write(f"- {w}")
        else:
            st.success("✅ YÜKLEME UYGUN")
            st.write(res["warnings"][0])

st.divider()

# Hapag-Lloyd Bilgilendirme Notları
with st.expander("📌 Hapag-Lloyd Özel Yükleme ve Lashing Kuralları"):
    for note in HAPAG_LLOYD_NOTES:
        st.markdown(f"- {note}")
