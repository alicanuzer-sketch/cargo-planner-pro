import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import plotly.graph_objects as go
from dataclasses import dataclass
from typing import List
import io

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors as rl_colors

# ============================================================
# CONFIG & PROFESSIONAL STYLING
# ============================================================
st.set_page_config(page_title="Cargo Planner Pro", page_icon="📦", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .metric-card {
        background-color: #ffffff;
        padding: 18px;
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        border-top: 4px solid #0068C9;
        text-align: center;
    }
    .metric-title { font-size: 11px; color: #6c757d; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
    .metric-value { font-size: 22px; color: #1e293b; font-weight: 800; margin-top: 4px; }
    .stDownloadButton > button {
        width: 100%;
        border-radius: 8px;
        font-weight: 600;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🚢 Cargo Planner Pro - Yükleme Simülasyonu")
st.caption("Endüstriyel Özel Ekipman (Flat Rack & Open Top) Yük Planlama ve 3D Görselleştirme")

# ============================================================
# DATA MODELS & HAPAG REMARKS
# ============================================================
@dataclass
class Cargo:
    sku: str
    name: str
    length: float
    width: float
    height: float
    weight: float
    is_stackable: bool = True
    max_stack: int = 10

@dataclass
class Placement:
    sku: str
    name: str
    x: float; y: float; z: float
    l: float; w: float; h: float
    weight: float
    is_stackable: bool
    stack_layer: int
    max_stack: int

HAPAG_REMARKS = {
    "Flat Rack": [
        "📌 **Lashing Points:** Tüm kargolar Hapag-Lloyd lashing gözlerine min. 5T kapasiteli şerit/zincir ile sabitlenmelidir.",
        "📌 **OOG Clearance:** Taban genişliğini (2.43m) aşan yüklerde vinç/sapan elleçleme boşlukları dikkate alınmalıdır (Max Taşıma Limiti: 5.00m).",
        "📌 **Weight Distribution:** Ağır kargoların ağırlık merkezi konteyner tabanının ortasına %60 oranında yayılmalıdır.",
        "📌 **Bedding Requirements:** Noktasal yüksek ağırlıkta ahşap kalas (bedding) kullanımı zorunludur."
    ],
    "Open Top": [
        "📌 **Tarpaulin/Tente:** Yük yüksekliği profil sınırını (2.34m/2.65m) aşıyorsa tente örtülemez, OOG Top olarak bildirilmeli (Max Yükseklik Limiti: 5.00m).",
        "📌 **Roof Bows:** Tente çıtaları çıkarıldığında üst yapı rijitliği azalacağı için yan duvar lashing limitleri gözetilmelidir.",
        "📌 **Door Header:** Arka kapı üst kirişi (swivel header) sökülebilir, yükleme sonrası yerine takılmalıdır."
    ]
}

if 'c_list' not in st.session_state:
    st.session_state.c_list = [
        Cargo("10", "item 1", 2.00, 1.00, 1.50, 1000, False, 1),
        Cargo("11", "item 2", 10.23, 3.15, 2.65, 24800, False, 1)
    ]

# ============================================================
# PACKING ENGINE & HELPER FUNCTIONS
# ============================================================
def calculate_oog(x, y, z, cl, cw, ch, dl, dw, dh):
    return {
        "front": max(0.0, -x), "rear": max(0.0, (x + cl) - dl),
        "left": max(0.0, -y), "right": max(0.0, (y + cw) - dw), "top": max(0.0, (z + ch) - dh)
    }

def is_overlapping(p1: Placement, candidate_box):
    x2, y2, z2, l2, w2, h2 = candidate_box
    return not (
        p1.x + p1.l <= x2 + 0.0001 or x2 + l2 <= p1.x + 0.0001 or
        p1.y + p1.w <= y2 + 0.0001 or y2 + w2 <= p1.y + 0.0001 or
        p1.z + p1.h <= z2 + 0.0001 or z2 + h2 <= p1.z + 0.0001
    )

def is_valid_placement(pt_x, pt_y, pt_z, cl, cw, ch, dl, dw=2.43, max_oog_width=5.0):
    # KESİN SINIR KONTROLÜ: x + cl toplamı konteyner boyundan (dl) büyükse YASAK!
    if (pt_x + cl) > dl + 0.0001:
        return False

    if (pt_y + cw) > max_oog_width + 0.0001:
        return False

    return True

def check_stacking_validity(candidate_box, placements: List[Placement]):
    pt_x, pt_y, pt_z, cl, cw, ch = candidate_box
    if pt_z <= 0.01:
        return True, 1

    supporting_items = []
    for p in placements:
        overlap_x = min(pt_x + cl, p.x + p.l) - max(pt_x, p.x)
        overlap_y = min(pt_y + cw, p.y + p.w) - max(pt_y, p.y)
        if overlap_x > 0.05 and overlap_y > 0.05 and abs((p.z + p.h) - pt_z) <= 0.02:
            supporting_items.append(p)

    if not supporting_items:
        return False, 0

    max_layer_below = 0
    for item in supporting_items:
        if not item.is_stackable or item.stack_layer >= item.max_stack:
            return False, 0
        max_layer_below = max(max_layer_below, item.stack_layer)

    return True, max_layer_below + 1

def pack_cargo_3d(cargos: List[Cargo], dl: float, dw: float, dh: float, max_w: float, is_flat_rack: bool = True, allow_rotation=True):
    placements: List[Placement] = []
    unplaced = []
    current_weight = 0.0

    MAX_OOG_WIDTH = 5.00
    MAX_OOG_HEIGHT = 5.00
    allowed_max_w = MAX_OOG_WIDTH if is_flat_rack else dw

    # Kargoları Hacme (Boy x En x Yükseklik) göre büyükten küçüğe sıralıyoruz.
    # Böylece 10.23m boyundaki devasa kargo her zaman ILK olarak (x=0) noktasına yerleşir.
    sorted_cargos = sorted(cargos, key=lambda c: (c.length * c.width * c.height, c.weight), reverse=True)

    for cargo in sorted_cargos:
        if current_weight + cargo.weight > max_w or cargo.height > MAX_OOG_HEIGHT:
            unplaced.append(cargo)
            continue

        placed = False
        orientations = []
        if cargo.length <= dl + 0.0001 and cargo.width <= allowed_max_w + 0.0001:
            orientations.append((cargo.length, cargo.width))

        if allow_rotation and cargo.length != cargo.width:
            if cargo.width <= dl + 0.0001 and cargo.length <= allowed_max_w + 0.0001:
                orientations.append((cargo.width, cargo.length))

        if not orientations:
            unplaced.append(cargo)
            continue

        candidate_points = [(0.0, 0.0, 0.0)]
        for p in placements:
            candidate_points.extend([
                (p.x + p.l, p.y, p.z),
                (p.x, p.y + p.w, p.z),
                (p.x, p.y, p.z + p.h),
            ])

        # Koordinatları X (boy) öncelikli sırala
        candidate_points = sorted(set(candidate_points), key=lambda pt: (pt[0], pt[1], pt[2]))

        for pt_x, pt_y, pt_z in candidate_points:
            for cl, cw in orientations:
                # KESİN FİZİKSEL SINIR: x + kargo_boyu asla dl (11.60m) değerini geçemez!
                if (pt_x + cl) > dl + 0.0001:
                    continue

                if not is_valid_placement(pt_x, pt_y, pt_z, cl, cw, cargo.height, dl=dl, dw=dw, max_oog_width=allowed_max_w):
                    continue

                candidate_box = (pt_x, pt_y, pt_z, cl, cw, cargo.height)
                if any(is_overlapping(existing, candidate_box) for existing in placements):
                    continue

                stack_ok, layer_num = check_stacking_validity(candidate_box, placements)
                if not stack_ok:
                    continue

                placements.append(Placement(
                    cargo.sku, cargo.name, pt_x, pt_y, pt_z, cl, cw, cargo.height, cargo.weight,
                    cargo.is_stackable, layer_num, cargo.max_stack
                ))
                current_weight += cargo.weight
                placed = True
                break
            if placed:
                break

        if not placed:
            unplaced.append(cargo)

    return placements, unplaced

def pack_multi_container(cargos: List[Cargo], dl: float, dw: float, dh: float, max_w: float, is_flat_rack: bool = True, allow_rotation=True):
    containers = []
    remaining_cargos = cargos.copy()

    while len(remaining_cargos) > 0:
        placements, unplaced = pack_cargo_3d(remaining_cargos, dl, dw, dh, max_w, is_flat_rack, allow_rotation)
        if not placements:
            st.error(f"⚠️ Konteynere Sığmayan Yükler: {[c.name for c in unplaced]}")
            break
        containers.append(placements)
        remaining_cargos = unplaced

    return containers

# ============================================================
# DRAWING & EXPORT ENGINE
# ============================================================
def create_2d_figure(placements: List[Placement], dl: float, dw: float, dh: float, max_len_used: float):
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 9))
    colors = ['#0068C9', '#FF4B4B', '#29B09D', '#774294', '#FF8700', '#00D4FF', '#E63946', '#457B9D']

    ax1.set_title("TOP VIEW (Üstten Görünüm)", fontsize=10, fontweight='bold')
    ax1.add_patch(patches.Rectangle((0, 0), dl, dw, color='#e2e8f0', alpha=0.5))
    
    ax2.set_title("SIDE VIEW (Yandan Görünüm)", fontsize=10, fontweight='bold')
    ax2.add_patch(patches.Rectangle((0, 0), dl, dh, color='#e2e8f0', alpha=0.5))
    
    ax3.set_title("FRONT VIEW (Önden Görünüm)", fontsize=10, fontweight='bold')
    ax3.add_patch(patches.Rectangle((0, 0), dw, dh, color='#e2e8f0', alpha=0.5))

    for idx, p in enumerate(placements):
        c_color = colors[idx % len(colors)]
        ax1.add_patch(patches.Rectangle((p.x, p.y), p.l, p.w, edgecolor='black', facecolor=c_color, alpha=0.75, linewidth=1))
        ax1.text(p.x + p.l/2, p.y + p.w/2, f"{p.sku}\n{p.name}", ha='center', va='center', color='white', fontweight='bold', fontsize=7)

        ax2.add_patch(patches.Rectangle((p.x, p.z), p.l, p.h, edgecolor='black', facecolor=c_color, alpha=0.75, linewidth=1))
        ax2.text(p.x + p.l/2, p.z + p.h/2, f"{p.sku}", ha='center', va='center', color='white', fontweight='bold', fontsize=7)

        ax3.add_patch(patches.Rectangle((p.y, p.z), p.w, p.h, edgecolor='black', facecolor=c_color, alpha=0.5, linewidth=1))
        ax3.text(p.y + p.w/2, p.z + p.h/2, f"{p.sku}", ha='center', va='center', color='black', fontweight='bold', fontsize=7)

    max_x_bound = max(dl + 0.5, max_len_used + 0.5)
    max_y_bound = max(dw + 0.5, max([p.y + p.w for p in placements] + [dw]) + 0.5) if placements else dw + 0.5
    max_z_bound = max(dh + 0.5, max([p.z + p.h for p in placements] + [dh]) + 0.5) if placements else dh + 0.5

    ax1.set_xlim(-0.5, max_x_bound); ax1.set_ylim(-0.5, max_y_bound); ax1.grid(True, linestyle=':', alpha=0.5)
    ax2.set_xlim(-0.5, max_x_bound); ax2.set_ylim(-0.5, max_z_bound); ax2.grid(True, linestyle=':', alpha=0.5)
    ax3.set_xlim(-0.5, max_y_bound); ax3.set_ylim(-0.5, max_z_bound); ax3.grid(True, linestyle=':', alpha=0.5)
    
    plt.tight_layout()
    return fig

def render_3d_plotly(placements: List[Placement], dl: float, dw: float, dh: float):
    fig = go.Figure()
    colors = ['#0068C9', '#FF4B4B', '#29B09D', '#774294', '#FF8700', '#00D4FF', '#E63946', '#457B9D']

    # Konteyner Taban Çerçevesi
    fig.add_trace(go.Scatter3d(
        x=[0, dl, dl, 0, 0, 0, dl, dl, 0, 0, 0, 0, dl, dl, dl, dl],
        y=[0, 0, dw, dw, 0, 0, 0, dw, dw, 0, dw, dw, dw, 0, 0, dw],
        z=[0, 0, 0, 0, 0, dh, dh, dh, dh, dh, 0, dh, dh, dh, 0, 0],
        mode='lines', line=dict(color='#334155', width=4), name='Container Frame'
    ))

    for idx, p in enumerate(placements):
        c_color = colors[idx % len(colors)]

        x_pts = [p.x, p.x+p.l, p.x+p.l, p.x, p.x, p.x+p.l, p.x+p.l, p.x]
        y_pts = [p.y, p.y, p.y+p.w, p.y+p.w, p.y, p.y, p.y+p.w, p.y+p.w]
        z_pts = [p.z, p.z, p.z, p.z, p.z+p.h, p.z+p.h, p.z+p.h, p.z+p.h]

        i_ind = [0, 0, 4, 4, 0, 0, 3, 3, 0, 1, 1, 2]
        j_ind = [1, 2, 5, 6, 1, 5, 2, 6, 3, 2, 5, 6]
        k_ind = [2, 3, 6, 7, 5, 4, 6, 7, 7, 6, 6, 7]

        fig.add_trace(go.Mesh3d(
            x=x_pts, y=y_pts, z=z_pts,
            i=i_ind, j=j_ind, k=k_ind,
            color=c_color, opacity=0.85, name=f"SKU {p.sku}: {p.name}",
            flatshading=True,
            hoverinfo="text",
            hovertext=f"<b>{p.name}</b> (SKU: {p.sku})<br>Boyut: {p.l:.2f} x {p.w:.2f} x {p.h:.2f} m<br>Ağırlık: {p.weight} kg"
        ))

    fig.update_layout(
        scene=dict(
            xaxis=dict(title='Uzunluk / X (m)', range=[0, max(dl, 12)]),
            yaxis=dict(title='Genişlik / Y (m)', range=[0, 5]),
            zaxis=dict(title='Yükseklik / Z (m)', range=[0, 5]),
            aspectmode='data'
        ),
        margin=dict(l=0, r=0, b=0, t=10), height=550
    )
    return fig

def generate_excel(all_containers_manifest, eq_type):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary_rows = []
        for c_idx, df_manifest in enumerate(all_containers_manifest):
            summary_rows.append({
                "Container": f"Konteyner #{c_idx+1}",
                "Equipment": eq_type,
                "Total Items": len(df_manifest),
                "Total Cargo Weight (kg)": df_manifest["Weight (kg)"].sum()
            })
            df_manifest.to_excel(writer, sheet_name=f'Container_{c_idx+1}', index=False)
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name='Summary', index=False)
    return output.getvalue()

def generate_pdf(df_report, fig_2d, eq_type, len_util, total_w, c_num, remarks_list):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=15, leading=18, textColor=rl_colors.HexColor('#0068C9'))
    
    story.append(Paragraph(f"Cargo Planner Pro - Loading Plan (Container #{c_num})", title_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>Equipment:</b> {eq_type} | <b>Length Utilization:</b> {len_util:.1f}% | <b>Total Cargo Weight:</b> {total_w:,.0f} kg", styles['Normal']))
    story.append(Spacer(1, 6))
    
    img_buf = io.BytesIO()
    fig_2d.savefig(img_buf, format='png', dpi=150, bbox_inches='tight')
    img_buf.seek(0)
    story.append(Image(img_buf, width=540, height=280))
    story.append(Spacer(1, 6))

    table_data = [df_report.columns.tolist()] + df_report.values.tolist()
    t = Table(table_data)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), rl_colors.HexColor('#0068C9')),
        ('TEXTCOLOR', (0,0), (-1,0), rl_colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('BOTTOMPADDING', (0,0), (-1,0), 3),
        ('BACKGROUND', (0,1), (-1,-1), rl_colors.HexColor('#F8F9FA')),
        ('GRID', (0,0), (-1,-1), 0.5, rl_colors.grey),
        ('FONTSIZE', (0,1), (-1,-1), 7),
    ]))
    story.append(t)
    
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>Hapag-Lloyd Operational & Lashing Remarks:</b>", styles['Heading3']))
    for r in remarks_list:
        clean_r = r.replace("**", "").replace("📌 ", "• ")
        story.append(Paragraph(clean_r, styles['Normal']))

    doc.build(story)
    return buffer.getvalue()

