"""
Batch import v2 — handles evolving Excel column headers across batches.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np
import re
from sqlalchemy import text
from db import get_engine
from config import get_nas_mount

NAS = get_nas_mount()
PARAM_DIR = os.path.join(NAS, 'parameter')

# ── Column aliases: DB column -> possible Excel header names ──
# Order matters: first match wins for each DB column
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

# Non-numeric/categorical columns
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

# Track warnings
warnings = []


def find_column(df, aliases):
    """Find a column in DataFrame by trying multiple possible names."""
    for name in aliases:
        if name in df.columns:
            return name
    return None


def _warn(msg):
    warnings.append(msg)
    print('  WARNING: ' + msg)


def clean_num(val):
    if pd.isna(val) or str(val).strip() in ['/', '', 'nan', 'None', 'NaN']:
        return None
    s = str(val).replace(' ', '').upper()
    # Handle values like "100W" — extract number
    match = re.search(r"[-+]?\d*\.?\d+(?:E[-+]?\d+)?", s)
    if match:
        try:
            return float(match.group(0))
        except (ValueError, TypeError):
            return None
    return None


def discover_excel_files():
    excels = []
    for entry in sorted(os.listdir(PARAM_DIR)):
        entry_path = os.path.join(PARAM_DIR, entry)
        if not os.path.isdir(entry_path):
            continue
        for f in os.listdir(entry_path):
            m = re.match(r'(P\d+)-(\d{8})\.xlsx', f)
            if m and not f.startswith('~$'):
                excels.append({
                    'prefix': m.group(1),
                    'date': m.group(2),
                    'path': os.path.join(entry_path, f),
                    'dir': entry,
                })
    return excels


def import_excel(excel_info, engine):
    filepath = excel_info['path']
    prefix = excel_info['prefix']
    date = excel_info['date']

    print('\n  [{}-{}] Reading {}...'.format(prefix, date, os.path.basename(filepath)))
    df = pd.read_excel(filepath)

    # Detect unknown columns
    known_aliases = set()
    for aliases in list(COLUMN_MAP.values()) + list(CATEGORICAL_MAP.values()):
        known_aliases.update(aliases)
    for col in df.columns:
        if col not in known_aliases and col not in ['样品编号']:
            _warn('Unknown column in {}: [{}] — NOT imported'.format(prefix, col))

    count = 0
    skipped = 0

    with engine.begin() as conn:
        for _, row in df.iterrows():
            raw_id = str(row['样品编号']).replace('#', '').strip()
            if not raw_id.isdigit():
                skipped += 1
                continue
            sid = '{}-{}-{}'.format(prefix, date, raw_id.zfill(2))

            # ── Resolve all column values ──
            params = {}
            for db_col, aliases in COLUMN_MAP.items():
                excel_col = find_column(df, aliases)
                if excel_col:
                    params[db_col] = clean_num(row.get(excel_col))
                else:
                    params[db_col] = None

            # Categorical values
            cat_values = {}
            for db_col, aliases in CATEGORICAL_MAP.items():
                excel_col = find_column(df, aliases)
                if excel_col:
                    val = row.get(excel_col)
                    cat_values[db_col] = str(val) if pd.notna(val) and str(val).strip() not in ['/', ''] else None
                else:
                    cat_values[db_col] = None

            # Convert total_duration from minutes to seconds
            if params.get('total_duration_sec') is not None:
                params['total_duration_sec'] = int(params['total_duration_sec'] * 60)

            # Convert base_vacuum from mbar to Pa
            if params.get('base_vacuum_pa') is not None:
                params['base_vacuum_pa'] = params['base_vacuum_pa'] * 100

            # Convert working_pressure from mbar to Pa
            if params.get('working_pressure_pa') is not None:
                params['working_pressure_pa'] = params['working_pressure_pa'] * 100

            # ── samples table ──
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
                'sid': sid,
                'sub_t': cat_values.get('substrate_type'),
                'sub_i': cat_values.get('substrate_info'),
                'sam_t': cat_values.get('sample_type'),
                'tem': cat_values.get('top_electrode_material'),
                'bem': cat_values.get('bottom_electrode_material'),
                'temm': cat_values.get('top_electrode_method'),
                'tag': cat_values.get('batch_tag'),
            })

            # ── pvd_deposition table ──
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
                'dur': params.get('total_duration_sec'),
                'bvac': params.get('base_vacuum_pa'),
                'wp': params.get('working_pressure_pa'),
                'dv': params.get('discharge_voltage_v'),
                'dc': params.get('discharge_current_a'),
                'freq': params.get('pulse_freq_khz'),
                'duty': params.get('duty_cycle_pct'),
                'model': cat_values.get('equipment_model'),
                'rem': cat_values.get('remarks'),
                'ano': cat_values.get('anomalies'),
            })
            count += 1

    return count, skipped


def ensure_columns(engine):
    """Add missing columns."""
    new_cols = [
        ('alsc_power_w', 'DOUBLE PRECISION'),
        ('aln_power_w', 'DOUBLE PRECISION'),
    ]
    with engine.begin() as conn:
        for cname, ctype in new_cols:
            try:
                conn.execute(text(
                    'ALTER TABLE pvd_deposition ADD COLUMN IF NOT EXISTS {} {}'.format(cname, ctype)
                ))
            except Exception as e:
                print('  Column {}: {}'.format(cname, e))


def run():
    global warnings
    print('=' * 60)
    print('BATCH IMPORT v2 — fuzzy column matching')
    print('=' * 60)

    engine = get_engine()

    print('\nEnsuring columns...')
    ensure_columns(engine)

    excels = discover_excel_files()
    print('\nFound {} Excel files'.format(len(excels)))

    total = 0
    for e in excels:
        count, skipped = import_excel(e, engine)
        total += count
        print('    Imported: {}, Skipped: {}'.format(count, skipped))

    print('\n' + '=' * 60)
    print('Total imported: {} records'.format(total))

    if warnings:
        print('\nWARNINGS ({}):'.format(len(warnings)))
        for w in warnings:
            print('  - ' + w)

    # Verify
    with engine.begin() as conn:
        r = conn.execute(text(
            "SELECT substring(sample_id,1,2) as batch, count(*) FROM samples GROUP BY 1 ORDER BY 1"
        )).fetchall()
        print('\nSample counts:')
        for batch, cnt in r:
            print('  {}: {}'.format(batch, cnt))

        # Check P5 temp
        p5_temp = conn.execute(text(
            "SELECT count(*) FROM pvd_deposition WHERE sample_id LIKE 'P5-%' AND substrate_temp_set IS NOT NULL"
        )).fetchone()[0]
        print('\nP5 temperature present: {}/49'.format(p5_temp))

        # Check new columns
        alsc = conn.execute(text(
            "SELECT count(*) FROM pvd_deposition WHERE alsc_power_w IS NOT NULL"
        )).fetchone()[0]
        aln = conn.execute(text(
            "SELECT count(*) FROM pvd_deposition WHERE aln_power_w IS NOT NULL"
        )).fetchone()[0]
        print('AlSc data: {} records, AlN data: {} records'.format(alsc, aln))

    print('=' * 60)


if __name__ == '__main__':
    run()
