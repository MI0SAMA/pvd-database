import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sqlalchemy import text
from db import get_engine, get_valid_numeric_params
from config import get_nas_mount
from plotter import plot_pe_loop
from processor.parse import parse_hysteresis

st.set_page_config(page_title="电学性能分析", layout="wide")

engine = get_engine()
NAS = get_nas_mount()

PARAM_COLS = get_valid_numeric_params('pvd_deposition', exclude_cols=['pvd_id', 'sample_id'])

def _elabel(col):
    labels = {
        'film_target_thickness_nm': 'Film Thk (nm)', 'top_elec_target_thickness_nm': 'Top Elec Thk (nm)',
        'al_power_w': 'Al Power (W)', 'sc_power_w': 'Sc Power (W)',
        'alsc_power_w': 'AlSc Power (W)', 'aln_power_w': 'AlN Power (W)',
        'n2_flow_sccm': 'N2 Flow (sccm)', 'ar_flow_sccm': 'Ar Flow (sccm)',
        'substrate_temp_set': 'Substrate Temp', 'target_dist_mm': 'Target Dist (mm)',
        'rotation_speed_rpm': 'Rotation (rpm)',
        'total_duration_sec': 'Duration (sec)', 'base_vacuum_pa': 'Base Vacuum (Pa)',
        'working_pressure_pa': 'Working Pressure (Pa)',
        'pulse_freq_khz': 'Pulse Freq (kHz)', 'pre_sputtering_min': 'Pre-sputter (min)',
    }
    return labels.get(col, col)

PARAM_LABELS = {col: _elabel(col) for col in PARAM_COLS}

ELEC_COLS = ['avg_pr', 'avg_ec', 'avg_pmax', 'avg_loop_area', 'avg_ec_pos', 'avg_ec_neg']
ELEC_LABELS = {
    'avg_pr': 'Avg Pr (uC/cm2)', 'avg_ec': 'Avg Ec (V)', 'avg_pmax': 'Avg Pmax (uC/cm2)',
    'avg_loop_area': 'Loop Area', 'avg_ec_pos': 'Avg Ec+ (V)', 'avg_ec_neg': 'Avg Ec- (V)',
}

PVD_COLS_SQL = ', '.join('p.' + c for c in PARAM_COLS)


@st.cache_data
def load_electrical_data():
    with engine.begin() as conn:
        return pd.read_sql(text("""
            SELECT ce.sample_id, substring(ce.sample_id, 1, 2) AS batch,
                   s.substrate_type, s.sample_type,
                   s.top_electrode_material, s.bottom_electrode_material,
                   ce.test_voltage, ce.period_ms, ce.profile,
                   ce.remnant_polarization_pr, ce.coercive_field_ec,
                   ce.ec_pos, ce.ec_neg, ce.pr_pos, ce.pr_neg,
                   ce.pmax, ce.pmin, ce.ps_pos, ce.ps_neg,
                   ce.loop_area, ce.v_max, ce.v_min, ce.data_points,
                   ce.raw_data_path
            FROM char_electrical ce
            JOIN samples s ON ce.sample_id = s.sample_id
            WHERE ce.test_type = 'PE_Loop'
        """), conn)


@st.cache_data
def load_per_sample_agg():
    with engine.begin() as conn:
        return pd.read_sql(text("""
            SELECT s.sample_id, substring(s.sample_id,1,2) AS batch,
                   s.substrate_type, s.sample_type,
                   s.top_electrode_material, s.bottom_electrode_material,
                   AVG(ce.remnant_polarization_pr) AS avg_pr,
                   AVG(ce.coercive_field_ec) AS avg_ec,
                   AVG(ce.ec_pos) AS avg_ec_pos,
                   AVG(ce.ec_neg) AS avg_ec_neg,
                   AVG(ce.pmax) AS avg_pmax,
                   AVG(ce.pmin) AS avg_pmin,
                   AVG(ce.ps_pos) AS avg_ps_pos,
                   AVG(ce.ps_neg) AS avg_ps_neg,
                   AVG(ce.loop_area) AS avg_loop_area,
                   AVG(ce.test_voltage) AS avg_test_v,
                   MAX(ce.test_voltage) AS max_test_v,
                   COUNT(*) AS curve_count,
                   {}
            FROM char_electrical ce
            JOIN samples s ON ce.sample_id = s.sample_id
            JOIN pvd_deposition p ON ce.sample_id = p.sample_id
            WHERE ce.test_type = 'PE_Loop'
            GROUP BY s.sample_id, s.substrate_type, s.sample_type,
                     s.top_electrode_material, s.bottom_electrode_material,
                     {}
        """.format(PVD_COLS_SQL, PVD_COLS_SQL)), conn)


