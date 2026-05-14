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
