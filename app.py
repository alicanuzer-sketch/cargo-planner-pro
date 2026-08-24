import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import plotly.graph_objects as go
from dataclasses import dataclass
from typing import List
from itertools import permutations
import io

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors as rl_colors

# ============================================================
# CONFIG & PROFESSIONAL STYLING
# ============================================================
st.set_page_config(page_title="LoadSketch", page_icon="📦", layout="wide")

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

st.title("📦 LoadSketch")
st.caption("Ölçüleri girin; Flat Rack ve Open Top için olası yerleşim fikirlerini 2D ve 3D olarak görün.")

st.info(
    "ℹ️ Bu araç yalnızca ön planlama ve görselleştirme amacıyla bir yerleşim fikri üretir. "
    "Çıktılar resmi yükleme, lashing/securing, mühendislik hesabı veya taşıyıcı onayı değildir. "
    "Nihai uygulama öncesinde ekipman ve operasyon detayları ilgili taraflarla ayrıca doğrulanmalıdır."
)


# ============================================================
# DATA MODELS & GENERAL PLANNING NOTES
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

GENERAL_PLANNING_NOTES = {
    "Flat Rack": [
        "📌 **Yerleşim sınırı:** 20' FR için 5.50 m, 40' FR / 40' HC FR için 11.60 m üzerindeki tek parçalar bu otomatik yerleşim hesabına dahil edilmez.",
        "📌 **Tahmini yan taşma:** 2.43 m taban genişliğini aşan kısımlar görselde ve tabloda yaklaşık taşma olarak gösterilir.",
        "📌 **Tahmini üst taşma:** Ekipmanın referans yüksekliğini aşan kısım yaklaşık üst taşma olarak gösterilir; yalnızca yükseklik nedeniyle yerleşim önerisi durdurulmaz.",
        "📌 **Uygulama içi planlama kuralı:** Zemine oturan FR yüklerinde en az %60 taban teması aranır. Bu, resmi yapısal veya securing hesabı değildir.",
    ],
    "Open Top": [
        "📌 **Üstten giriş:** Her tek parçanın seçilen OT'nin tanımlı tavan açıklığından geçebildiği varsayılır.",
        "📌 **Çok parçalı yerleşim:** Tavan açıklığı giriş için kullanılır; parçalar içeri alındıktan sonra tanımlı iç taban alanında farklı nihai pozisyonlara yerleştirilebilir.",
        "📌 **Tahmini üst taşma:** Referans yüksekliğini aşan kısım yaklaşık üst taşma olarak gösterilir; yükseklik tek başına yerleşim önerisini engellemez.",
        "📌 **Operasyon notu:** Yükleme sırası, erişim, bedding, lashing ve securing bu araç tarafından doğrulanmaz ve ayrıca değerlendirilmelidir.",
    ]
}

# Planning limits. OT internal floor values are conservative rounded-down values
# used by the application as conservative planning parameters.
# These values are planning inputs, not carrier-specific acceptance criteria.
EQUIPMENT_PROFILES = {
    "20ft Flat Rack": {
        "dl": 5.50, "dw": 2.43, "dh": 2.20, "max_w": 42000.0,
        "is_flat_rack": True,
    },
    "40ft Standard Flat Rack": {
        "dl": 11.60, "dw": 2.43, "dh": 1.92, "max_w": 39000.0,
        "is_flat_rack": True,
    },
    "40ft High Cube Flat Rack": {
        "dl": 11.60, "dw": 2.43, "dh": 2.25, "max_w": 39000.0,
        "is_flat_rack": True,
    },
    "20ft Standard Open Top": {
        "dl": 5.89, "dw": 2.35, "dh": 2.34, "max_w": 30000.0,
        "is_flat_rack": False,
        "roof_l": 5.33, "roof_w": 2.23,
        "door_w": 2.33, "door_h": 2.28,
    },
    "40ft Standard Open Top": {
        "dl": 12.02, "dw": 2.35, "dh": 2.34, "max_w": 28000.0,
        "is_flat_rack": False,
        "roof_l": 11.55, "roof_w": 2.23,
        "door_w": 2.34, "door_h": 2.27,
    },
    "40ft High Cube Open Top": {
        "dl": 12.02, "dw": 2.35, "dh": 2.65, "max_w": 28000.0,
        "is_flat_rack": False,
        "roof_l": 11.55, "roof_w": 2.19,
        "door_w": 2.35, "door_h": 2.57,
    },
}

