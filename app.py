import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from dataclasses import dataclass
from typing import List

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
st.caption("Cargo-Planner style professional OOG Multi-View Layout")

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
# INITIALIZE STATE (Hafıza Yönetimi Sabitlendi)
# ============================================================
if 'c_list' not in st.session_state:
    st.session_state.c_list = [
        Cargo("10", "Main Machine", 3.50, 3.50, 1.70, 2200),
        Cargo("13", "Transformer Box", 4.90, 3.10, 2.20, 8000),
        Cargo("7", "Control Unit", 3.50, 1.30, 1.20, 2100),
        Cargo("15", "Accessory Kit", 0.90, 0.90, 0.55, 180)
    ]

# ============================================================
# PACKING ENGINE (Yan Yana Sıralama Altyapısı Düzenlendi)
# ============================================================
def calculate_oog(x, y, z, cl, cw, ch, dl, dw, dh):
    return {
        "front": max(0.0, -x), "rear": max(0.0, (x + cl) - dl),
        "left": max(0.0, -y), "right": max(0.0, (y + cw) - dw), "top": max(0.0, (z + ch) - dh)
    }

def pack_cargo(cargos: List[Cargo], dl: float, dw: float, dh: float):
    placements: List[Placement] = []
    unplaced = []
    
    # Hacimsel büyüklüğe göre sırala
    sorted_cargos = sorted(cargos, key=lambda c: (c.length * c.width * c.height), reverse=True)
    
    current_x = 0.0  # Kargoların üst üste binmesini önleyen takip çizgisi

    for cargo in sorted_cargos:
        # Genişlik taşması varsa kargoyu Y ekseninde ortala (Symmetrical OOG)
        cy = (dw - cargo.width) / 2
        cx = current_x
        cz = 0.0
        
        placements.append(Placement(
            cargo.sku, cargo.name, cx, cy, cz, cargo.length, cargo.width, cargo.height, cargo.weight
        ))
        
        # Bir sonraki kargoyu bu kargonun bittiği yere koy (X ekseninde kaydır)
        current_x += cargo.length

    return placements, unplaced

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

    st.subheader("➕ Add Item")
    with st.form("cargo_form", clear_on_submit=True):
        sku = st.text_input("SKU / ID", f"{len(st.session_state.c_list) + 10}")
        name = st.text_input("Cargo Name", f"Item-{sku}")
        c_l = st.number_input("Length (cm)", value=200) / 100.0
        c_w = st.number_input("Width (cm)", value=200) / 100.0
        c_h = st.number_input("Height (cm)", value=200) / 100.0
        c_wt = st.number_input("Weight (kg)", value=1000)
        
        if st.form_submit_button("Add to Load List"):
            st.session_state.c_list.append(Cargo(sku, name, c_l, c_w, c_h, c_wt))
            st.rerun()

    if st.button("🗑️ Clear List", type="secondary"):
        st.session_state.c_list = []
        st.rerun()