raw_df = load_electrical_data()
agg_df = load_per_sample_agg()

# ── Sidebar ──
with st.sidebar:
    st.title("电学性能分析")
    st.markdown("---")
    batches_avail = sorted(agg_df['batch'].unique().tolist())
    selected_batches = st.multiselect("批次筛选", batches_avail, default=batches_avail)
    st.markdown("---")

    st.markdown("### 异常检测规则")

    rule_pmax = st.checkbox("Pmax 过高", value=True,
                            help="漏电器件极化值异常高")
    pmax_thresh = st.number_input("Pmax > (μC/cm²)", value=200.0, step=10.0)

    rule_pr_ratio = st.checkbox("Pr/Pmax 比值异常", value=True,
                                help="矩形回线 → 漏电积分")
    pr_ratio_thresh = st.number_input("Pr/Pmax >", value=0.95, step=0.01, format="%.2f")

    rule_ec = st.checkbox("Ec 过小", value=True,
                          help="无矫顽场 → 非铁电体")
    ec_thresh = st.number_input("Ec < (V)", value=0.1, step=0.01, format="%.3f")

    rule_fullness = st.checkbox("回线不饱满", value=True,
                                help="P_at_Vmax / Pmax 过低 → 斜窄线而非饱满椭圆")
    fullness_thresh = st.number_input("Fullness <", value=0.5, step=0.05, format="%.2f")

    rule_ec_asym = st.checkbox("Ec 不对称", value=False,
                               help="正负矫顽场差距过大")
    ec_asym_thresh = st.number_input("|Ec+ - Ec-| > (V)", value=10.0, step=1.0)

# Filter by batch
agg_sel = agg_df[agg_df['batch'].isin(selected_batches)].copy()
raw_sel = raw_df[raw_df['batch'].isin(selected_batches)]


# ── Anomaly Detection ──
def detect_anomalies(df):
    anomaly = pd.Series(False, index=df.index)
    reasons = pd.Series('', index=df.index)

    if rule_pmax:
        mask = df['avg_pmax'].abs() > pmax_thresh
        anomaly = anomaly | mask
        reasons = reasons.where(~mask, reasons + 'Pmax_high;')

    if rule_pr_ratio:
        ratio = df['avg_pr'].abs() / (df['avg_pmax'].abs() + 1e-10)
        mask = ratio > pr_ratio_thresh
        anomaly = anomaly | mask
        reasons = reasons.where(~mask, reasons + 'Pr_ratio;')

    if rule_ec:
        mask = df['avg_ec'] < ec_thresh
        anomaly = anomaly | mask
        reasons = reasons.where(~mask, reasons + 'Ec_low;')

    if rule_fullness:
        sat = np.maximum(df['avg_ps_pos'].fillna(0).abs(), df['avg_ps_neg'].fillna(0).abs())
        fullness = sat / (df['avg_pmax'].abs() + 1e-10)
        mask = fullness < fullness_thresh
        anomaly = anomaly | mask
        reasons = reasons.where(~mask, reasons + 'Not_full;')

    if rule_ec_asym:
        asym = (df['avg_ec_pos'].fillna(0) - df['avg_ec_neg'].fillna(0)).abs()
        mask = asym > ec_asym_thresh
        anomaly = anomaly | mask
        reasons = reasons.where(~mask, reasons + 'Ec_asym;')

    return anomaly.values, reasons.values


is_anom, anom_reason = detect_anomalies(agg_sel)
agg_sel['is_anomaly'] = is_anom
agg_sel['anomaly_reason'] = anom_reason

normal_df = agg_sel[~agg_sel['is_anomaly']]
anomaly_df = agg_sel[agg_sel['is_anomaly']]

# ═══════════════ Header ═══════════════
st.title("电学性能分析")
cols = st.columns(5)
cols[0].metric("总样品", len(agg_sel))
cols[1].metric("正常", len(normal_df))
cols[2].metric("疑似异常", len(anomaly_df))
cols[3].metric("异常率", "{:.1f}%".format(100 * len(anomaly_df) / max(len(agg_sel), 1)))
cols[4].metric("总曲线", len(raw_sel))

