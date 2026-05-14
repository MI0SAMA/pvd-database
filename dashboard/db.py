import pandas as pd
from sqlalchemy import create_engine, text
from config import get_db_url


def get_engine():
    return create_engine(get_db_url())


def load_table(table_name):
    engine = get_engine()
    return pd.read_sql(f"SELECT * FROM {table_name}", engine)


def get_all_tables():
    engine = get_engine()
    df = pd.read_sql(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'",
        engine
    )
    tables = df["table_name"].tolist()
    return [t for t in tables if t and t != "post_annealing"]


def update_row(table, sample_id, changes):
    engine = get_engine()
    with engine.begin() as conn:
        for col_name, new_val in changes.items():
            sql = text(
                "UPDATE {} SET \"{}\" = :val WHERE sample_id = :pk".format(table, col_name)
            )
            conn.execute(sql, {"val": new_val, "pk": sample_id})


def execute_sql(sql, params=None):
    engine = get_engine()
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {})

def get_valid_numeric_params(table='pvd_deposition', exclude_cols=None):
    """Return list of numeric columns in a table that have at least one non-null value."""
    if exclude_cols is None:
        exclude_cols = ['pvd_id', 'sample_id']
    conn = get_engine().connect()
    cols = conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = '{}' "
        "AND data_type IN ('double precision', 'integer') ORDER BY ordinal_position".format(table)
    )).fetchall()
    valid = []
    for (col,) in cols:
        if col in exclude_cols:
            continue
        cnt = conn.execute(text(
            'SELECT count(*) FROM {} WHERE "{}" IS NOT NULL'.format(table, col)
        )).fetchone()[0]
        if cnt > 0:
            valid.append(col)
    conn.close()
    return valid