SECONDARY_EQUIPMENT_PRIORITY = [
    "20ft Standard Open Top",
    "20ft Flat Rack",
    "40ft Standard Open Top",
    "40ft High Cube Open Top",
    "40ft Standard Flat Rack",
    "40ft High Cube Flat Rack",
]


def get_equipment_profile(eq_name: str):
    return EQUIPMENT_PROFILES[eq_name]


def placements_to_cargos(placements: List[Placement]) -> List[Cargo]:
    return [
        Cargo(
            sku=p.sku,
            name=p.name,
            length=p.l,
            width=p.w,
            height=p.h,
            weight=p.weight,
            is_stackable=p.is_stackable,
            max_stack=p.max_stack,
        )
        for p in placements
    ]


def fit_group_to_equipment(placements: List[Placement], eq_name: str, allow_rotation: bool):
    profile = get_equipment_profile(eq_name)
    group_cargos = placements_to_cargos(placements)
    repacked, unplaced = pack_cargo_3d(
        group_cargos,
        profile,
        allow_rotation=allow_rotation,
    )
    fits_all = len(unplaced) == 0 and len(repacked) == len(group_cargos)
    return fits_all, repacked


def valid_equipment_options_for_group(placements: List[Placement], allow_rotation: bool):
    options = []
    for eq_name in SECONDARY_EQUIPMENT_PRIORITY:
        fits_all, _ = fit_group_to_equipment(placements, eq_name, allow_rotation)
        if fits_all:
            options.append(eq_name)
    return options

if 'c_list' not in st.session_state:
    st.session_state.c_list = [
        Cargo("10", "item 1", 2.00, 1.00, 1.50, 1000, False, 1),
        Cargo("11", "item 2", 10.23, 3.15, 2.65, 24800, False, 1)
    ]

# ============================================================
# PACKING ENGINE & HELPER FUNCTIONS
# ============================================================
def calculate_oog(x, y, z, cl, cw, ch, dl, dw, dh):
    """OOG is measured against the equipment planning gauge / deck envelope."""
    return {
        "front": max(0.0, -x),
        "rear": max(0.0, (x + cl) - dl),
        "left": max(0.0, -y),
        "right": max(0.0, (y + cw) - dw),
        "top": max(0.0, (z + ch) - dh),
    }


def is_overlapping(p1: Placement, candidate_box):
    x2, y2, z2, l2, w2, h2 = candidate_box
    return not (
        p1.x + p1.l <= x2 + 0.0001 or x2 + l2 <= p1.x + 0.0001 or
        p1.y + p1.w <= y2 + 0.0001 or y2 + w2 <= p1.y + 0.0001 or
        p1.z + p1.h <= z2 + 0.0001 or z2 + h2 <= p1.z + 0.0001
    )


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


def flat_rack_floor_support_ok(y_start: float, cargo_width: float, deck_width: float = 2.43):
    """User-defined FR planning safety rules for cargo resting directly on the deck."""
    y_end = y_start + cargo_width

    # Rule 3: cargo must actually intersect the physical deck.
    if not (y_start < deck_width and y_end > 0.0):
        return False

    contact_width = max(0.0, min(y_end, deck_width) - max(y_start, 0.0))
    contact_ratio = contact_width / cargo_width if cargo_width > 0 else 0.0

    # Rule 1: minimum 60% of cargo width supported by the deck.
    if contact_ratio + 1e-9 < 0.60:
        return False

    # Rule 2 as supplied: cargo transverse center must be <= 2.00 m.
    y_center = y_start + cargo_width / 2.0
    if y_center > 2.00 + 1e-9:
        return False

    return True


