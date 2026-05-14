"""
Shared import utilities — fuzzy column matching for evolving Excel headers.
Used by both batch_import_v2.py and pages/2_import.py
"""
import re
import pandas as pd
from sqlalchemy import text

# ── Column aliases: DB column -> list of possible Excel header names ──
COLUMN_MAP = {
    'film_target_thickness_nm':       ['膜层厚度(nm)'],
    'top_elec_target_thickness_nm':   ['顶电极厚度(nm)'],
    'bottom_elec_target_thickness_nm': ['底电极厚度(nm)'],
    'al_power_w':                     ['Al(W)'],
    'sc_power_w':                     ['Sc(W)'],
    'alsc_power_w':                   ['AlSc(W)/电压', 'AlSc(W)'],
    'aln_power_w':                    ['AlN(W)/电压', 'AlN(W)'],
    'n2_flow_sccm':                   ['N2(sccm)'],
    'ar_flow_sccm':                   ['Ar2(sccm)'],
    'substrate_temp_set':             ['制备温度(°C)', '制备温度（°C）', '制备温度'],
    'bias_voltage_v':                 ['基底偏压'],
    'target_dist_mm':                 ['靶截距'],
    'sputter_angle_deg':              ['溅射角度（若有）', '溅射角度'],
    'rotation_speed_rpm':             ['基底转速'],
    'pre_sputtering_min':             ['预溅射时间（min）', '预溅射时间(min)'],
    'total_duration_sec':             ['总沉积时长（min）', '总沉积时长(min)'],
    'base_vacuum_pa':                 ['本底真空度'],
    'working_pressure_pa':            ['工作气压'],
    'discharge_voltage_v':            ['电压'],
    'discharge_current_a':            ['电流'],
    'pulse_freq_khz':                 ['脉冲频率'],
    'duty_cycle_pct':                 ['占空比（电信号相关，若有请提供）', '占空比'],
    'equipment_model':                ['设备型号'],
}

CATEGORICAL_MAP = {
    'substrate_type':               ['衬底类型'],
    'substrate_info':               ['衬底信息（如N/P型Si，掺杂浓度等）'],
    'sample_type':                  ['样品类型'],
    'top_electrode_material':       ['顶电极材料'],
    'bottom_electrode_material':    ['底电极材料'],
    'top_electrode_method':         ['顶电极制备方式（如光刻/硬掩膜）'],
    'batch_tag':                    ['归属（Pilot/Medium/Stable-A/B/C）'],
    'remarks':                      ['备注（重点需要做哪些测试）'],
    'anomalies':                    ['异常记录'],
}


def find_column(df, aliases):
    """Find a column in DataFrame by trying multiple possible names."""
    for name in aliases:
        if name in df.columns:
            return name
    return None


def clean_num(val):
    if pd.isna(val) or str(val).strip() in ['/', '', 'nan', 'None', 'NaN']:
        return None
    s = str(val).replace(' ', '').upper()
    match = re.search(r"[-+]?\d*\.?\d+(?:E[-+]?\d+)?", s)
    if match:
        try:
            return float(match.group(0))
        except (ValueError, TypeError):
            return None
    return None


def parse_batch_from_filename(filename):
    m = re.match(r'(P\d+)-(\d{8})\.xlsx?', filename)
    if m:
        return m.group(1), m.group(2)
    return None, None


def extract_params(df_row, excel_df):
    """Extract all parameter values from an Excel row. Returns dict."""
    params = {}
    for db_col, aliases in COLUMN_MAP.items():
        ec = find_column(excel_df, aliases)
        params[db_col] = clean_num(df_row.get(ec)) if ec else None

    cat_values = {}
    for db_col, aliases in CATEGORICAL_MAP.items():
        ec = find_column(excel_df, aliases)
        if ec:
            val = df_row.get(ec)
            cat_values[db_col] = str(val) if pd.notna(val) and str(val).strip() not in ['/', ''] else None
        else:
            cat_values[db_col] = None

    return params, cat_values