# ============================================================
# RESULTS & MULTI-VIEW DRAWINGS
# ============================================================
with col_main:
    placements, unplaced = pack_cargo(st.session_state.c_list, dl, dw, dh)
    
    # Bilgi Kartları
    c1, c2, c3, c4 = st.columns(4)
    total_w = sum(p.weight for p in placements)
    max_len_used = max([p.x + p.l for p in placements]) if placements else 0.0
    len_util = (max_len_used / dl) * 100 if dl > 0 else 0
    
    with c1: st.markdown(f'<div class="metric-card"><div class="metric-title">EQUIPMENT TYPE</div><div class="metric-value">{eq_type}</div></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div class="metric-card"><div class="metric-title">LENGTH UTILIZATION</div><div class="metric-value">{len_util:.1f}% ({max_len_used:.2f} m)</div></div>', unsafe_allow_html=True)
    with c3: st.markdown(f'<div class="metric-card"><div class="metric-title">NET CARGO WEIGHT</div><div class="metric-value">{total_w:,.0f} KG</div></div>', unsafe_allow_html=True)
    with c4: st.markdown(f'<div class="metric-card"><div class="metric-title">MAX PAYLOAD</div><div class="metric-value">{max_w:,.0f} KG</div></div>', unsafe_allow_html=True)

    if len(placements) > 0:
        # 3'lü Görünüm Paftası Çizimi (Matplotlib)
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 14))
        colors = ['#0068C9', '#FF4B4B', '#29B09D', '#774294', '#FF8700', '#00D4FF']
        report_data = []

        # 1. Plan: Üstten Görünüm (Top View)
        ax1.set_title("TOP VIEW (Üstten Görünüm - Genişlik Taşması / Overwidth)", fontsize=12, fontweight='bold')
        ax1.add_patch(patches.Rectangle((0, 0), dl, dw, color='lightgray', alpha=0.4, label='Container Base'))
        
        # 2. Plan: Yandan Görünüm (Side View)
        ax2.set_title("SIDE VIEW (Yandan Görünüm - Yükseklik Taşması / Overheight)", fontsize=12, fontweight='bold')
        ax2.add_patch(patches.Rectangle((0, 0), dl, dh, color='lightgray', alpha=0.4))
        
        # 3. Plan: Önden Görünüm (Front View)
        ax3.set_title("FRONT VIEW (Önden Görünüm - Genişlik & Yükseklik Taşma Detayı)", fontsize=12, fontweight='bold')
        ax3.add_patch(patches.Rectangle((0, 0), dw, dh, color='lightgray', alpha=0.4))

        for idx, p in enumerate(placements):
            oog = calculate_oog(p.x, p.y, p.z, p.l, p.w, p.h, dl, dw, dh)
            is_oog = "Yes" if any(v > 0 for v in oog.values()) else "No"
            c_color = colors[idx % len(colors)]

            report_data.append({
                "SKU": p.sku, "Name": p.name, "Length (cm)": int(p.l*100), "Width (cm)": int(p.w*100), "Height (cm)": int(p.h*100),
                "Weight (kg)": p.weight, "OOG?": is_oog, "Left OOG (cm)": int(oog['left']*100), "Right OOG (cm)": int(oog['right']*100), "Top OOG (cm)": int(oog['top']*100)
            })

            # Top View Çiz
            ax1.add_patch(patches.Rectangle((p.x, p.y), p.l, p.w, edgecolor='black', facecolor=c_color, alpha=0.7, linewidth=1.5))
            ax1.text(p.x + p.l/2, p.y + p.w/2, f"SKU {p.sku}", ha='center', va='center', color='white', fontweight='bold', fontsize=9)

            # Side View Çiz
            ax2.add_patch(patches.Rectangle((p.x, p.z), p.l, p.h, edgecolor='black', facecolor=c_color, alpha=0.7, linewidth=1.5))
            ax2.text(p.x + p.l/2, p.z + p.h/2, f"SKU {p.sku}", ha='center', va='center', color='white', fontweight='bold', fontsize=9)

            # Front View Çiz (Üst üste binmeyi engellemek için tüm kargoların ön kesit izdüşümünü basar)
            ax3.add_patch(patches.Rectangle((p.y, p.z), p.w, p.h, edgecolor='black', facecolor='none', linestyle='--', linewidth=1.5))
            ax3.add_patch(patches.Rectangle((p.y, p.z), p.w, p.h, facecolor=c_color, alpha=0.4))
            ax3.text(p.y + p.w/2, p.z + p.h/2, f"SKU {p.sku}", ha='center', va='center', color='black', fontweight='bold', fontsize=9)

        # Grafik Sınır Ayarları (Dinamik Ölçeklendirme)
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
        st.subheader("📋 Load Manifest & OOG Specification")
        st.dataframe(pd.DataFrame(report_data), use_container_width=True)
    else:
        st.info("Load list is empty. Please add items from the sidebar.")
