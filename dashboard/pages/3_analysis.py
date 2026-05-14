import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sqlalchemy import text
from db import get_engine

st.set_page_config(page_title="工艺参数分析", layout="wide")

engine = get_engine()

# ── Load data: pvd_deposition JOIN samples ──
@st.cache_data
def load_process_data():
    """Return a wide DataFrame with process params + batch info, one row per sample."""
    with engine.begin() as conn:
        df = pd.read_sql(text("""
            SELECT s.sample_id,
                   substring(s.sample_id, 1, 2) AS batch,
                   s.substrate_type,
                   s.sample_type,
                   s.top_electrode_material,
                   s.bottom_electrode_material,
                   s.top_electrode_method,
                   s.batch_tag,
                   p.*
            FROM samples s
            JOIN pvd_deposition p ON s.sample_id = p.sample_id
        """), conn)
    # Drop duplicate sample_id column from pvd_deposition
    if 'sample_id_1' in df.columns:
        df = df.drop(columns=['sample_id_1'])
    # Also drop pvd_id
    if 'pvd_id' in df.columns:
        df = df.drop(columns=['pvd_id'])
    return df

df = load_process_data()

# ── Define numeric parameter columns ──
PARAM_COLS = [
    'film_target_thickness_nm', 'top_elec_target_thickness_nm', 'bottom_elec_target_thickness_nm',
    'al_power_w', 'sc_power_w',
    'n2_flow_sccm', 'ar_flow_sccm',
    'substrate_temp_set', 'bias_voltage_v',
    'target_dist_mm', 'sputter_angle_deg', 'rotation_speed_rpm',
    'total_duration_sec', 'base_vacuum_pa', 'working_pressure_pa',
    'total_power_w', 'discharge_voltage_v', 'discharge_current_a',
    'pulse_freq_khz', 'duty_cycle_pct', 'pre_sputtering_min',
]

PARAM_LABELS = {
    'film_target_thickness_nm': 'Film Thickness (nm)',
    'top_elec_target_thickness_nm': 'Top Electrode Thickness (nm)',
    'bottom_elec_target_thickness_nm': 'Bottom Electrode Thickness (nm)',
    'al_power_w': 'Al Power (W)',
    'sc_power_w': 'Sc Power (W)',
    'n2_flow_sccm': 'N2 Flow (sccm)',
    'ar_flow_sccm': 'Ar Flow (sccm)',
    'substrate_temp_set': 'Substrate Temp (C)',
    'bias_voltage_v': 'Bias Voltage (V)',
    'target_dist_mm': 'Target Distance (mm)',
    'sputter_angle_deg': 'Sputter Angle (deg)',
    'rotation_speed_rpm': 'Rotation Speed (rpm)',
    'total_duration_sec': 'Total Duration (sec)',
    'base_vacuum_pa': 'Base Vacuum (Pa)',
    'working_pressure_pa': 'Working Pressure (Pa)',
    'total_power_w': 'Total Power (W)',
    'discharge_voltage_v': 'Discharge Voltage (V)',
    'discharge_current_a': 'Discharge Current (A)',
    'pulse_freq_khz': 'Pulse Freq (kHz)',
    'duty_cycle_pct': 'Duty Cycle (%)',
    'pre_sputtering_min': 'Pre-sputtering (min)',
}

# ── Sidebar: batch filter ──
with st.sidebar:
    st.title("工艺参数分析")
    st.markdown("---")
    batches_avail = sorted(df['batch'].unique().tolist())
    selected_batches = st.multiselect("批次筛选", batches_avail, default=batches_avail)

filtered = df[df['batch'].isin(selected_batches)] if selected_batches else df

st.title("PVD 工艺参数分布分析")
st.caption("数据来源: pvd_deposition JOIN samples，共 {} 个样品".format(len(filtered)))

# ═══════════════════════════════════════
# Section 1: Single Variable Distribution
# ═══════════════════════════════════════
st.header("单变量分布")

c1, c2 = st.columns([1, 3])
with c1:
    dist_param = st.selectbox(
        "选择参数",
        PARAM_COLS,
        format_func=lambda x: PARAM_LABELS.get(x, x),
        key='dist_param'
    )

