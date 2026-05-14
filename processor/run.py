"""
PVD PE Loop Processor v2 - with corrected column mapping.
Run inside Docker: docker exec pvd_dashboard python processor/run.py
"""
import os, sys, re, zipfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db import get_engine
from config import get_nas_mount
from processor.parse import parse_hysteresis, parse_filename
from processor.metrics import extract_all_metrics

NAS = get_nas_mount()
PARAM_DIR = os.path.join(NAS, 'parameter')


def discover_batches():
    batches = []
    if not os.path.isdir(PARAM_DIR):
        return batches
    for entry in sorted(os.listdir(PARAM_DIR)):
        entry_path = os.path.join(PARAM_DIR, entry)
        if not os.path.isdir(entry_path):
            continue
        m = re.match(r'(P\d+)-\d+-\d+', entry)
        if not m: continue
        prefix = m.group(1)
        date = None
        for f in os.listdir(entry_path):
            xm = re.match(r'{}-(\d{{8}})\.xlsx'.format(prefix), f)
            if xm:
                date = xm.group(1)
                break
        if not date: continue
        raw_dir = None; raw_zip = None
        for f in os.listdir(entry_path):
            full = os.path.join(entry_path, f)
            if os.path.isdir(full) and '铁电' in f: raw_dir = full
            elif f.endswith('.zip') and '铁电' in f: raw_zip = full
        if raw_dir or raw_zip:
            batches.append({'prefix': prefix, 'date': date, 'raw_dir': raw_dir, 'raw_zip': raw_zip})
    return batches


def collect_raw_files(batch):
    files = []
    if batch['raw_dir']:
        for f in os.listdir(batch['raw_dir']):
            info = parse_filename(f)
            if info:
                sn, pos, curve = info
                files.append({'sample_num': sn, 'position': pos, 'curve': curve,
                              'filepath': os.path.join(batch['raw_dir'], f)})
    if batch['raw_zip']:
        try:
            with zipfile.ZipFile(batch['raw_zip'], 'r') as z:
                for name in z.namelist():
                    basename = os.path.basename(name)
                    info = parse_filename(basename)
                    if info:
                        sn, pos, curve = info
                        files.append({'sample_num': sn, 'position': pos, 'curve': curve,
                                      'filepath': batch['raw_zip'] + '/' + name})
        except Exception as e:
            print("  ERROR zip {}: {}".format(batch['raw_zip'], e))
    return files


def ensure_columns(engine):
    """Add extended test parameter columns."""
    cols = [
        ('ec_pos', 'DOUBLE PRECISION'), ('ec_neg', 'DOUBLE PRECISION'),
        ('pr_pos', 'DOUBLE PRECISION'), ('pr_neg', 'DOUBLE PRECISION'),
        ('pmax', 'DOUBLE PRECISION'), ('pmin', 'DOUBLE PRECISION'),
        ('ps_pos', 'DOUBLE PRECISION'), ('ps_neg', 'DOUBLE PRECISION'),
        ('loop_area', 'DOUBLE PRECISION'),
        ('v_max', 'DOUBLE PRECISION'), ('v_min', 'DOUBLE PRECISION'),
        ('data_points', 'INTEGER'),
        ('test_voltage', 'DOUBLE PRECISION'),
        ('period_ms', 'DOUBLE PRECISION'),
        ('profile', 'VARCHAR(50)'),
        ('task_name', 'VARCHAR(50)'),
        ('sample_area_cm2', 'DOUBLE PRECISION'),
    ]
    with engine.begin() as conn:
        for cname, ctype in cols:
            try:
                conn.execute(text(
                    "ALTER TABLE char_electrical ADD COLUMN IF NOT EXISTS {} {}".format(cname, ctype)
                ))
            except Exception:
                pass


SQL_INSERT = """
    INSERT INTO char_electrical (
        sample_id, raw_data_path, test_type, test_date,
        remnant_polarization_pr, coercive_field_ec,
        ec_pos, ec_neg, pr_pos, pr_neg,
        pmax, pmin, ps_pos, ps_neg,
        loop_area, v_max, v_min, data_points,
        test_voltage, period_ms, profile, task_name, sample_area_cm2
    ) VALUES (
        :sid, :path, 'PE_Loop', :test_date,
        :pr, :ec,
        :ec_pos, :ec_neg, :pr_pos, :pr_neg,
        :pmax, :pmin, :ps_pos, :ps_neg,
        :loop_area, :v_max, :v_min, :dp,
        :test_v, :period, :profile, :task, :area
    )
    ON CONFLICT (sample_id, raw_data_path) DO UPDATE SET
        remnant_polarization_pr = EXCLUDED.remnant_polarization_pr,
        coercive_field_ec = EXCLUDED.coercive_field_ec,
        ec_pos = EXCLUDED.ec_pos, ec_neg = EXCLUDED.ec_neg,
        pr_pos = EXCLUDED.pr_pos, pr_neg = EXCLUDED.pr_neg,
        pmax = EXCLUDED.pmax, pmin = EXCLUDED.pmin,
        ps_pos = EXCLUDED.ps_pos, ps_neg = EXCLUDED.ps_neg,
        loop_area = EXCLUDED.loop_area,
        v_max = EXCLUDED.v_max, v_min = EXCLUDED.v_min,
        data_points = EXCLUDED.data_points,
        test_voltage = EXCLUDED.test_voltage,
        period_ms = EXCLUDED.period_ms,
        profile = EXCLUDED.profile,
        task_name = EXCLUDED.task_name,
        sample_area_cm2 = EXCLUDED.sample_area_cm2
"""