def orientation_allowed_for_equipment(cl: float, cw: float, profile: dict):
    """Check whether one cargo orientation can physically enter/use this equipment."""
    if profile["is_flat_rack"]:
        # HARD RULE: no FR cargo may exceed the usable deck length.
        # Width/height may be OOG, subject to support checks during placement.
        return cl <= profile["dl"] + 0.0001

    # Open Top: every individual piece must pass through the roof opening.
    roof_l = profile["roof_l"]
    roof_w = profile["roof_w"]
    return cl <= roof_l + 0.0001 and cw <= roof_w + 0.0001


def _candidate_points(placements: List[Placement], cl: float, cw: float, ch: float, profile: dict):
    """Generate 3D extreme-point candidates from combinations of existing X/Y edges.

    The previous engine only paired X and Y coordinates from the same cargo. That
    misses valid layouts such as X=edge of Cargo A + Y=edge of Cargo B. This
    Cartesian extreme-point set is the key fix for mixed side-by-side / end-to-end
    Flat Rack plans.
    """
    dl = profile["dl"]
    dw = profile["dw"]
    is_flat_rack = profile["is_flat_rack"]

    x_coords = {0.0}
    z_coords = {0.0}

    for p in placements:
        x_coords.add(round(p.x, 6))
        x_coords.add(round(p.x + p.l, 6))
        # Also allow filling a gap immediately before an existing cargo.
        x_coords.add(round(p.x - cl, 6))
        z_coords.add(round(p.z + p.h, 6))

    # Over-width FR cargo is kept centered transversely. It cannot share an X
    # span with another deck cargo anyway, so searching multiple Y positions
    # adds no useful solution and can create unrealistic asymmetry.
    if is_flat_rack and cw > dw + 0.0001:
        y_coords = {round((dw - cw) / 2.0, 6)}
    else:
        y_coords = {0.0}
        for p in placements:
            y_coords.add(round(p.y, 6))
            y_coords.add(round(p.y + p.w, 6))
            y_coords.add(round(p.y - cw, 6))

    points = []
    for z in z_coords:
        for x in x_coords:
            for y in y_coords:
                if x < -0.0001:
                    continue
                if x + cl > dl + 0.0001:
                    continue
                if not is_flat_rack and (y < -0.0001 or y + cw > dw + 0.0001):
                    continue
                points.append((round(x, 6), round(y, 6), round(z, 6)))

    # Prefer floor placements, then compact X usage, then lower OOG / more
    # centered transverse positions. This keeps the output deterministic.
    deck_center = dw / 2.0
    def sort_key(pt):
        x, y, z = pt
        left_oog = max(0.0, -y)
        right_oog = max(0.0, y + cw - dw)
        oog = left_oog + right_oog
        center_offset = abs((y + cw / 2.0) - deck_center)
        return (z, x, round(oog, 6), round(center_offset, 6), y)

    return sorted(set(points), key=sort_key)


