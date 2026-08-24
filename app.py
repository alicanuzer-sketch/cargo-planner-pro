import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import plotly.graph_objects as go
from dataclasses import dataclass
from typing import List, Dict, Tuple
import io

# ReportLab kütüphaneleri (PDF üretimi için)
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors as rl_colors

# ============================================================
# CONFIG & STYLE
# ============================================================
st.set_page_config(page_title="Cargo Planner Pro", page_icon="📦", layout="wide")

st.markdown("""
    <style>
    .metric-card {
        background-color: #f8f9fa; padding: 15px; border-radius: 8px;
        border-left: 5px solid #0068C9; margin-bottom: 10px;
    }
    .metric-title { font-size: 11px; color: #6c757d; font-weight: bold; }
    .metric-value { font-size: 18px; color: #212529; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

st.title("🚢 Project Logistics Loading Planner")
st.caption("Cargo-Planner style professional OOG Multi-View, Multi-Container & Stacking Rules")

# ============================================================
# DATA MODELS
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
    max_stack: int = 10  # Maksimum üst üste kat sayısı

@dataclass
class Placement:
    sku: str
    name: str
    x: float; y: float; z: float
    l: float; w: float; h: float
    weight: float
    is_stackable: bool
    stack_layer: int  # Hangi kat seviyesinde durduğu

# ============================================================
# INITIALIZE STATE
# ============================================================
if 'c_list' not in st.session_state:
    st.session_state.c_list = [
        Cargo("10", "Main Machine", 3.50, 1.20, 1.70, 2200, False, 1),
        Cargo("13", "Transformer Box", 4.90, 1.10, 2.20, 8000, False, 1),
        Cargo("7", "Control Unit", 3.50, 1.00, 1.20, 2100, True, 2),
        Cargo("15", "Accessory Kit", 0.90, 0.90, 0.55, 180, True, 4),
        Cargo("16", "Extra Box", 1.20, 0.80, 0.80, 350, True, 3)
    ]

# ============================================================
# PACKING ENGINE
# ============================================================
def calculate_oog(x, y, z, cl, cw, ch, dl, dw, dh):
    return {
        "front": max(0.0, -x), "rear": max(0.0, (x + cl) - dl),
        "left": max(0.0, -y), "right": max(0.0, (y + cw) - dw), "top": max(0.0, (z + ch) - dh)
    }

def is_overlapping(p1: Placement, p2_bounds):
    x2, y2, z2, l2, w2, h2 = p2_bounds
    return not (
        p1.x + p1.l <= x2 or x2 + l2 <= p1.x or
        p1.y + p1.w <= y2 or y2 + w2 <= p1.y or
        p1.z + p1.h <= z2 or z2 + h2 <= p1.z
    )

def check_stacking_validity(candidate_box, placements: List[Placement]):
    """İstifleme limitlerini ve üst üste koyma iznini denetler."""
    pt_x, pt_y, pt_z, cl, cw, ch = candidate_box
    
    # Z=0 (Zemin) ise her zaman yerleşebilir
    if pt_z <= 0.001:
        return True, 1

    # Altında kalan kutuları bul
    supporting_items = []
    for p in placements:
        # X ve Y eksenlerinde çakışma/temas var mı?
        overlap_x = max(0.0, min(pt_x + cl, p.x + p.l) - max(pt_x, p.x))
        overlap_y = max(0.0, min(pt_y + cw, p.y + p.w) - max(pt_y, p.y))
        
        # Tam alt yüzeyde durup durmadığını kontrol et
        if overlap_x > 0.01 and overlap_y > 0.01 and abs((p.z + p.h) - pt_z) < 0.001:
            supporting_items.append(p)

    if not supporting_items:
        return False, 0

    # Altındaki her kargonun istiflenebilir olması ve max kat sınırını aşmaması gerekir
    max_layer_below = 0
    for item in supporting_items:
        if not item.is_stackable:
            return False, 0
        if item.stack_layer >= item.max_stack:
            return False, 0
        max_layer_below = max(max_layer_below, item.stack_layer)

    return True, max_layer_below + 1

def pack_cargo_3d(cargos: List[Cargo], dl: float, dw: float, dh: float, max_w: float, allow_rotation=True):
    placements: List[Placement] = []
    unplaced = []
    current_weight = 0.0

    # İstiflenemeyen ve ağır malzemelere öncelik ver (Tabana önce koyulmaları için)
    sorted_cargos = sorted(cargos, key=lambda c: (not c.is_stackable, c.weight, c.length * c.width * c.height), reverse=True)

    for cargo in sorted_cargos:
        # Ağırlık sınırı kontrolü
        if current_weight + cargo.weight > max_w:
            unplaced.append(cargo)
            continue

        placed = False
        orientations = [(cargo.length, cargo.width)]
        if allow_rotation and cargo.length != cargo.width:
            orientations.append((cargo.width, cargo.length))

        candidate_points = [(0.0, 0.0, 0.0)]
        for p in placements:
            candidate_points.extend([
                (p.x + p.l, p.y, p.z),
                (p.x, p.y + p.w, p.z),
                (p.x, p.y, p.z + p.h),
            ])

        candidate_points = sorted(set(candidate_points), key=lambda pt: (pt[2], pt[0], pt[1]))

        for pt_x, pt_y, pt_z in candidate_points:
            for cl, cw in orientations:
                if pt_y + cw > dw + 0.01 and dw > 0:
                    continue
                
                candidate_box = (pt_x, pt_y, pt_z, cl, cw, cargo.height)
                
                # Çakışma kontrolü
                if any(is_overlapping(existing, candidate_box) for existing in placements):
                    continue

                # İstifleme kuralı kontrolü (Max Stack & Can Stack)
                stack_ok, layer_num = check_stacking_validity(candidate_box, placements)
                if not stack_ok:
                    continue

                # Yerleştir
                placements.append(Placement(
                    cargo.sku, cargo.name, pt_x, pt_y, pt_z, cl, cw, cargo.height, cargo.weight,
                    cargo.is_stackable, layer_num
                ))
                current_weight += cargo.weight
                placed = True
                break
            if placed:
                break

        if not placed:
            unplaced.append(cargo)

    return placements, unplaced

def pack_multi_container(cargos: List[Cargo], dl: float, dw: float, dh: float, max_w: float, allow_rotation=True):
    """Sığmayan kargoları yeni konteynerlere bölen döngüsel fonksiyon."""
    containers = []
    remaining_cargos = cargos.copy()

    while len(remaining_cargos) > 0:
        placements, unplaced = pack_cargo_3d(remaining_cargos, dl, dw, dh, max_w, allow_rotation)
        
        # Eğer bu konteynerde hiçbir eleman yerleştirilemediyse sonsuz döngüyü önle
        if not placements:
            st.error(f"⚠️ Şunlar hiçbir şekilde konteynere sığmıyor: {[c.name for c in unplaced]}")
            break
            
        containers.append(placements)
        remaining_cargos = unplaced

    return containers

# ============================================================
# MATPLOTLIB FIGURE GENERATOR
# ============================================================
def create_2d_figure(placements: List[Placement], dl: float, dw: float, dh: float, max_len_used: float):
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10))
    colors = ['#0068C9', '#FF4B4B', '#29B09D', '#774294', '#FF8700', '#00D4FF', '#E63946', '#457B9D']

    ax1.set_title("TOP VIEW (Üstten Görünüm)", fontsize=10, fontweight='bold')
    ax1.add_patch(patches.Rectangle((0, 0), dl, dw, color='lightgray', alpha=0.4))
    
    ax2.set_title("SIDE VIEW (Yandan Görünüm)", fontsize=10, fontweight='bold')
    ax2.add_patch(patches.Rectangle((0, 0), dl, dh, color='lightgray', alpha=0.4))
    
    ax3.set_title("FRONT VIEW (Önden Görünüm)", fontsize=10, fontweight='bold')
    ax3.add_patch(patches.Rectangle((0, 0), dw, dh, color='lightgray', alpha=0.4))

    for idx, p in enumerate(placements):
        c_color = colors[idx % len(colors)]
        ax1.add_patch(patches.Rectangle((p.x, p.y), p.l, p.w, edgecolor='black', facecolor=c_color, alpha=0.7, linewidth=1.2))
        ax1.text(p.x + p.l/2, p.y + p.w/2, f"SKU {p.sku}", ha='center', va='center', color='white', fontweight='bold', fontsize=8)

        ax2.add_patch(patches.Rectangle((p.x, p.z), p.l, p.h, edgecolor='black', facecolor=c_color, alpha=0.7, linewidth=1.2))
        ax2.text(p.x + p.l/2, p.z + p.h/2, f"SKU {p.sku}", ha='center', va='center', color='white', fontweight='bold', fontsize=8)

        ax3.add_patch(patches.Rectangle((p.y, p.z), p.w, p.h, edgecolor='black', facecolor='none', linestyle='--', linewidth=1.2))
        ax3.add_patch(patches.Rectangle((p.y, p.z), p.w, p.h, facecolor=c_color, alpha=0.4))
        ax3.text(p.y + p.w/2, p.z + p.h/2, f"SKU {p.sku}", ha='center', va='center', color='black', fontweight='bold', fontsize=8)

    max_x_bound = max(dl + 2, max_len_used + 2)
    max_y_bound = max([dw + 2] + [p.y + p.w + 1 for p in placements]) if placements else dw + 2
    min_y_bound = min([-1.0] + [p.y - 1 for p in placements]) if placements else -1.0
    max_z_bound = max([dh + 2] + [p.z + p.h + 1 for p in placements]) if placements else dh + 2

    ax1.set_xlim(-1, max_x_bound); ax1.set_ylim(min_y_bound, max_y_bound); ax1.grid(True, linestyle='--', alpha=0.4)
    ax2.set_xlim(-1, max_x_bound); ax2.set_ylim(-0.5, max_z_bound); ax2.grid(True, linestyle='--', alpha=0.4)
    ax3.set_xlim(min_y_bound, max_y_bound); ax3.set_ylim(-0.5, max_z_bound); ax3.grid(True, linestyle='--', alpha=0.4)
    
    plt.tight_layout()
    return fig

# ============================================================
# REPORT GENERATION FUNCTIONS (PDF & EXCEL)
# ============================================================
def generate_excel(all_containers_manifest, eq_type):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary_rows = []
        for c_idx, df_manifest in enumerate(all_containers_manifest):
            total_w = df_manifest["Weight (kg)"].sum()
            summary_rows.append({
                "Container": f"Konteyner #{c_idx+1}",
                "Equipment": eq_type,
                "Total Items": len(df_manifest),
                "Total Cargo Weight (kg)": total_w
            })
            df_manifest.to_excel(writer, sheet_name=f'Container_{c_idx+1}', index=False)
            
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name='Summary', index=False)
    return output.getvalue()

def generate_pdf(df_report, fig_2d, eq_type, len_util, total_w, c_num):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=25, leftMargin=25, topMargin=25, bottomMargin=25)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, leading=20, textColor=rl_colors.HexColor('#0068C9'))
    
    story.append(Paragraph(f"Project Logistics Loading Report - Container #{c_num}", title_style))
    story.append(Spacer(1, 8))
    
    summary_text = f"<b>Equipment:</b> {eq_type} | <b>Length Utilization:</b> {len_util:.1f}% | <b>Total Weight:</b> {total_w:,.0f} kg"
    story.append(Paragraph(summary_text, styles['Normal']))
    story.append(Spacer(1, 10))
    
    img_buf = io.BytesIO()
    fig_2d.savefig(img_buf, format='png', dpi=150, bbox_inches='tight')
    img_buf.seek(0)
    story.append(Image(img_buf, width=540, height=360))
    story.append(Spacer(1, 10))

    table_data = [df_report.columns.tolist()] + df_report.values.tolist()
    t = Table(table_data)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), rl_colors.HexColor('#0068C9')),
        ('TEXTCOLOR', (0,0), (-1,0), rl_colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('BOTTOMPADDING', (0,0), (-1,0), 4),
        ('BACKGROUND', (0,1), (-1,-1), rl_colors.HexColor('#F8F9FA')),
        ('GRID', (0,0), (-1,-1), 0.5, rl_colors.grey),
        ('FONTSIZE', (0,1), (-1,-1), 7),
    ]))
    story.append(t)
    
    doc.build(story)
    return buffer.getvalue()

# ============================================================
# PLOTLY 3D RENDER ENGINE
# ============================================================
def render_3d_plotly(placements: List[Placement], dl: float, dw: float, dh: float):
    fig = go.Figure()
    colors = ['#0068C9', '#FF4B4B', '#29B09D', '#774294', '#FF8700', '#00D4FF', '#E63946', '#457B9D']

    fig.add_trace(go.Scatter3d(
        x=[0, dl, dl, 0, 0, 0, dl, dl, 0, 0, 0, 0, dl, dl, dl, dl],
        y=[0, 0, dw, dw, 0, 0, 0, dw, dw, 0, dw, dw, dw, 0, 0, dw],
        z=[0, 0, 0, 0, 0, dh, dh, dh, dh, dh, 0, dh, dh, dh, 0, 0],
        mode='lines', line=dict(color='gray', width=4), name='Container Wireframe', hoverinfo='none'
    ))

    for idx, p in enumerate(placements):
        c_color = colors[idx % len(colors)]
        x_pts = [p.x, p.x+p.l, p.x+p.l, p.x, p.x, p.x+p.l, p.x+p.l, p.x]
        y_pts = [p.y, p.y, p.y+p.w, p.y+p.w, p.y, p.y, p.y+p.w, p.y+p.w]
        z_pts = [p.z, p.z, p.z, p.z, p.z+p.h, p.z+p.h, p.z+p.h, p.z+p.h]

        fig.add_trace(go.Mesh3d(
            x=x_pts, y=y_pts, z=z_pts,
            i=[7, 0, 0, 0, 4, 4, 6, 6, 4, 0, 3, 2],
            j=[3, 4, 1, 2, 5, 6, 5, 2, 0, 1, 6, 3],
            k=[0, 7, 5, 3, 6, 7, 1, 1, 1, 5, 7, 7],
            color=c_color, opacity=0.8, name=f"SKU {p.sku}: {p.name}",
            hoverinfo="text",
            hovertext=(
                f"<b>{p.name}</b><br>SKU: {p.sku}<br>"
                f"Konum (X,Y,Z): ({p.x:.2f}, {p.y:.2f}, {p.z:.2f}) m<br>"
                f"Boyut (BxGxY): {p.l:.2f} x {p.w:.2f} x {p.h:.2f} m<br>"
                f"Ağırlık: {p.weight:,.0f} kg<br>"
                f"İstiflenebilir: {'Evet' if p.is_stackable else 'Hayır'}<br>"
                f"Kat Seviyesi: {p.stack_layer}"
            )
        ))

    fig.update_layout(
        scene=dict(
            xaxis=dict(title='Uzunluk / X (m)', backgroundcolor="rgb(240, 240, 240)"),
            yaxis=dict(title='Genişlik / Y (m)', backgroundcolor="rgb(240, 240, 240)"),
            zaxis=dict(title='Yükseklik / Z (m)', backgroundcolor="rgb(240, 240, 240)"),
            aspectmode='data'
        ),
        margin=dict(l=0, r=0, b=0, t=30), height=550
    )
    return fig

# ============================================================
# STREAMLIT UI LAYOUT
# ============================================================
col_sidebar, col_main = st.columns([1, 3])

with col_sidebar:
    st.header("📋 Settings")
    eq_type = st.selectbox("Equipment Type", ["40ft Flat Rack", "20ft Flat Rack", "40ft Open Top"])
    
    if eq_type == "40ft Flat Rack":
        dl, dw, dh, max_w = 12.04, 2.43, 2.23, 40000.0
    elif eq_type == "20ft Flat Rack":
        dl, dw, dh, max_w = 5.63, 2.23, 2.20, 31000.0
    else:
        dl, dw, dh, max_w = 12.02, 2.35, 2.38, 28000.0

    allow_rot = st.checkbox("Kargo Döndürmeye İzin Ver (90° Rotation)", value=True)

    st.subheader("📁 Toplu Yükleme (Excel/CSV)")
    uploaded_file = st.file_uploader("Kargo Listesi Yükle", type=["xlsx", "csv"])
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
            st.success(f"✅ {len(df_up)} kargo eklendi!")
        except Exception as e:
            st.error(f"Hata: {e}")

    st.subheader("➕ Manuel Ekle")
    with st.form("cargo_form", clear_on_submit=True):
        sku = st.text_input("SKU / ID", f"{len(st.session_state.c_list) + 10}")
        name = st.text_input("Cargo Name", f"Item-{sku}")
        c_l = st.number_input("Length (cm)", value=200) / 100.0
        c_w = st.number_input("Width (cm)", value=100) / 100.0
        c_h = st.number_input("Height (cm)", value=150) / 100.0
        c_wt = st.number_input("Weight (kg)", value=1000)
        
        c_stackable = st.checkbox("Üst Üste Konulabilir (Stackable)", value=True)
        c_max_stack = st.number_input("Maksimum Kat Sayısı", min_value=1, max_value=10, value=5)
        
        if st.form_submit_button("Add to Load List"):
            st.session_state.c_list.append(Cargo(sku, name, c_l, c_w, c_h, c_wt, c_stackable, c_max_stack))
            st.rerun()

    if st.button("🗑️ Clear List", type="secondary"):
        st.session_state.c_list = []
        st.rerun()

# ============================================================
# RESULTS & DRAWINGS
# ============================================================
with col_main:
    containers = pack_multi_container(st.session_state.c_list, dl, dw, dh, max_w, allow_rotation=allow_rot)
    
    total_containers_needed = len(containers)
    total_items_placed = sum(len(c) for c in containers)
    
    st.markdown(f"### 🚛 Toplam İhtiyaç Duyulan Konteyner: **{total_containers_needed} Adet** ({eq_type})")
    
    if total_containers_needed > 0:
        # Konteynerleri sekme (Tab) halinde göster
        tab_titles = [f"📦 Konteyner #{idx+1} ({len(c)} Parça)" for idx, c in enumerate(containers)]
        container_tabs = st.tabs(tab_titles)
        
        all_manifests = []

        for idx, placements in enumerate(containers):
            with container_tabs[idx]:
                total_w = sum(p.weight for p in placements)
                max_len_used = max([p.x + p.l for p in placements]) if placements else 0.0
                len_util = (max_len_used / dl) * 100 if dl > 0 else 0
                
                c1, c2, c3, c4 = st.columns(4)
                with c1: st.markdown(f'<div class="metric-card"><div class="metric-title">EQUIPMENT TYPE</div><div class="metric-value">{eq_type}</div></div>', unsafe_allow_html=True)
                with c2: st.markdown(f'<div class="metric-card"><div class="metric-title">LENGTH UTILIZATION</div><div class="metric-value">{len_util:.1f}% ({max_len_used:.2f} m)</div></div>', unsafe_allow_html=True)
                with c3: st.markdown(f'<div class="metric-card"><div class="metric-title">NET CARGO WEIGHT</div><div class="metric-value">{total_w:,.0f} KG</div></div>', unsafe_allow_html=True)
                with c4: st.markdown(f'<div class="metric-card"><div class="metric-title">MAX PAYLOAD</div><div class="metric-value">{max_w:,.0f} KG</div></div>', unsafe_allow_html=True)

                fig_2d = create_2d_figure(placements, dl, dw, dh, max_len_used)

                tab_3d, tab_2d = st.tabs(["🧊 İnteraktif 3D Görünüm (Plotly)", "📐 2D Teknik Paftalar (Matplotlib)"])
                
                with tab_3d:
                    st.plotly_chart(render_3d_plotly(placements, dl, dw, dh), width='stretch', key=f"plotly_{idx}")

                with tab_2d:
                    st.pyplot(fig_2d)

                # Manifest Tablosu
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
                
                st.subheader(f"📋 Konteyner #{idx+1} Load Manifest & OOG Specification")
                st.dataframe(df_manifest, width='stretch')

                # PDF İndir Butonu (Konteynere Özel)
                pdf_data = generate_pdf(df_manifest, fig_2d, eq_type, len_util, total_w, idx+1)
                st.download_button(
                    label=f"📄 Konteyner #{idx+1} PDF Raporu İndir",
                    data=pdf_data,
                    file_name=f"container_{idx+1}_manifest.pdf",
                    mime="application/pdf",
                    key=f"pdf_btn_{idx}"
                )

        # Tüm Konteynerlerin Ortak Excel Raporunu İndir Butonu
        st.markdown("---")
        st.subheader("📥 Toplu Rapor İndir")
        excel_data = generate_excel(all_manifests, eq_type)
        st.download_button(
            label="📊 Tüm Konteynerlerin Excel Raporunu İndir (.xlsx)",
            data=excel_data,
            file_name="multi_container_manifest.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    else:
        st.info("Load list is empty. Please add items from the sidebar.")