# ============================================================
# AŞAMA 1: KARGO LİSTESİ
# ============================================================
with st.expander("📦 Kargo Listesini Düzenle / Yeni Ekle / Excel Yükle", expanded=True):
    col_tab, col_add = st.columns([2.5, 1])
    
    with col_tab:
        st.markdown("##### 📝 Canlı Kargo Listesi")
        st.caption("Tablodaki değerleri doğrudan değiştirebilir, solundaki kutucukla satır seçip **Delete** ile silebilirsiniz.")
        
        if st.session_state.c_list:
            df_current = pd.DataFrame([
                {
                    "SKU": c.sku,
                    "Name": c.name,
                    "Length (cm)": int(c.length * 100),
                    "Width (cm)": int(c.width * 100),
                    "Height (cm)": int(c.height * 100),
                    "Weight (kg)": c.weight,
                    "Stackable": c.is_stackable,
                    "Max Stack": c.max_stack
                } for c in st.session_state.c_list
            ])

            edited_df = st.data_editor(
                df_current,
                num_rows="dynamic",
                key="main_cargo_editor",
                height=230
            )

            updated_c_list = []
            for _, row in edited_df.iterrows():
                if pd.notnull(row['SKU']) and str(row['SKU']).strip() != "":
                    updated_c_list.append(Cargo(
                        sku=str(row['SKU']),
                        name=str(row['Name']),
                        length=float(row['Length (cm)']) / 100.0,
                        width=float(row['Width (cm)']) / 100.0,
                        height=float(row['Height (cm)']) / 100.0,
                        weight=float(row['Weight (kg)']),
                        is_stackable=bool(row['Stackable']),
                        max_stack=int(row['Max Stack'])
                    ))
            st.session_state.c_list = updated_c_list

    with col_add:
        st.markdown("##### ➕ Hızlı Tek Kargo Ekle")
        with st.form("quick_add_form", clear_on_submit=True):
            f_sku = st.text_input("SKU / ID", f"{len(st.session_state.c_list) + 10}")
            f_name = st.text_input("Kargo Adı", f"Cargo-{f_sku}")
            c1, c2 = st.columns(2)
            with c1:
                f_l = st.number_input("Boy (cm)", value=200)
                f_h = st.number_input("Yük. (cm)", value=150)
            with c2:
                f_w = st.number_input("En (cm)", value=100)
                f_wt = st.number_input("Ağırlık (kg)", value=1000)
            
            f_stack = st.checkbox("Üst Üste İstiflenebilir", value=True)
            
            if st.form_submit_button("Listeye Ekle"):
                st.session_state.c_list.append(Cargo(f_sku, f_name, f_l/100.0, f_w/100.0, f_h/100.0, f_wt, f_stack, 5))
                st.rerun()

        uploaded_file = st.file_uploader("Veya Excel/CSV Dosyası Yükle", type=["xlsx", "csv"])
        if uploaded_file is not None:
            try:
                df_up = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
                st.session_state.c_list = [
                    Cargo(
                        str(row['SKU']), str(row['Name']), 
                        float(row['Length_m']), float(row['Width_m']), float(row['Height_m']), 
                        float(row['Weight_kg']),
                        bool(row.get('Is_Stackable', True)),
                        int(row.get('Max_Stack', 10))
                    )
                    for _, row in df_up.iterrows()
                ]
                st.success("Excel başarıyla aktarıldı!")
                st.rerun()
            except Exception as e:
                st.error(f"Format Hatası: {e}")