def _pack_cargo_in_order(cargos_in_order: List[Cargo], profile: dict, allow_rotation=True):
    """Greedy placement for one specific cargo order."""
    placements: List[Placement] = []
    unplaced = []
    current_weight = 0.0

    dl = profile["dl"]
    dw = profile["dw"]
    max_w = profile["max_w"]
    is_flat_rack = profile["is_flat_rack"]

    for cargo in cargos_in_order:
        if current_weight + cargo.weight > max_w + 0.0001:
            unplaced.append(cargo)
            continue

        raw_orientations = [(cargo.length, cargo.width)]
        if allow_rotation and abs(cargo.length - cargo.width) > 0.0001:
            raw_orientations.append((cargo.width, cargo.length))

        orientations = []
        for cl, cw in raw_orientations:
            if orientation_allowed_for_equipment(cl, cw, profile):
                if not any(abs(cl-a) < 1e-6 and abs(cw-b) < 1e-6 for a, b in orientations):
                    orientations.append((cl, cw))

        if not orientations:
            unplaced.append(cargo)
            continue

        # Prefer the cargo's original orientation. Rotation is an alternative,
        # not the first choice, unless it is the only feasible orientation.
        placed = False
        for cl, cw in orientations:
            for pt_x, pt_y, pt_z in _candidate_points(placements, cl, cw, cargo.height, profile):
                candidate_box = (pt_x, pt_y, pt_z, cl, cw, cargo.height)

                if any(is_overlapping(existing, candidate_box) for existing in placements):
                    continue

                if is_flat_rack and pt_z <= 0.01:
                    if not flat_rack_floor_support_ok(pt_y, cw, dw):
                        continue

                # An FR cargo whose own physical width exceeds the deck width
                # reserves its whole longitudinal X span: no second cargo may be
                # placed beside it in that same X interval.
                if is_flat_rack:
                    conflict = False
                    for p in placements:
                        overlap_x = min(pt_x + cl, p.x + p.l) - max(pt_x, p.x)
                        if overlap_x > 0.001 and (cw > dw + 0.0001 or p.w > dw + 0.0001):
                            conflict = True
                            break
                    if conflict:
                        continue

                stack_ok, layer_num = check_stacking_validity(candidate_box, placements)
                if not stack_ok:
                    continue

                placements.append(Placement(
                    cargo.sku, cargo.name,
                    pt_x, pt_y, pt_z,
                    cl, cw, cargo.height,
                    cargo.weight,
                    cargo.is_stackable,
                    layer_num,
                    cargo.max_stack,
                ))
                current_weight += cargo.weight
                placed = True
                break

            if placed:
                break

        if not placed:
            unplaced.append(cargo)

    return placements, unplaced


def _packing_score(placements: List[Placement]):
    """Higher is better. Prefer more cargo volume/weight, then compact X usage."""
    volume = sum(p.l * p.w * p.h for p in placements)
    weight = sum(p.weight for p in placements)
    max_x = max((p.x + p.l for p in placements), default=0.0)
    return (len(placements), round(volume, 6), round(weight, 3), -round(max_x, 6))


def pack_cargo_3d(cargos: List[Cargo], profile: dict, allow_rotation=True):
    """Search several cargo orders instead of committing to one greedy order.

    For up to 6 pieces we test every cargo order (max 720 permutations). This is
    small enough for interactive Streamlit use and catches layouts the old
    volume-first greedy algorithm missed. For larger lists, a deterministic set
    of strong heuristic orders is used to keep response time reasonable.
    """
    if not cargos:
        return [], []

    cargos = list(cargos)
    best_placements = []
    best_unplaced = cargos[:]
    best_score = (-1, -1.0, -1.0, float('-inf'))

    if len(cargos) <= 6:
        candidate_orders = permutations(cargos)
    else:
        candidate_orders = [
            sorted(cargos, key=lambda c: c.length * c.width * c.height, reverse=True),
            sorted(cargos, key=lambda c: c.length, reverse=True),
            sorted(cargos, key=lambda c: (c.length, -c.width), reverse=True),
            sorted(cargos, key=lambda c: c.length * c.width, reverse=True),
            sorted(cargos, key=lambda c: c.width, reverse=True),
            sorted(cargos, key=lambda c: c.weight, reverse=True),
            sorted(cargos, key=lambda c: (c.length / max(c.width, 0.001)), reverse=True),
        ]

    for order in candidate_orders:
        placements, unplaced = _pack_cargo_in_order(list(order), profile, allow_rotation)

        # If every piece fits, we are done. Because all pieces are placed, the
        # main objective (one-container feasibility) has been achieved.
        if len(unplaced) == 0 and len(placements) == len(cargos):
            return placements, []

        score = _packing_score(placements)
        if score > best_score:
            best_score = score
            best_placements = placements
            best_unplaced = unplaced

    return best_placements, best_unplaced