# ═══════════════ Section 1: Sample explorer + PE Loop ═══════════════
st.divider()
st.subheader("样品检索")

filter_mode = st.radio("显示模式", ["仅异常", "全部", "仅正常"], horizontal=True, key='filter_mode')

if filter_mode == "仅异常":
    show_df = anomaly_df.copy()
elif filter_mode == "仅正常":
    show_df = normal_df.copy()
else:
    show_df = agg_sel.copy()

if len(show_df) > 0:
    show_cols = ['sample_id', 'batch', 'avg_pr', 'avg_ec', 'avg_pmax',
                 'avg_loop_area', 'curve_count', 'anomaly_reason']
    show_df = show_df[show_cols].copy()
    for c in ['avg_pr', 'avg_ec', 'avg_pmax', 'avg_loop_area']:
        show_df[c] = show_df[c].apply(lambda x: round(float(x), 4) if pd.notna(x) else None)
    show_df = show_df.sort_values('avg_pmax', ascending=False)

    event = st.dataframe(
        show_df, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            'sample_id': st.column_config.TextColumn('Sample ID'),
            'avg_pr': st.column_config.NumberColumn('Avg Pr', format='%.4f'),
            'avg_ec': st.column_config.NumberColumn('Avg Ec', format='%.4f'),
            'avg_pmax': st.column_config.NumberColumn('Avg Pmax', format='%.2f'),
            'anomaly_reason': st.column_config.TextColumn('异常原因'),
        }
    )

    if event.get('selection', {}).get('rows'):
        row_idx = event['selection']['rows'][0]
        selected_sid = show_df.iloc[row_idx]['sample_id']
        st.divider()
        st.subheader("PE Loop — {}".format(selected_sid))

        curves = raw_sel[raw_sel['sample_id'] == selected_sid].sort_values('test_voltage')

        if len(curves) > 0:
            is_anom_flag = agg_sel[agg_sel['sample_id'] == selected_sid]['is_anomaly'].values[0]
            reason = agg_sel[agg_sel['sample_id'] == selected_sid]['anomaly_reason'].values[0]

            mc = st.columns(6)
            mc[0].metric("Curves", len(curves))
            mc[1].metric("Avg Pr", "{:.4f}".format(float(curves['remnant_polarization_pr'].mean())))
            mc[2].metric("Avg Ec", "{:.4f}".format(float(curves['coercive_field_ec'].mean())))
            mc[3].metric("Pmax", "{:.2f}".format(float(curves['pmax'].max())))
            mc[4].metric("Status", "ANOMALY" if is_anom_flag else "Normal",
                         delta=reason if is_anom_flag else None)
            mc[5].metric("Batch", str(curves.iloc[0]['batch']))

            curve_count = len(curves)
            ncols = min(3, curve_count)
            cols = st.columns(ncols)
            for i, (_, crow) in enumerate(curves.iterrows()):
                fp = os.path.join(NAS, str(crow['raw_data_path']))
                with cols[i % ncols]:
                    try:
                        fig = plot_pe_loop(fp, "{} | {:.0f}V".format(selected_sid, float(crow['test_voltage'])))
                        st.pyplot(fig)
                    except Exception:
                        st.warning("无法读取")
        else:
            st.info("无曲线数据")
else:
    st.info("当前筛选条件下无样品")

# ═══════════════ Section 2: Distributions ═══════════════
st.divider()
st.subheader("电学指标分布")
st.caption("蓝色=正常  红色=异常")

fig, axes = plt.subplots(1, 3, figsize=(16, 5))
metric_pairs = [
    ('avg_pr', 'Pr (μC/cm²)'),
    ('avg_ec', 'Ec (V)'),
    ('avg_pmax', 'Pmax (μC/cm²)'),
]