def import_row(conn, sid, params, cat_values):
    """Insert or update a single sample row into samples + pvd_deposition."""

    conn.execute(text("""
        INSERT INTO samples (sample_id, substrate_type, substrate_info, sample_type,
            top_electrode_material, bottom_electrode_material,
            top_electrode_method, batch_tag)
        VALUES (:sid, :sub_t, :sub_i, :sam_t, :tem, :bem, :temm, :tag)
        ON CONFLICT (sample_id) DO UPDATE SET
            substrate_info = EXCLUDED.substrate_info,
            top_electrode_material = EXCLUDED.top_electrode_material,
            bottom_electrode_material = EXCLUDED.bottom_electrode_material,
            batch_tag = EXCLUDED.batch_tag
    """), {
        'sid': sid, 'sub_t': cat_values.get('substrate_type'),
        'sub_i': cat_values.get('substrate_info'),
        'sam_t': cat_values.get('sample_type'),
        'tem': cat_values.get('top_electrode_material'),
        'bem': cat_values.get('bottom_electrode_material'),
        'temm': cat_values.get('top_electrode_method'),
        'tag': cat_values.get('batch_tag'),
    })

    # Unit conversions
    dur = params.get('total_duration_sec')
    if dur is not None:
        dur = int(dur * 60)
    bv = params.get('base_vacuum_pa')
    if bv is not None:
        bv = bv * 100
    wp = params.get('working_pressure_pa')
    if wp is not None:
        wp = wp * 100

    conn.execute(text("""
        INSERT INTO pvd_deposition (
            sample_id,
            film_target_thickness_nm, top_elec_target_thickness_nm,
            bottom_elec_target_thickness_nm,
            al_power_w, sc_power_w, alsc_power_w, aln_power_w,
            n2_flow_sccm, ar_flow_sccm,
            substrate_temp_set, bias_voltage_v,
            target_dist_mm, sputter_angle_deg, rotation_speed_rpm,
            pre_sputtering_min, total_duration_sec,
            base_vacuum_pa, working_pressure_pa,
            discharge_voltage_v, discharge_current_a,
            pulse_freq_khz, duty_cycle_pct,
            equipment_model, remarks, anomalies
        ) VALUES (
            :sid,
            :film, :top_elec, :bot_elec,
            :al, :sc, :alsc, :aln,
            :n2, :ar,
            :temp, :bias,
            :dist, :angle, :rot,
            :pre, :dur,
            :bvac, :wp,
            :dv, :dc,
            :freq, :duty,
            :model, :rem, :ano
        )
        ON CONFLICT (sample_id) DO UPDATE SET
            film_target_thickness_nm = EXCLUDED.film_target_thickness_nm,
            top_elec_target_thickness_nm = EXCLUDED.top_elec_target_thickness_nm,
            bottom_elec_target_thickness_nm = EXCLUDED.bottom_elec_target_thickness_nm,
            al_power_w = EXCLUDED.al_power_w,
            sc_power_w = EXCLUDED.sc_power_w,
            alsc_power_w = EXCLUDED.alsc_power_w,
            aln_power_w = EXCLUDED.aln_power_w,
            n2_flow_sccm = EXCLUDED.n2_flow_sccm,
            ar_flow_sccm = EXCLUDED.ar_flow_sccm,
            substrate_temp_set = EXCLUDED.substrate_temp_set,
            total_duration_sec = EXCLUDED.total_duration_sec,
            base_vacuum_pa = EXCLUDED.base_vacuum_pa,
            working_pressure_pa = EXCLUDED.working_pressure_pa,
            anomalies = EXCLUDED.anomalies,
            remarks = EXCLUDED.remarks,
            equipment_model = EXCLUDED.equipment_model
    """), {
        'sid': sid,
        'film': params.get('film_target_thickness_nm'),
        'top_elec': params.get('top_elec_target_thickness_nm'),
        'bot_elec': params.get('bottom_elec_target_thickness_nm'),
        'al': params.get('al_power_w'),
        'sc': params.get('sc_power_w'),
        'alsc': params.get('alsc_power_w'),
        'aln': params.get('aln_power_w'),
        'n2': params.get('n2_flow_sccm'),
        'ar': params.get('ar_flow_sccm'),
        'temp': params.get('substrate_temp_set'),
        'bias': params.get('bias_voltage_v'),
        'dist': params.get('target_dist_mm'),
        'angle': params.get('sputter_angle_deg'),
        'rot': params.get('rotation_speed_rpm'),
        'pre': params.get('pre_sputtering_min'),
        'dur': dur,
        'bvac': bv,
        'wp': wp,
        'dv': params.get('discharge_voltage_v'),
        'dc': params.get('discharge_current_a'),
        'freq': params.get('pulse_freq_khz'),
        'duty': params.get('duty_cycle_pct'),
        'model': cat_values.get('equipment_model'),
        'rem': cat_values.get('remarks'),
        'ano': cat_values.get('anomalies'),
    })