def pack_multi_container(cargos: List[Cargo], profile: dict, allow_rotation=True):
    containers = []
    remaining_cargos = cargos.copy()

    while remaining_cargos:
        placements, unplaced = pack_cargo_3d(
            remaining_cargos,
            profile,
            allow_rotation=allow_rotation,
        )

        if not placements:
            st.warning(
                "Bu ekipman için otomatik bir yerleşim fikri oluşturulamadı: "
                + ", ".join(f"{c.sku} - {c.name}" for c in unplaced)
                + ". Ölçüleri, rotasyon seçeneğini veya ekipman tipini tekrar gözden geçirebilirsiniz."
            )
            break

        containers.append(placements)

        # Safety guard against an accidental infinite loop.
        if len(unplaced) >= len(remaining_cargos):
            break
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

    min_y_bound = min([p.y for p in placements] + [0.0]) - 0.5 if placements else -0.5
    max_x_bound = max(dl + 0.5, max_len_used + 0.5)
    max_y_bound = max(dw + 0.5, max([p.y + p.w for p in placements] + [dw]) + 0.5) if placements else dw + 0.5
    max_z_bound = max(dh + 0.5, max([p.z + p.h for p in placements] + [dh]) + 0.5) if placements else dh + 0.5

    ax1.set_xlim(-0.5, max_x_bound); ax1.set_ylim(min_y_bound, max_y_bound); ax1.grid(True, linestyle=':', alpha=0.5)
    ax2.set_xlim(-0.5, max_x_bound); ax2.set_ylim(-0.5, max_z_bound); ax2.grid(True, linestyle=':', alpha=0.5)
    ax3.set_xlim(min_y_bound, max_y_bound); ax3.set_ylim(-0.5, max_z_bound); ax3.grid(True, linestyle=':', alpha=0.5)
    
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

    min_y_val = min([p.y for p in placements] + [0.0]) if placements else 0.0
    max_y_val = max([p.y + p.w for p in placements] + [dw]) if placements else dw

    fig.update_layout(
        scene=dict(
            xaxis=dict(title='Uzunluk / X (m)', range=[0, max(dl, 12)]),
            yaxis=dict(title='Genişlik / Y (m)', range=[min_y_val - 0.5, max_y_val + 0.5]),
            zaxis=dict(title='Yükseklik / Z (m)', range=[0, 5]),
            aspectmode='data'
        ),
        margin=dict(l=0, r=0, b=0, t=10), height=550
    )
    return fig

def generate_excel(all_containers_manifest, container_equipment_types):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary_rows = []
        for c_idx, df_manifest in enumerate(all_containers_manifest):
            equipment_name = container_equipment_types[c_idx]
            summary_rows.append({
                "Unit": f"Unit #{c_idx+1}",
                "Equipment": equipment_name,
                "Total Items": len(df_manifest),
                "Total Cargo Weight (kg)": df_manifest["Weight (kg)"].sum()
            })
            df_manifest.to_excel(writer, sheet_name=f'Unit_{c_idx+1}', index=False)
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name='Summary', index=False)
    return output.getvalue()