# ============================================================
# AŞAMA 2: YATAY AYARLAR & HAPAG PAYLOAD VE NOTLAR
# ============================================================
st.markdown("---")
ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 2])

with ctrl1:
    eq_type = st.selectbox(
        "🚛 Ekipman Tipi Seçiniz",
        [
            "20ft Flat Rack",
            "40ft Standard Flat Rack",
            "40ft High Cube Flat Rack",
            "20ft Standard Open Top",
            "40ft Standard Open Top",
            "40ft High Cube Open Top"
        ]
    )
    
    is_flat_rack = "Flat Rack" in eq_type

    if eq_type == "20ft Flat Rack":
        dl, dw, dh, max_w = 5.50, 2.43, 2.20, 31000.0
    elif eq_type == "40ft Standard Flat Rack":
        dl, dw, dh, max_w = 11.60, 2.43, 1.92, 39000.0
    elif eq_type == "40ft High Cube Flat Rack":
        dl, dw, dh, max_w = 11.60, 2.43, 2.25, 39000.0
    elif eq_type == "20ft Standard Open Top":
        dl, dw, dh, max_w = 5.33, 2.23, 2.34, 28100.0
    elif eq_type == "40ft Standard Open Top":
        dl, dw, dh, max_w = 11.55, 2.23, 2.34, 26500.0
    elif eq_type == "40ft High Cube Open Top":
        dl, dw, dh, max_w = 11.55, 2.19, 2.65, 26200.0

