import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
from db import get_engine
from import_utils import (
    parse_batch_from_filename, extract_params, import_row, clean_num
)

st.set_page_config(page_title="数据导入", layout="wide")

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

with st.sidebar:
    st.title("权限控制")
    if not st.session_state.is_admin:
        pwd = st.text_input("管理员密码", type="password", key="import_pwd")
        if st.button("登录", key="import_login"):
            if pwd == st.session_state.get("admin_pwd", ""):
                st.session_state.is_admin = True
                st.rerun()
            else:
                st.error("密码错误")
    else:
        st.success("已进入管理员模式")
        if st.button("退出登录"):
            st.session_state.is_admin = False
            st.rerun()


st.title("实验数据导入")

if not st.session_state.is_admin:
    st.warning("请在左侧输入管理员密码后使用此功能。")
    st.stop()

st.markdown("上传 PVD 工艺记录 Excel，系统自动识别批次前缀和日期。支持 P1-P5 不同表头变体。")

uploaded_file = st.file_uploader("选择 Excel 文件", type=["xlsx", "csv"])

if uploaded_file:
    batch_prefix, batch_date = parse_batch_from_filename(uploaded_file.name)

    if not batch_prefix or not batch_date:
        st.error("无法从文件名 '{}' 解析批次信息。请使用格式: P1-20260317.xlsx".format(uploaded_file.name))
        st.stop()

    st.info("识别批次: **{}-{}**, 样品编号示例: `{}-{}-01`".format(
        batch_prefix, batch_date, batch_prefix, batch_date))

    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
    except Exception as e:
        st.error("读取文件失败: {}".format(e))
        st.stop()

    st.write("数据预览 (共 {} 行):".format(len(df)))
    st.dataframe(df.head(), use_container_width=True)

    if st.button("开始入库 / 更新", use_container_width=True, type="primary"):
        engine = get_engine()
        count = 0
        skipped = 0
        with st.status("正在解析并同步数据库...", expanded=True) as status:
            with engine.begin() as conn:
                for _, row in df.iterrows():
                    raw_id = str(row["样品编号"]).replace("#", "").strip()
                    if not raw_id.isdigit():
                        skipped += 1
                        continue
                    sid = "{}-{}-{}".format(batch_prefix, batch_date, raw_id.zfill(2))
                    params, cat_values = extract_params(row, df)
                    import_row(conn, sid, params, cat_values)
                    count += 1

            msg = "成功导入/更新 {} 条数据".format(count)
            if skipped:
                msg += "，跳过 {} 行（无效编号）".format(skipped)
            status.update(label="✅ " + msg, state="complete", expanded=False)
            st.success("任务完成！共有 {} 个样品的工艺参数已入库。".format(count))
            st.balloons()