def generate_pdf(df_report, fig_2d, eq_type, len_util, total_w, c_num, notes_list):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleStyle', parent=styles['Heading1'], fontSize=15, leading=18,
        textColor=rl_colors.HexColor('#0068C9')
    )
    note_style = ParagraphStyle(
        'NoteStyle', parent=styles['Normal'], fontSize=8, leading=11,
        textColor=rl_colors.HexColor('#475569')
    )

    story.append(Paragraph(f"LoadSketch - Ön Yerleşim Fikri (Ünite #{c_num})", title_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"<b>Ekipman:</b> {eq_type} | <b>Tahmini Uzunluk Kullanımı:</b> {len_util:.1f}% | "
        f"<b>Girilen Toplam Kargo Ağırlığı:</b> {total_w:,.0f} kg",
        styles['Normal']
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>Planlama notu:</b> Bu doküman, kullanıcı tarafından girilen ölçü ve ağırlıklara göre oluşturulmuş bir ön görselleştirmedir. "
        "Resmi yükleme, lashing/securing, yapısal mühendislik hesabı veya taşıyıcı onayı niteliğinde değildir. "
        "Gerçek uygulama öncesinde ilgili operasyonel taraflarca ayrıca doğrulanmalıdır.",
        note_style
    ))
    story.append(Spacer(1, 7))

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
    story.append(Paragraph("<b>Genel Planlama Notları:</b>", styles['Heading3']))
    for r in notes_list:
        clean_r = r.replace("**", "").replace("📌 ", "• ")
        story.append(Paragraph(clean_r, note_style))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Yalnızca ön planlama ve görselleştirme amacıyla hazırlanmıştır. Ekipman, yükleme yöntemi, bedding, "
        "lashing/securing, ağırlık dağılımı ve nihai operasyon kararı sevkiyat öncesinde ayrıca doğrulanmalıdır.",
        note_style
    ))

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
# AŞAMA 2: EKİPMAN AYARLARI & ÇOKLU KONTEYNER OPTİMİZASYONU
# ============================================================
st.markdown("---")
ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 2])

with ctrl1:
    eq_type = st.selectbox(
        "🚛 Başlangıç Ekipman Tipi",
        list(EQUIPMENT_PROFILES.keys()),
        index=list(EQUIPMENT_PROFILES.keys()).index("40ft High Cube Flat Rack")
        if "40ft High Cube Flat Rack" in EQUIPMENT_PROFILES else 0,
    )
    primary_profile = get_equipment_profile(eq_type)
    dl = primary_profile["dl"]
    dw = primary_profile["dw"]
    dh = primary_profile["dh"]
    max_w = primary_profile["max_w"]
    is_flat_rack = primary_profile["is_flat_rack"]
    if not is_flat_rack:
        st.caption(
            f"Roof opening: {primary_profile['roof_l']:.2f} × {primary_profile['roof_w']:.2f} m | "
            f"Internal floor: {primary_profile['dl']:.2f} × {primary_profile['dw']:.2f} m | "
            f"Gauge height: {primary_profile['dh']:.2f} m"
        )

with ctrl2:
    allow_rot = st.checkbox("🔄 Kargoları 90° Döndürmeye İzin Ver", value=False)
    st.caption("Kapalıyken girilen Boy değeri X ekseninde sabit kalır. Açıldığında uygulama alternatif 90° yerleşimleri de deneyebilir.")

    optimize_secondary = st.checkbox(
        "♻️ 2. ve sonraki üniteler için alternatif ekipman fikri göster",
        value=True,
    )
    st.caption("Örneğin kalan parçalar için daha küçük bir ekipmanda da olası yerleşim bulunursa bunu alternatif olarak gösterebilir.")

    st.caption(
        "OT çoklu parça görselleştirmesinde her parçanın tavan açıklığından geçtiği ve içeride nihai konumuna alınabildiği varsayılır. "
        "Gerçek yükleme yolu, erişim, bedding ve lashing/securing bu simülasyonun kapsamı dışındadır."
    )

base_containers = pack_multi_container(
    st.session_state.c_list,
    primary_profile,
    allow_rotation=allow_rot,
)

containers = []
container_equipment_types = []

