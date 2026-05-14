import os, re, zipfile
from sqlalchemy import text
from db import get_engine
from config import get_nas_mount

NAS = get_nas_mount()


def discover_batches():
    param_dir = os.path.join(NAS, "parameter")
    if not os.path.isdir(param_dir):
        print("Parameter directory not found: {}".format(param_dir))
        return []

    batches = []
    for entry in sorted(os.listdir(param_dir)):
        entry_path = os.path.join(param_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        m = re.match(r"(P\d+)-\d+-\d+", entry)
        if not m:
            continue
        batch_prefix = m.group(1)

        date = None
        for f in os.listdir(entry_path):
            xm = re.match(r"{}-(\d{{8}})\.xlsx".format(batch_prefix), f)
            if xm:
                date = xm.group(1)
                break
        if not date:
            continue

        raw_dir = None
        raw_zip = None
        for f in os.listdir(entry_path):
            full = os.path.join(entry_path, f)
            if os.path.isdir(full) and "铁电" in f:
                raw_dir = full
            elif f.endswith(".zip") and "铁电" in f:
                raw_zip = full

        if raw_dir or raw_zip:
            batches.append({
                "batch_prefix": batch_prefix,
                "date": date,
                "raw_dir": raw_dir,
                "raw_zip": raw_zip,
            })
    return batches


def scan_raw_files(batch):
    files = []
    pattern = re.compile(r"(\d+)#[（(](\d+)-(\d+)[）)]\.txt$")

    if batch["raw_dir"]:
        for f in os.listdir(batch["raw_dir"]):
            m = pattern.match(f)
            if m:
                files.append({
                    "sample_num": int(m.group(1)),
                    "position": int(m.group(2)),
                    "seq": int(m.group(3)),
                    "filepath": os.path.join(batch["raw_dir"], f),
                })

    if batch["raw_zip"]:
        try:
            with zipfile.ZipFile(batch["raw_zip"], "r") as z:
                for name in z.namelist():
                    basename = os.path.basename(name)
                    m = pattern.match(basename)
                    if m:
                        files.append({
                            "sample_num": int(m.group(1)),
                            "position": int(m.group(2)),
                            "seq": int(m.group(3)),
                            "filepath": batch["raw_zip"] + "/" + name,
                        })
        except Exception as e:
            print("Error reading zip {}: {}".format(batch["raw_zip"], e))
    return files


def run_sync():
    engine = get_engine()
    batches = discover_batches()
    print("Found {} batches with raw data".format(len(batches)))

    total = 0
    for batch in batches:
        prefix = batch["batch_prefix"]
        date = batch["date"]
        raw_files = scan_raw_files(batch)
        print("  {}-{}: {} raw data files".format(prefix, date, len(raw_files)))

        with engine.begin() as conn:
            for rf in raw_files:
                sample_id = "{}-{}-{:02d}".format(prefix, date, rf["sample_num"])

                exists = conn.execute(
                    text("SELECT 1 FROM samples WHERE sample_id = :sid"),
                    {"sid": sample_id}
                ).fetchone()

                if not exists:
                    print("    Skip {}: sample {} not found".format(rf["filepath"], sample_id))
                    continue

                rel_path = os.path.relpath(rf["filepath"], NAS) if rf["filepath"].startswith(NAS) else rf["filepath"]

                from plotter import extract_metrics
                metrics = extract_metrics(rf["filepath"])

                try:
                    conn.execute(text("""
                        INSERT INTO char_electrical (sample_id, raw_data_path, test_type,
                            remnant_polarization_pr, coercive_field_ec)
                        VALUES (:sid, :path, 'PE_Loop', :pr, :ec)
                        ON CONFLICT (sample_id, raw_data_path) DO NOTHING
                    """), {
                        "sid": sample_id,
                        "path": rel_path,
                        "pr": metrics["pr"],
                        "ec": metrics.get("ec_pos"),
                    })
                    total += 1
                except Exception as e:
                    print("    Error inserting {}: {}".format(sample_id, e))

    print("Sync complete. {} records added.".format(total))
    return total


if __name__ == "__main__":
    run_sync()