if dist_param:
    series = pd.to_numeric(filtered[dist_param], errors='coerce').dropna()

    if len(series) > 0:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        # Histogram + KDE
        ax1.hist(series, bins=min(30, len(series)//3), color='steelblue',
                 edgecolor='white', alpha=0.8, density=True)
        # KDE via gaussian
        from scipy.stats import gaussian_kde
        try:
            kde = gaussian_kde(series)
            x_range = np.linspace(series.min(), series.max(), 200)
            ax1.plot(x_range, kde(x_range), 'r-', linewidth=2, label='KDE')
        except Exception:
            pass
        ax1.axvline(series.mean(), color='red', linestyle='--', alpha=0.5, label='Mean')
        ax1.axvline(series.median(), color='orange', linestyle='--', alpha=0.5, label='Median')
        ax1.set_xlabel(PARAM_LABELS.get(dist_param, dist_param))
        ax1.set_ylabel('Density')
        ax1.set_title('Distribution')
        ax1.legend(fontsize=8)

        # Box plot
        bp = ax2.boxplot(series.dropna(), vert=True, patch_artist=True,
                         widths=0.4,
                         boxprops=dict(facecolor='steelblue', alpha=0.7),
                         medianprops=dict(color='red', linewidth=2))
        ax2.set_ylabel(PARAM_LABELS.get(dist_param, dist_param))
        ax2.set_title('Box Plot')
        ax2.set_xticklabels([])

        fig.tight_layout()
        st.pyplot(fig)

        # Five-number summary
        st.markdown("**统计摘要**")
        sm = series.describe()
        cols = st.columns(8)
        cols[0].metric("N", int(sm['count']))
        cols[1].metric("Mean", "{:.4g}".format(sm['mean']))
        cols[2].metric("Std", "{:.4g}".format(sm['std']))
        cols[3].metric("Min", "{:.4g}".format(sm['min']))
        cols[4].metric("Q1", "{:.4g}".format(sm['25%']))
        cols[5].metric("Median", "{:.4g}".format(sm['50%']))
        cols[6].metric("Q3", "{:.4g}".format(sm['75%']))
        cols[7].metric("Max", "{:.4g}".format(sm['max']))

    else:
        st.warning("所选参数无有效数据")

# ═══════════════════════════════════════
# Section 2: Batch Comparison
# ═══════════════════════════════════════
st.divider()
st.header("批次对比")

c1, c2 = st.columns([1, 3])
with c1:
    batch_param = st.selectbox(
        "选择参数",
        PARAM_COLS,
        format_func=lambda x: PARAM_LABELS.get(x, x),
        key='batch_param'
    )

if batch_param:
    fig, ax = plt.subplots(figsize=(12, 5))
    batch_order = sorted([b for b in batches_avail if b in selected_batches])

    box_data = []
    box_labels = []
    for b in batch_order:
        vals = pd.to_numeric(filtered[filtered['batch'] == b][batch_param], errors='coerce').dropna()
        if len(vals) > 0:
            box_data.append(vals.values)
            box_labels.append('{} (n={})'.format(b, len(vals)))

    if box_data:
        bp = ax.boxplot(box_data, patch_artist=True, widths=0.5,
                        boxprops=dict(facecolor='steelblue', alpha=0.7),
                        medianprops=dict(color='red', linewidth=2),
                        flierprops=dict(marker='o', markersize=5, alpha=0.5))

        # Overlay individual points with jitter
        for i, vals in enumerate(box_data):
            jitter = np.random.normal(i + 1, 0.04, size=len(vals))
            ax.scatter(jitter, vals, alpha=0.3, s=20, color='black', edgecolors='none')

        ax.set_xticklabels(box_labels)
        ax.set_ylabel(PARAM_LABELS.get(batch_param, batch_param))
        ax.set_title('{} by Batch'.format(PARAM_LABELS.get(batch_param, batch_param)))
        ax.grid(axis='y', alpha=0.3)
        fig.tight_layout()
        st.pyplot(fig)
    else:
        st.warning("无数据")

# ═══════════════════════════════════════
# Section 3: Parameter Overview Table
# ═══════════════════════════════════════
st.divider()
st.header("参数全景")

@st.cache_data
def compute_param_summary(_df, _param_cols):
    rows = []
    for col in _param_cols:
        s = pd.to_numeric(_df[col], errors='coerce').dropna()
        if len(s) == 0:
            continue
        rows.append({
            'Parameter': PARAM_LABELS.get(col, col),
            'N': len(s),
            'Mean': round(s.mean(), 4),
            'Std': round(s.std(), 4),
            'Min': round(s.min(), 4),
            'Q1': round(s.quantile(0.25), 4),
            'Median': round(s.median(), 4),
            'Q3': round(s.quantile(0.75), 4),
            'Max': round(s.max(), 4),
            'CV%': round(100 * s.std() / s.mean(), 2) if s.mean() != 0 else None,
        })
    return pd.DataFrame(rows)

summary_df = compute_param_summary(filtered, PARAM_COLS)

if not summary_df.empty:
    st.dataframe(
        summary_df.sort_values('CV%', ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={
            'Parameter': st.column_config.TextColumn('参数'),
            'N': st.column_config.NumberColumn('N'),
            'Mean': st.column_config.NumberColumn('均值', format='%.4g'),
            'Std': st.column_config.NumberColumn('标准差', format='%.4g'),
            'CV%': st.column_config.NumberColumn('变异系数%', format='%.1f'),
            'Min': st.column_config.NumberColumn('最小', format='%.4g'),
            'Q1': st.column_config.NumberColumn('Q1', format='%.4g'),
            'Median': st.column_config.NumberColumn('中位数', format='%.4g'),
            'Q3': st.column_config.NumberColumn('Q3', format='%.4g'),
            'Max': st.column_config.NumberColumn('最大', format='%.4g'),
        }
    )
else:
    st.warning("无数据")