if base_containers:
    for idx, base_placements in enumerate(base_containers):
        if idx == 0:
            chosen_eq = eq_type
            chosen_placements = base_placements
        else:
            valid_options = valid_equipment_options_for_group(base_placements, allow_rot)
            if eq_type not in valid_options:
                valid_options.append(eq_type)

            if optimize_secondary and valid_options:
                default_eq = valid_options[0]
            else:
                default_eq = eq_type

            chosen_eq = st.selectbox(
                f"🚛 Ünite #{idx+1} için ekipman fikri",
                options=valid_options,
                index=valid_options.index(default_eq) if default_eq in valid_options else 0,
                key=f"equipment_override_{idx+1}",
                help="Listede, mevcut geometrik planlama kurallarıyla bu yük grubu için bir yerleşim fikri üretilebilen ekipmanlar gösterilir.",
            )

            fits_all, repacked = fit_group_to_equipment(base_placements, chosen_eq, allow_rot)
            if fits_all:
                chosen_placements = repacked
            else:
                st.warning(
                    f"Ünite #{idx+1} için {chosen_eq} ile otomatik yerleşim fikri oluşturulamadı. "
                    f"Başlangıç ekipmanı olan {eq_type} görünümüne dönüldü."
                )
                chosen_eq = eq_type
                chosen_placements = base_placements

        profile = get_equipment_profile(chosen_eq)
        containers.append({
            "equipment": chosen_eq,
            "dl": profile["dl"],
            "dw": profile["dw"],
            "dh": profile["dh"],
            "max_w": profile["max_w"],
            "is_flat_rack": profile["is_flat_rack"],
            "placements": chosen_placements,
        })
        container_equipment_types.append(chosen_eq)

with ctrl3:
    st.metric("Önerilen Ünite Sayısı", f"{len(containers)} Adet")
    if containers and len(set(container_equipment_types)) > 1:
        st.info("Alternatif ekipman kombinasyonu gösteriliyor.")

