"""
Batch import all P1-P5 Excel files + run electrical data processor.
Run inside Docker: docker exec pvd_dashboard python batch_import.py
"""
import os, sys, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from sqlalchemy import text
from db import get_engine
from config import get_nas_mount

NAS = get_nas_mount()
PARAM_DIR = os.path.join(NAS, 'parameter')


def clean_num(val):
    if pd.isna(val) or str(val).strip() in ['/', '', 'nan', 'None']:
        return None
    s = str(val).replace(' ', '').upper()
    match = re.search(r"[-+]?\d*\.?\d+(?:E[-+]?\d+)?", s)
    if match:
        try:
            return float(match.group(0))
        except (ValueError, TypeError):
            return None
    return None


def discover_excel_files():
    """Find all P-series Excel files in NAS parameter/."""
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
    """Import a single Excel file into the database."""
    filepath = excel_info['path']
    prefix = excel_info['prefix']
    date = excel_info['date']

    print("  Reading {}...".format(os.path.basename(filepath)))
    try:
        df = pd.read_excel(filepath)
    except Exception as e:
        print("    ERROR reading file: {}".format(e))
        return 0, 0

    count = 0
    skipped = 0

    with engine.begin() as conn:
        for _, row in df.iterrows():
            raw_id = str(row['样品编号']).replace('#', '').strip()
            if not raw_id.isdigit():
                skipped += 1
                continue
            sid = '{}-{}-{}'.format(prefix, date, raw_id.zfill(2))

            # samples table
            conn.execute(text("""
                INSERT INTO samples (sample_id, substrate_type, substrate_info, sample_type,
                    top_electrode_material, bottom_electrode_material, top_electrode_method, batch_tag)
                VALUES (:sid, :sub_t, :sub_i, :sam_t, :tem, :bem, :temm, :tag)
                ON CONFLICT (sample_id) DO UPDATE SET
                    substrate_info = EXCLUDED.substrate_info,
                    top_electrode_material = EXCLUDED.top_electrode_material,
                    bottom_electrode_material = EXCLUDED.bottom_electrode_material,
                    batch_tag = EXCLUDED.batch_tag
            """), {
                'sid': sid,
                'sub_t': row.get('衬底类型'),
                'sub_i': row.get('衬底信息（如N/P型Si，掺杂浓度等）'),
                'sam_t': row.get('样品类型'),
                'tem': row.get('顶电极材料'),
                'bem': row.get('底电极材料'),
                'temm': row.get('顶电极制备方式（如光刻/硬掩膜）'),
                'tag': row.get('归属（Pilot/Medium/Stable-A/B/C）'),
            })

            # pvd_deposition table
            base_pa = clean_num(row.get('本底真空度'))
            if base_pa is not None:
                base_pa *= 100
            work_pa = clean_num(row.get('工作气压'))
            if work_pa is not None:
                work_pa *= 100
            duration_sec = clean_num(row.get('总沉积时长（min）'))
            if duration_sec is not None:
                duration_sec = int(duration_sec * 60)

            conn.execute(text("""
                INSERT INTO pvd_deposition (
                    sample_id, top_elec_target_thickness_nm, film_target_thickness_nm,
                    bottom_elec_target_thickness_nm, al_power_w, sc_power_w,
                    n2_flow_sccm, ar_flow_sccm, substrate_temp_set, bias_voltage_v,
                    target_dist_mm, sputter_angle_deg, rotation_speed_rpm,
                    pre_sputtering_min, total_duration_sec, base_vacuum_pa,
                    working_pressure_pa, discharge_voltage_v, discharge_current_a,
                    pulse_freq_khz, duty_cycle_pct, equipment_model, remarks, anomalies
                ) VALUES (
                    :sid, :t_th, :f_th, :b_th, :al, :sc, :n2, :ar, :temp, :bias,
                    :dist, :ang, :rot, :pre, :dur, :base, :work, :volt, :curr,
                    :freq, :duty, :model, :rem, :ano
                )
                ON CONFLICT (sample_id) DO UPDATE SET
                    top_elec_target_thickness_nm = EXCLUDED.top_elec_target_thickness_nm,
                    film_target_thickness_nm = EXCLUDED.film_target_thickness_nm,
                    bottom_elec_target_thickness_nm = EXCLUDED.bottom_elec_target_thickness_nm,
                    al_power_w = EXCLUDED.al_power_w, sc_power_w = EXCLUDED.sc_power_w,
                    n2_flow_sccm = EXCLUDED.n2_flow_sccm, ar_flow_sccm = EXCLUDED.ar_flow_sccm,
                    substrate_temp_set = EXCLUDED.substrate_temp_set,
                    total_duration_sec = EXCLUDED.total_duration_sec,
                    base_vacuum_pa = EXCLUDED.base_vacuum_pa,
                    working_pressure_pa = EXCLUDED.working_pressure_pa,
                    anomalies = EXCLUDED.anomalies, remarks = EXCLUDED.remarks
            """), {
                'sid': sid,
                't_th': clean_num(row.get('顶电极厚度(nm)')),
                'f_th': clean_num(row.get('膜层厚度(nm)')),
                'b_th': clean_num(row.get('底电极厚度(nm)')),
                'al': clean_num(row.get('Al(W)')), 'sc': clean_num(row.get('Sc(W)')),
                'n2': clean_num(row.get('N2(sccm)')), 'ar': clean_num(row.get('Ar2(sccm)')),
                'temp': clean_num(row.get('制备温度')), 'bias': clean_num(row.get('基底偏压')),
                'dist': clean_num(row.get('靶截距')), 'ang': clean_num(row.get('溅射角度（若有）')),
                'rot': clean_num(row.get('基底转速')), 'pre': clean_num(row.get('预溅射时间（min）')),
                'dur': duration_sec, 'base': base_pa, 'work': work_pa,
                'volt': clean_num(row.get('电压')), 'curr': clean_num(row.get('电流')),
                'freq': clean_num(row.get('脉冲频率')),
                'duty': clean_num(row.get('占空比（电信号相关，若有请提供）')),
                'model': row.get('设备型号'), 'rem': row.get('备注（重点需要做哪些测试）'),
                'ano': row.get('异常记录'),
            })
            count += 1

    return count, skipped


def run():
    print("=" * 60)
    print("Batch Import: P1 - P5 Excel + Electrical Data")
    print("=" * 60)

    engine = get_engine()

    excels = discover_excel_files()
    print("\nFound {} Excel files:".format(len(excels)))
    for e in excels:
        print("  {}-{} from {}".format(e['prefix'], e['date'], e['dir']))

    # Phase 1: Import Excel files
    print("\n" + "=" * 60)
    print("Phase 1: Importing Excel files...")
    total_excel = 0
    for e in excels:
        print("\n  [{}-{}]".format(e['prefix'], e['date']))
        count, skipped = import_excel(e, engine)
        print("    Imported: {}, Skipped: {}".format(count, skipped))
        total_excel += count
    print("\n  Total Excel records: {}".format(total_excel))

    # Verify
    with engine.begin() as conn:
        result = conn.execute(text(
            "SELECT substring(sample_id, 1, 2) as batch, count(*) FROM samples GROUP BY 1 ORDER BY 1"
        )).fetchall()
        print("\n  Sample counts by batch:")
        for r in result:
            print("    {}: {}".format(r[0], r[1]))

    # Phase 2: Run processor for electrical data
    print("\n" + "=" * 60)
    print("Phase 2: Processing electrical raw data...")
    from processor.run import run as processor_run
    processor_run()

    print("\n" + "=" * 60)
    print("All done!")
    print("=" * 60)


if __name__ == '__main__':
    run()
