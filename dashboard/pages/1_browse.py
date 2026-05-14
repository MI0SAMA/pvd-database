import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import numpy as np
from db import load_table, get_all_tables, update_row, get_engine
from sqlalchemy import text
from config import get_nas_mount
from plotter import plot_pe_loop, plot_pe_loops_multi

st.set_page_config(page_title="数据浏览", layout="wide")

NAS = get_nas_mount()

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

with st.sidebar:
    st.title("权限控制")
    if not st.session_state.is_admin:
        pwd = st.text_input("管理员密码", type="password")
        if st.button("登录"):
            if pwd == st.session_state.get("admin_pwd", ""):
                st.session_state.is_admin = True
                st.rerun()
            else:
                st.error("密码错误")
    else:
        st.success("已进入编辑模式")
        if st.button("退出登录"):
            st.session_state.is_admin = False
            st.rerun()
    st.divider()
    if st.button("刷新数据库缓存"):
        st.cache_data.clear()
        st.rerun()

tables = get_all_tables()
st.title("实验数据查询中心")
target_table = st.selectbox("选择要查看的表格", tables)

if not target_table:
    st.stop()

df = load_table(target_table)

# ====== Admin edit mode ======
if st.session_state.is_admin:
    st.subheader("编辑模式: {}".format(target_table))
    editor_key = "editor_{}".format(target_table)
    edited_df = st.data_editor(
        df, use_container_width=True, num_rows="fixed", key=editor_key,
        column_config={"sample_id": st.column_config.TextColumn("sample_id", disabled=True)}
    )
    if st.button("提交修改到数据库"):
        state = st.session_state[editor_key]
        edited_rows = state.get("edited_rows", {})
        if not edited_rows:
            st.info("没有数据变动")
        else:
            try:
                for row_idx, updated_values in edited_rows.items():
                    pk_val = df.iloc[row_idx]["sample_id"]
                    update_row(target_table, pk_val, updated_values)
                st.success("{} 的 {} 条记录已更新".format(target_table, len(edited_rows)))
                st.rerun()
            except Exception as e:
                st.error("更新失败: {}".format(e))
else:
    st.subheader("查看模式: {}".format(target_table))
    st.dataframe(df, use_container_width=True)
    st.info("若要修改表格，请在左侧输入管理员密码。")

# ====== PE Loop Gallery ======
if target_table == "char_electrical":
    st.divider()
    st.header("PE 电滞回线画廊")

    if "sample_id" not in df.columns or "raw_data_path" not in df.columns:
        st.error("表中缺少必要列")
        st.stop()

    # Filter to PE_Loop only and drop NaN paths
    loop_df = df[df["raw_data_path"].notna()].copy()
    if "test_type" in loop_df.columns:
        loop_df = loop_df[loop_df["test_type"] == "PE_Loop"]

    if loop_df.empty:
        st.warning("暂无 PE Loop 数据")
        st.stop()

    # Get unique samples with their aggregate metrics
    engine = get_engine()
    with engine.begin() as conn:
        agg_df = pd.read_sql(text("""
            SELECT sample_id,
                   count(*) as curve_count,
                   round(avg(remnant_polarization_pr)::numeric, 4) as avg_pr,
                   round(avg(coercive_field_ec)::numeric, 4) as avg_ec,
                   round(avg(pmax)::numeric, 2) as avg_pmax,
                   round(avg(v_max)::numeric, 1) as avg_vmax,
                   min(raw_data_path) as first_path
            FROM char_electrical
            WHERE test_type = 'PE_Loop' AND raw_data_path IS NOT NULL
            GROUP BY sample_id
            ORDER BY sample_id
        """), conn)

    st.markdown("共 **{}** 个样品，**{}** 条测试曲线".format(len(agg_df), len(loop_df)))

    # ---- View mode selector ----
    view_mode = st.radio(
        "查看模式",
        ["样品概览（每样品一条代表曲线）", "单样品详细（查看全部曲线）", "多样品对比"],
        horizontal=True
    )

    if view_mode == "样品概览（每样品一条代表曲线）":
        # Show one representative curve per sample, with metrics
        cols = st.columns(3)
        for idx, (_, row) in enumerate(agg_df.iterrows()):
            fp = os.path.join(NAS, str(row["first_path"]))
            with cols[idx % 3]:
                try:
                    fig = plot_pe_loop(fp, str(row["sample_id"]))
                    st.pyplot(fig)
                except Exception:
                    st.warning("无法读取: {}".format(row["sample_id"]))
                st.caption("Pr={}  Ec={}  Pmax={}  Vmax={}V  ({} curves)".format(
                    row["avg_pr"], row["avg_ec"], row["avg_pmax"],
                    row["avg_vmax"], row["curve_count"]))

    elif view_mode == "单样品详细（查看全部曲线）":
        sample_list = sorted(agg_df["sample_id"].tolist())
        selected = st.selectbox("选择样品", sample_list)

        sample_data = loop_df[loop_df["sample_id"] == selected]
        st.markdown("**{}** — {} 条曲线".format(selected, len(sample_data)))

        # Show metrics summary
        sub = sample_data.iloc[0]
        with engine.begin() as conn:
            stats = conn.execute(text("""
                SELECT round(avg(remnant_polarization_pr)::numeric, 4) as pr,
                       round(avg(coercive_field_ec)::numeric, 4) as ec,
                       round(avg(pmax)::numeric, 2) as pmax,
                       round(avg(v_max)::numeric, 1) as vmax
                FROM char_electrical WHERE sample_id = :sid AND test_type = 'PE_Loop'
            """), {"sid": selected}).fetchone()

        cols_metric = st.columns(4)
        cols_metric[0].metric("Avg Pr", stats[0])
        cols_metric[1].metric("Avg Ec", stats[1])
        cols_metric[2].metric("Pmax", stats[2])
        cols_metric[3].metric("Vmax", "{}V".format(stats[3]))

        # Show all curves
        cols = st.columns(3)
        for idx, (_, srow) in enumerate(sample_data.iterrows()):
            fp = os.path.join(NAS, str(srow["raw_data_path"]))
            with cols[idx % 3]:
                try:
                    label = os.path.basename(str(srow["raw_data_path"]))
                    fig = plot_pe_loop(fp, label[:30])
                    st.pyplot(fig)
                except Exception:
                    st.warning("无法读取")

    else:  # 多样品对比
        compare_samples = st.multiselect("选择要对比的样品 (2-6个)", sorted(agg_df["sample_id"].tolist()), max_selections=6)

        if len(compare_samples) >= 2:
            # Get first curve from each sample
            paths = []
            labels = []
            for sid in compare_samples:
                first = loop_df[loop_df["sample_id"] == sid].iloc[0]
                paths.append(os.path.join(NAS, str(first["raw_data_path"])))
                labels.append(sid)

            try:
                fig = plot_pe_loops_multi(paths, labels)
                st.pyplot(fig)
            except Exception as e:
                st.error("绘图失败: {}".format(e))

            # Metrics comparison table
            st.subheader("指标对比")
            comp_data = agg_df[agg_df["sample_id"].isin(compare_samples)][
                ["sample_id", "curve_count", "avg_pr", "avg_ec", "avg_pmax", "avg_vmax"]
            ]
            st.dataframe(comp_data, use_container_width=True, hide_index=True)
        else:
            st.info("请选择至少 2 个样品进行对比")