# ============================================================
# AŞAMA 3: SİMÜLASYON VE RAPORLAMA EKRANI
# ============================================================
if containers:
    all_manifests = []
    for container in containers:
        c_dl = container["dl"]
        c_dw = container["dw"]
        c_dh = container["dh"]
        placements_all = container["placements"]

        report_rows = []
        for p in placements_all:
            oog = calculate_oog(p.x, p.y, p.z, p.l, p.w, p.h, c_dl, c_dw, c_dh)
            is_oog = "Estimated overhang" if any(v > 0 for v in oog.values()) else "Within reference envelope"
            report_rows.append({
                "SKU": p.sku,
                "Name": p.name,
                "X (m)": round(p.x, 2),
                "Y (m)": round(p.y, 2),
                "Z (m)": round(p.z, 2),
                "Length (cm)": int(p.l * 100),
                "Width (cm)": int(p.w * 100),
                "Height (cm)": int(p.h * 100),
                "Weight (kg)": p.weight,
                "Stackable": "Yes" if p.is_stackable else "No",
                "Layer": p.stack_layer,
                "Estimated Envelope Note": is_oog,
                "Est. Left Overhang (cm)": round(oog["left"] * 100, 1),
                "Est. Right Overhang (cm)": round(oog["right"] * 100, 1),
                "Est. Top Overhang (cm)": round(oog["top"] * 100, 1),
            })
        all_manifests.append(pd.DataFrame(report_rows))

    st.markdown("### 🧭 Olası Yerleşim Fikri")
    selected_container_no = st.selectbox(
        "Görüntülenecek Ünite",
        options=list(range(1, len(containers) + 1)),
        format_func=lambda n: f"📦 Ünite #{n} — {containers[n-1]['equipment']}",
        key="selected_container_no",
    )

    idx = selected_container_no - 1
    selected_container = containers[idx]
    placements = selected_container["placements"]
    selected_eq_type = selected_container["equipment"]
    c_dl = selected_container["dl"]
    c_dw = selected_container["dw"]
    c_dh = selected_container["dh"]
    c_max_w = selected_container["max_w"]
    c_is_flat_rack = selected_container["is_flat_rack"]
    df_manifest = all_manifests[idx]

    st.caption(
        f"Girilen bilgilerle uygulama {len(containers)} ünite üzerinden bir yerleşim fikri oluşturdu. "
        f"Şu anda Ünite #{selected_container_no} — {selected_eq_type} görüntüleniyor."
    )

    total_w = sum(p.weight for p in placements)
    max_len_used = max([p.x + p.l for p in placements]) if placements else 0.0
    len_util = (max_len_used / c_dl) * 100 if c_dl > 0 else 0

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(
            f'<div class="metric-card"><div class="metric-title">Tahmini Uzunluk Kullanımı</div>'
            f'<div class="metric-value">%{len_util:.1f}</div></div>',
            unsafe_allow_html=True,
        )
    with m2:
        st.markdown(
            f'<div class="metric-card"><div class="metric-title">Girilen Toplam Ağırlık</div>'
            f'<div class="metric-value">{total_w:,.0f} KG</div></div>',
            unsafe_allow_html=True,
        )
    with m3:
        st.markdown(
            f'<div class="metric-card"><div class="metric-title">GÖSTERİLEN EKİPMAN / REFERANS PAYLOAD</div>'
            f'<div class="metric-value" style="font-size:16px">{selected_eq_type}<br>{c_max_w:,.0f} KG</div></div>',
            unsafe_allow_html=True,
        )
    with m4:
        selected_category = "Flat Rack" if c_is_flat_rack else "Open Top"
        selected_remarks = GENERAL_PLANNING_NOTES[selected_category]
        try:
            fig_2d = create_2d_figure(placements, c_dl, c_dw, c_dh, max_len_used)
            pdf_data = generate_pdf(
                df_manifest,
                fig_2d,
                selected_eq_type,
                len_util,
                total_w,
                selected_container_no,
                selected_remarks,
            )
            st.download_button(
                label=f"📄 Ünite #{selected_container_no} Ön Yerleşim PDF'ini İndir",
                data=pdf_data,
                file_name=f"loadsketch_unit_{selected_container_no}_{selected_eq_type.replace(' ', '_')}.pdf",
                mime="application/pdf",
                key=f"pdf_btn_selected_{selected_container_no}_{selected_eq_type}",
            )
        except Exception as e:
            st.error(f"PDF oluşturulamadı: {e}")
            fig_2d = create_2d_figure(placements, c_dl, c_dw, c_dh, max_len_used)

    with st.expander(f"📋 {selected_category} için Genel Planlama Notları", expanded=False):
        for r in selected_remarks:
            st.markdown(r)

    st.markdown("<br>", unsafe_allow_html=True)

    v_tab1, v_tab2, v_tab3 = st.tabs([
        "🧊 İnteraktif 3D Yerleşim Görünümü",
        "📐 2D Yerleşim Görünümü",
        "📋 Parça Listesi & Tahmini Koordinatlar",
    ])

    with v_tab1:
        st.plotly_chart(
            render_3d_plotly(placements, c_dl, c_dw, c_dh),
            key=f"plotly_main_selected_{selected_container_no}_{selected_eq_type}",
            use_container_width=True,
        )

    with v_tab2:
        st.pyplot(fig_2d)

    with v_tab3:
        st.dataframe(df_manifest, use_container_width=True)

    st.markdown("---")
    st.markdown("#### 📦 Yerleşim Özeti")
    summary_df = pd.DataFrame([
        {
            "Ünite": f"#{i+1}",
            "Ekipman": c["equipment"],
            "Yük Adedi": len(c["placements"]),
            "Toplam Ağırlık (kg)": sum(p.weight for p in c["placements"]),
        }
        for i, c in enumerate(containers)
    ])
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    excel_data = generate_excel(all_manifests, container_equipment_types)
    st.download_button(
        label="📊 Tüm Ünitelerin Yerleşim Verisini Excel Olarak İndir (.xlsx)",
        data=excel_data,
        file_name="loadsketch_arrangement_data.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.caption(
        "Bu görselleştirme yalnızca girilen ölçü ve ağırlıklara göre oluşturulmuş bir ön yerleşim fikridir. "
        "Gerçek yükleme, ekipman uygunluğu, ağırlık dağılımı, bedding, lashing/securing ve nihai operasyon kararı ayrıca doğrulanmalıdır."
    )