for ax, (col, label) in zip(axes, metric_pairs):
    n_vals = pd.to_numeric(normal_df[col], errors='coerce').dropna()
    a_vals = pd.to_numeric(anomaly_df[col], errors='coerce').dropna()
    all_vals = pd.concat([n_vals, a_vals])
    if len(all_vals) == 0:
        ax.set_title(label + ' (no data)')
        continue
    bins = min(30, max(5, len(all_vals) // 4))
    b_min, b_max = float(all_vals.min()), float(all_vals.max())
    if len(n_vals) > 0:
        ax.hist(n_vals, bins=bins, range=(b_min, b_max), color='steelblue', alpha=0.7, label='Normal', edgecolor='white')
    if len(a_vals) > 0:
        ax.hist(a_vals, bins=bins, range=(b_min, b_max), color='crimson', alpha=0.5, label='Anomaly', edgecolor='white')
    ax.set_xlabel(label)
    ax.set_ylabel('Count')
    ax.legend(fontsize=8)
    ax.set_title(label)

fig.tight_layout()
st.pyplot(fig)

# ═══════════════ Section 3: Process-Property Correlation ═══════════════
st.divider()
st.subheader("工艺-性能关联")

c1, c2, c3 = st.columns(3)
with c1:
    x_param = st.selectbox("X 轴 (工艺参数)", PARAM_COLS, format_func=lambda x: PARAM_LABELS.get(x, x))
with c2:
    y_elec = st.selectbox("Y 轴 (电学指标)", ELEC_COLS, format_func=lambda x: ELEC_LABELS.get(x, x))
with c3:
    include_anomaly = st.checkbox("包含异常样品", value=False)

plot_df = agg_sel if include_anomaly else normal_df

if x_param and y_elec and len(plot_df) > 2:
    x_vals = pd.to_numeric(plot_df[x_param], errors='coerce')
    y_vals = pd.to_numeric(plot_df[y_elec], errors='coerce')
    valid = x_vals.notna() & y_vals.notna()
    x_vals = x_vals[valid].astype(float)
    y_vals = y_vals[valid].astype(float)

    fig, ax = plt.subplots(figsize=(10, 6))
    mask_anom = plot_df['is_anomaly'].values[valid.values] if include_anomaly else np.zeros(len(x_vals), dtype=bool)
    colors = np.where(mask_anom, 'crimson', 'steelblue')
    ax.scatter(x_vals, y_vals, c=colors, alpha=0.7, s=50, edgecolors='white', linewidth=0.5)

    if len(x_vals) > 2:
        try:
            coef = np.polyfit(x_vals, y_vals, 1)
            x_line = np.linspace(x_vals.min(), x_vals.max(), 100)
            ax.plot(x_line, np.polyval(coef, x_line), 'r--', linewidth=1.5, alpha=0.7)
            r = np.corrcoef(x_vals, y_vals)[0, 1]
            ax.set_title('r = {:.4f}'.format(r), fontsize=10, color='red')
        except Exception:
            pass

    ax.set_xlabel(PARAM_LABELS.get(x_param, x_param))
    ax.set_ylabel(ELEC_LABELS.get(y_elec, y_elec))
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    st.pyplot(fig)
else:
    st.info("数据不足")
# ═══════════════ Section 4: Multi-sample PE Loop comparison ═══════════════
st.divider()
st.subheader("多样品 PE Loop 对比")
st.caption("选择样品和曲线，在同一张图上叠加完整的 PE 电滞回线")

sample_options = sorted(raw_sel['sample_id'].unique())
compare_samples = st.multiselect("选择样品 (1-6个)", sample_options, max_selections=6, key='multi_sample')

if compare_samples:
    # ── Build curve filter list from selected samples ──
    selected_curves = raw_sel[raw_sel['sample_id'].isin(compare_samples)].copy()
    selected_curves['_basename'] = selected_curves['raw_data_path'].apply(
        lambda x: os.path.basename(str(x)) if pd.notna(x) else '')
    selected_curves['_tv_str'] = selected_curves['test_voltage'].apply(
        lambda x: '{:.0f}V'.format(float(x)) if pd.notna(x) else '')
    selected_curves['_freq'] = selected_curves['period_ms'].apply(
        lambda x: '{}Hz'.format(500 if float(x) < 5 else 50) if pd.notna(x) else '')
    selected_curves['_label'] = (selected_curves['sample_id'] + ' | ' +
        selected_curves['_basename'] + ' | ' +
        selected_curves['_tv_str'] + ' ' + selected_curves['_freq'])

    curve_labels = selected_curves['_label'].tolist()
    curve_paths = selected_curves['raw_data_path'].tolist()

    # Default: select all curves
    selected_labels = st.multiselect(
        "选择要绘制的曲线 (默认全选，可取消勾选不需要的)",
        curve_labels, default=curve_labels, key='curve_filter')

    if selected_labels:
        # Get selected indices
        selected_indices = [curve_labels.index(lbl) for lbl in selected_labels]
        filtered = selected_curves.iloc[selected_indices]

        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            plot_mode = st.radio("显示模式", ["全部曲线", "平均曲线"], horizontal=True, key='loop_mode',
                help="全部曲线: 每条独立图例 | 平均曲线: 同一样品所有选中曲线求一条均值")
        with mc2:
            custom_range = st.checkbox("自定义坐标范围", value=False, key='custom_range')
        with mc3:
            st.caption("已选 {} 条曲线".format(len(selected_labels)))

        if custom_range:
            rc1, rc2, rc3, rc4 = st.columns(4)
            with rc1: x_min = st.number_input("V min", value=-100.0, step=10.0)
            with rc2: x_max = st.number_input("V max", value=100.0, step=10.0)
            with rc3: y_min = st.number_input("P min", value=-200.0, step=10.0)
            with rc4: y_max = st.number_input("P max", value=200.0, step=10.0)

        fig, ax = plt.subplots(figsize=(14, 9))

        if plot_mode == "全部曲线":
            # One consistent style per curve, all in legend
            sample_colors = {}
            for i, sid in enumerate(compare_samples):
                sample_colors[sid] = plt.cm.tab10(i % 10)

            for _, crow in filtered.iterrows():
                fp = os.path.join(NAS, str(crow['raw_data_path']))
                try:
                    hdata = parse_hysteresis(fp)
                    sid = crow['sample_id']
                    label = crow['_label']
                    c = sample_colors.get(sid, 'gray')
                    ax.plot(hdata.voltage, hdata.polarization, color=c,
                            linewidth=1.0, alpha=0.7, label=label)
                except Exception:
                    pass

        else:  # 平均曲线 — one averaged curve per sample
            for idx, sid in enumerate(compare_samples):
                sample_curves = filtered[filtered['sample_id'] == sid]
                if len(sample_curves) == 0:
                    continue
                all_v, all_p = [], []
                for _, crow in sample_curves.iterrows():
                    fp = os.path.join(NAS, str(crow['raw_data_path']))
                    try:
                        hdata = parse_hysteresis(fp)
                        all_v.append(np.array(hdata.voltage, dtype=np.float64))
                        all_p.append(np.array(hdata.polarization, dtype=np.float64))
                    except Exception:
                        pass
                if len(all_v) > 0:
                    v_min = float(min(v.min() for v in all_v))
                    v_max = float(max(v.max() for v in all_v))
                    v_grid = np.linspace(v_min, v_max, 500)
                    p_interp = []
                    for v_arr, p_arr in zip(all_v, all_p):
                        p_interp.append(np.interp(v_grid, v_arr, p_arr))
                    p_mean = np.mean(p_interp, axis=0)
                    c = plt.cm.tab10(idx % 10)
                    label = '{} | avg (n={})'.format(sid, len(sample_curves))
                    ax.plot(v_grid, p_mean, color=c, linewidth=2.0, alpha=0.95, label=label)
                    if len(p_interp) > 1:
                        p_std = np.std(p_interp, axis=0)
                        ax.fill_between(v_grid, p_mean - p_std, p_mean + p_std, color=c, alpha=0.1)

        ax.axhline(y=0, color='gray', linewidth=0.5, linestyle='--')
        ax.axvline(x=0, color='gray', linewidth=0.5, linestyle='--')
        ax.set_xlabel('Voltage (V)')
        ax.set_ylabel('Polarization (uC/cm2)')
        ax.set_title('PE Loop Comparison')

        n_lines = len(ax.get_lines())
        if n_lines > 15:
            ax.legend(fontsize=5.5, loc='upper left', ncol=3, bbox_to_anchor=(1.01, 1.0))
        elif n_lines > 8:
            ax.legend(fontsize=6.5, loc='upper left', ncol=2)
        else:
            ax.legend(fontsize=8, loc='upper left')
        ax.grid(True, alpha=0.3)

        if custom_range:
            ax.set_xlim(x_min, x_max)
            ax.set_ylim(y_min, y_max)

        fig.tight_layout()
        st.pyplot(fig)
    else:
        st.info("请至少选择一条曲线")
else:
    st.info("请选择至少 1 个样品")