def process_single(engine, rf, prefix, date):
    sample_id = '{}-{}-{:02d}'.format(prefix, date, rf['sample_num'])

    with engine.begin() as conn:
        exists = conn.execute(
            text('SELECT 1 FROM samples WHERE sample_id = :sid'),
            {'sid': sample_id}
        ).fetchone()
    if not exists:
        return 'skip', sample_id

    filepath = rf['filepath']
    rel_path = os.path.relpath(filepath, NAS) if filepath.startswith(NAS) else filepath

    try:
        hdata = parse_hysteresis(filepath)
        metrics = extract_all_metrics(hdata.voltage, hdata.polarization)
    except Exception:
        return 'error', sample_id

    tp = hdata.test_params
    try:
        with engine.begin() as conn:
            conn.execute(text(SQL_INSERT), {
                'sid': sample_id, 'path': rel_path, 'test_date': date,
                'pr': metrics.get('pr'),
                'ec': max(metrics.get('ec_pos') or 0, metrics.get('ec_neg') or 0),
                'ec_pos': metrics.get('ec_pos'), 'ec_neg': metrics.get('ec_neg'),
                'pr_pos': metrics.get('pr_pos'), 'pr_neg': metrics.get('pr_neg'),
                'pmax': metrics.get('pmax'), 'pmin': metrics.get('pmin'),
                'ps_pos': metrics.get('ps_pos'), 'ps_neg': metrics.get('ps_neg'),
                'loop_area': metrics.get('loop_area'),
                'v_max': metrics.get('v_max'), 'v_min': metrics.get('v_min'),
                'dp': metrics.get('data_points'),
                'test_v': tp.get('test_voltage'),
                'period': tp.get('period_ms'),
                'profile': tp.get('profile'),
                'task': tp.get('task_name'),
                'area': tp.get('sample_area_cm2'),
            })
        return 'ok', sample_id
    except Exception:
        return 'error', sample_id


def process_batch(batch, engine):
    prefix, date = batch['prefix'], batch['date']
    raw_files = collect_raw_files(batch)
    print("\n  Batch {}-{}: {} raw files".format(prefix, date, len(raw_files)))
    if not raw_files:
        return 0, 0, 0
    raw_files.sort(key=lambda x: (x['sample_num'], x['position'], x['curve']))
    ok, skip, err = 0, 0, 0
    for rf in raw_files:
        status, _ = process_single(engine, rf, prefix, date)
        if status == 'ok': ok += 1
        elif status == 'skip': skip += 1
        else: err += 1
        if (ok + skip + err) % 100 == 0:
            print("    Progress: {} done...".format(ok + skip + err))
    print("    Inserted: {}, Skipped: {}, Errors: {}".format(ok, skip, err))
    return ok, skip, err


def run():
    print("=" * 60)
    print("PVD PE Loop Processor v2 (corrected column mapping)")
    print("=" * 60)
    engine = get_engine()
    print("\nEnsuring columns...")
    ensure_columns(engine)

    # Clear old data (with wrong column mapping)
    with engine.begin() as conn:
        result = conn.execute(text("DELETE FROM char_electrical WHERE test_type = 'PE_Loop'"))
        print("Cleared {} old records".format(result.rowcount))

    batches = discover_batches()
    print("\nFound {} batches".format(len(batches)))
    total_ok, total_skip, total_err = 0, 0, 0
    for batch in batches:
        ok, skip, err = process_batch(batch, engine)
        total_ok += ok; total_skip += skip; total_err += err

    print("\n" + "=" * 60)
    print("DONE. OK: {}, Skip: {}, Err: {}".format(total_ok, total_skip, total_err))
    with engine.begin() as conn:
        r = conn.execute(text(
            "SELECT count(*), count(DISTINCT sample_id) FROM char_electrical WHERE test_type = 'PE_Loop'"
        )).fetchone()
        r2 = conn.execute(text(
            "SELECT count(DISTINCT test_voltage), count(DISTINCT profile) FROM char_electrical WHERE test_type = 'PE_Loop'"
        )).fetchone()
        print("Records: {}, Samples: {}, Unique test voltages: {}, Profiles: {}".format(r[0], r[1], r2[0], r2[1]))
    print("=" * 60)


if __name__ == '__main__':
    run()
