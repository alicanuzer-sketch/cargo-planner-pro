import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import plotly.graph_objects as go
from dataclasses import dataclass
from typing import List
import io

# ReportLab kütüphaneleri (PDF üretimi için)
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
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
st.caption("Cargo-Planner style professional OOG Multi-View & 3D Interactive Layout")

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

@dataclass
class Placement:
    sku: str
    name: str
    x: float; y: float; z: float
    l: float; w: float; h: float
    weight: float

# ============================================================
# INITIALIZE STATE
# ============================================================
if 'c_list' not in st.session_state:
    st.session_state.c_list = [
        Cargo("10", "Main Machine", 3.50, 1.20, 1.70, 2200),
        Cargo("13", "Transformer Box", 4.90, 1.10, 2.20, 8000),
        Cargo("7", "Control Unit", 3.50, 1.00, 1.20, 2100),
        Cargo("15", "Accessory Kit", 0.90, 0.90, 0.55, 180),
        Cargo("16", "Extra Box", 1.20, 0.80, 0.80, 350)
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

def pack_cargo_3d(cargos: List[Cargo], dl: float, dw: float, dh: float, allow_rotation=True):
    placements: List[Placement] = []
    unplaced = []

    sorted_cargos = sorted(cargos, key=lambda c: (c.length * c.width * c.height), reverse=True)

    for cargo in sorted_cargos:
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
                if any(is_overlapping(existing, candidate_box) for existing in placements):
                    continue

                placements.append(Placement(
                    cargo.sku, cargo.name, pt_x, pt_y, pt_z, cl, cw, cargo.height, cargo.weight
                ))
                placed = True
                break
            if placed:
                break

        if not placed:
            unplaced.append(cargo)

    return placements, unplaced

# ============================================================
# REPORT GENERATION FUNCTIONS (PDF & EXCEL)
# ============================================================
def generate_excel(df_report, eq_type, len_util, total_w):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_summary = pd.DataFrame([{
            "Equipment": eq_type,
            "Length Utilization (%)": round(len_util, 1),
            "Total Cargo Weight (kg)": total_w
        }])
        df_summary.to_excel(writer, sheet_name='Summary', index=False)
        df_report.to_excel(writer, sheet_name='Load Manifest', index=False)
    return output.getvalue()

def generate_pdf(df_report, eq_type, len_util, total_w):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, leading=22, textColor=rl_colors.HexColor('#0068C9'))
    
    story.append(Paragraph("Project Logistics Loading Report", title_style))
    story.append(Spacer(1, 10))
    
    # Özet Bilgiler
    summary_text = f"<b>Equipment:</b> {eq_type} | <b>Length Utilization:</b> {len_util:.1f}% | <b>Total Weight:</b> {total_w:,.0f} kg"
    story.append(Paragraph(summary_text, styles['Normal']))
    story.append(Spacer(1, 15))
    
    # Manifest Tablosu
    table_data = [df_report.columns.tolist()] + df_report.values.tolist()
    t = Table(table_data)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), rl_colors.HexColor('#0068C9')),
        ('TEXTCOLOR', (0,0), (-1,0), rl_colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('BACKGROUND', (0,1), (-1,-1), rl_colors.HexColor('#F8F9FA')),
        ('GRID', (0,0), (-1,-1), 0.5, rl_colors.grey),
        ('FONTSIZE', (0,1), (-1,-1), 8),
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
                f"Ağırlık: {p.weight:,.0f} kg"
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
                Cargo(str(row['SKU']), str(row['Name']), float(row['Length_m']), float(row['Width_m']), float(row['Height_m']), float(row['Weight_kg']))
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
        
        if st.form_submit_button("Add to Load List"):
            st.session_state.c_list.append(Cargo(sku, name, c_l, c_w, c_h, c_wt))
            st.rerun()

    if st.button("🗑️ Clear List", type="secondary"):
        st.session_state.c_list = []
        st.rerun()

# ============================================================
# RESULTS & DRAWINGS
# ============================================================
with col_main:
    placements, unplaced = pack_cargo_3d(st.session_state.c_list, dl, dw, dh, allow_rotation=allow_rot)
    
    c1, c2, c3, c4 = st.columns(4)
    total_w = sum(p.weight for p in placements)
    max_len_used = max([p.x + p.l for p in placements]) if placements else 0.0
    len_util = (max_len_used / dl) * 100 if dl > 0 else 0
    
    with c1: st.markdown(f'<div class="metric-card"><div class="metric-title">EQUIPMENT TYPE</div><div class="metric-value">{eq_type}</div></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div class="metric-card"><div class="metric-title">LENGTH UTILIZATION</div><div class="metric-value">{len_util:.1f}% ({max_len_used:.2f} m)</div></div>', unsafe_allow_html=True)
    with c3: st.markdown(f'<div class="metric-card"><div class="metric-title">NET CARGO WEIGHT</div><div class="metric-value">{total_w:,.0f} KG</div></div>', unsafe_allow_html=True)
    with c4: st.markdown(f'<div class="metric-card"><div class="metric-title">MAX PAYLOAD</div><div class="metric-value">{max_w:,.0f} KG</div></div>', unsafe_allow_html=True)

    if len(placements) > 0:
        tab_3d, tab_2d = st.tabs(["🧊 İnteraktif 3D Görünüm (Plotly)", "📐 2D Teknik Paftalar (Matplotlib)"])
        
        with tab_3d:
            st.plotly_chart(render_3d_plotly(placements, dl, dw, dh), width='stretch')

        with tab_2d:
            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 12))
            colors = ['#0068C9', '#FF4B4B', '#29B09D', '#774294', '#FF8700', '#00D4FF', '#E63946', '#457B9D']

            ax1.set_title("TOP VIEW (Üstten Görünüm)", fontsize=11, fontweight='bold')
            ax1.add_patch(patches.Rectangle((0, 0), dl, dw, color='lightgray', alpha=0.4))
            
            ax2.set_title("SIDE VIEW (Yandan Görünüm)", fontsize=11, fontweight='bold')
            ax2.add_patch(patches.Rectangle((0, 0), dl, dh, color='lightgray', alpha=0.4))
            
            ax3.set_title("FRONT VIEW (Önden Görünüm)", fontsize=11, fontweight='bold')
            ax3.add_patch(patches.Rectangle((0, 0), dw, dh, color='lightgray', alpha=0.4))

            for idx, p in enumerate(placements):
                c_color = colors[idx % len(colors)]
                ax1.add_patch(patches.Rectangle((p.x, p.y), p.l, p.w, edgecolor='black', facecolor=c_color, alpha=0.7, linewidth=1.5))
                ax1.text(p.x + p.l/2, p.y + p.w/2, f"SKU {p.sku}", ha='center', va='center', color='white', fontweight='bold', fontsize=9)

                ax2.add_patch(patches.Rectangle((p.x, p.z), p.l, p.h, edgecolor='black', facecolor=c_color, alpha=0.7, linewidth=1.5))
                ax2.text(p.x + p.l/2, p.z + p.h/2, f"SKU {p.sku}", ha='center', va='center', color='white', fontweight='bold', fontsize=9)

                ax3.add_patch(patches.Rectangle((p.y, p.z), p.w, p.h, edgecolor='black', facecolor='none', linestyle='--', linewidth=1.5))
                ax3.add_patch(patches.Rectangle((p.y, p.z), p.w, p.h, facecolor=c_color, alpha=0.4))
                ax3.text(p.y + p.w/2, p.z + p.h/2, f"SKU {p.sku}", ha='center', va='center', color='black', fontweight='bold', fontsize=9)

            max_x_bound = max(dl + 2, max_len_used + 2)
            max_y_bound = max([dw + 2] + [p.y + p.w + 1 for p in placements])
            min_y_bound = min([-1.0] + [p.y - 1 for p in placements])
            max_z_bound = max([dh + 2] + [p.z + p.h + 1 for p in placements])

            ax1.set_xlim(-1, max_x_bound); ax1.set_ylim(min_y_bound, max_y_bound); ax1.grid(True, linestyle='--', alpha=0.4)
            ax2.set_xlim(-1, max_x_bound); ax2.set_ylim(-0.5, max_z_bound); ax2.grid(True, linestyle='--', alpha=0.4)
            ax3.set_xlim(min_y_bound, max_y_bound); ax3.set_ylim(-0.5, max_z_bound); ax3.grid(True, linestyle='--', alpha=0.4)
            
            plt.tight_layout()
            st.pyplot(fig)

        # Manifest Tablosu
        report_data = []
        for p in placements:
            oog = calculate_oog(p.x, p.y, p.z, p.l, p.w, p.h, dl, dw, dh)
            is_oog = "Yes" if any(v > 0 for v in oog.values()) else "No"
            report_data.append({
                "SKU": p.sku, "Name": p.name, "X (m)": round(p.x, 2), "Y (m)": round(p.y, 2), "Z (m)": round(p.z, 2),
                "Length (cm)": int(p.l*100), "Width (cm)": int(p.w*100), "Height (cm)": int(p.h*100),
                "Weight (kg)": p.weight, "OOG?": is_oog
            })

        df_manifest = pd.DataFrame(report_data)
        st.subheader("📋 Load Manifest & OOG Specification")
        st.dataframe(df_manifest, width='stretch')

        # 📥 İNDİRME BUTONLARI (PDF & EXCEL)
        st.subheader("📥 Rapor İndir")
        col_dl1, col_dl2 = st.columns(2)

        excel_data = generate_excel(df_manifest, eq_type, len_util, total_w)
        pdf_data = generate_pdf(df_manifest, eq_type, len_util, total_w)

        with col_dl1:
            st.download_button(
                label="📊 Excel Raporu İndir (.xlsx)",
                data=excel_data,
                file_name="load_manifest.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        with col_dl2:
            st.download_button(
                label="📄 PDF Raporu İndir (.pdf)",
                data=pdf_data,
                file_name="load_manifest.pdf",
                mime="application/pdf",
                use_container_width=True
            )

    else:
        st.info("Load list is empty. Please add items from the sidebar.")