with ctrl2:
    allow_rot = st.checkbox("🔄 Kargoları 90° Döndürmeye İzin Ver", value=True)
    st.caption("En/Boy optimizasyonu için kargolar otomatik çevrilir.")

containers = pack_multi_container(st.session_state.c_list, dl, dw, dh, max_w, is_flat_rack=is_flat_rack, allow_rotation=allow_rot)

with ctrl3:
    st.metric("Gerekli Toplam Konteyner", f"{len(containers)} Adet")

eq_category = "Flat Rack" if is_flat_rack else "Open Top"
current_remarks = HAPAG_REMARKS[eq_category]

with st.expander(f"📋 Hapag-Lloyd {eq_category} Operasyonel & Lashing Notları", expanded=True):
    for r in current_remarks:
        st.markdown(r)

# ============================================================
# AŞAMA 3: SİMÜLASYON VE RAPORLAMA EKRANI
# ============================================================
if containers:
    tab_titles = [f"📦 Konteyner #{idx+1}" for idx, c in enumerate(containers)]
    container_tabs = st.tabs(tab_titles)
    all_manifests = []

    for idx, placements in enumerate(containers):
        with container_tabs[idx]:
            total_w = sum(p.weight for p in placements)
            max_len_used = max([p.x + p.l for p in placements]) if placements else 0.0
            len_util = (max_len_used / dl) * 100 if dl > 0 else 0
            
            m1, m2, m3, m4 = st.columns(4)
            with m1: st.markdown(f'<div class="metric-card"><div class="metric-title">Uzunluk Doluluğu</div><div class="metric-value">%{len_util:.1f}</div></div>', unsafe_allow_html=True)
            with m2: st.markdown(f'<div class="metric-card"><div class="metric-title">Toplam Yük Ağırlığı</div><div class="metric-value">{total_w:,.0f} KG</div></div>', unsafe_allow_html=True)
            with m3: st.markdown(f'<div class="metric-card"><div class="metric-title">MAX ALLOWED PAYLOAD</div><div class="metric-value">{max_w:,.0f} KG</div></div>', unsafe_allow_html=True)
            with m4:
                report_data = []
                for p in placements:
                    oog = calculate_oog(p.x, p.y, p.z, p.l, p.w, p.h, dl, dw, dh)
                    is_oog = "Yes" if any(v > 0 for v in oog.values()) else "No"
                    report_data.append({
                        "SKU": p.sku, "Name": p.name, "X (m)": round(p.x, 2), "Y (m)": round(p.y, 2), "Z (m)": round(p.z, 2),
                        "Length (cm)": int(p.l*100), "Width (cm)": int(p.w*100), "Height (cm)": int(p.h*100),
                        "Weight (kg)": p.weight, "Stackable": "Yes" if p.is_stackable else "No", "Layer": p.stack_layer, "OOG?": is_oog
                    })
                df_manifest = pd.DataFrame(report_data)
                all_manifests.append(df_manifest)

                try:
                    fig_2d = create_2d_figure(placements, dl, dw, dh, max_len_used)
                    pdf_data = generate_pdf(df_manifest, fig_2d, eq_type, len_util, total_w, idx+1, current_remarks)
                    st.download_button(
                        label=f"📄 Konteyner #{idx+1} PDF Raporu İndir",
                        data=pdf_data,
                        file_name=f"container_{idx+1}_manifest.pdf",
                        mime="application/pdf",
                        key=f"pdf_btn_{idx}"
                    )
                except Exception as e:
                    st.error("PDF oluşturulamadı")

            st.markdown("<br>", unsafe_allow_html=True)

            v_tab1, v_tab2, v_tab3 = st.tabs(["🧊 İnteraktif 3D Yükleme Modeli", "📐 2D Teknik Çizim Paftası", "📋 Yükleme Manifestosu & Koordinatlar"])
            
            with v_tab1:
                st.plotly_chart(render_3d_plotly(placements, dl, dw, dh), key=f"plotly_main_{idx}")
            
            with v_tab2:
                st.pyplot(fig_2d)

            with v_tab3:
                st.dataframe(df_manifest)

    st.markdown("---")
    excel_data = generate_excel(all_manifests, eq_type)
    st.download_button(
        label="📊 Tüm Konteynerlerin Detaylı Excel Raporunu İndir (.xlsx)",
        data=excel_data,
        file_name="cargo_planner_full_manifest.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
