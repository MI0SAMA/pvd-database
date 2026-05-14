import streamlit as st
from sqlalchemy import text
from config import get_admin_password
from db import get_engine

st.set_page_config(page_title="AlScN PVD 数据库", layout="wide", page_icon="⚡")

admin_password = get_admin_password()

if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
if "admin_pwd" not in st.session_state:
    st.session_state.admin_pwd = admin_password

# ── Sidebar ──
with st.sidebar:
    st.title("AlScN PVD")
    st.markdown("工艺参数与电学数据库")
    st.markdown("---")

    if not st.session_state.is_admin:
        pwd = st.text_input("管理员密码", type="password")
        if st.button("登录", use_container_width=True):
            if pwd == admin_password:
                st.session_state.is_admin = True
                st.session_state.admin_pwd = admin_password
                st.rerun()
            else:
                st.error("密码错误")
    else:
        st.success("已进入编辑模式")
        if st.button("退出登录", use_container_width=True):
            st.session_state.is_admin = False
            st.rerun()

    st.markdown("---")
    if st.button("刷新数据库缓存", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.caption("服务器: 10.10.10.142")
    st.caption("Dashboard v2.2")

# ── Main ──
st.title("AlScN PVD 工艺参数数据库")

# Fetch stats
engine = get_engine()
with engine.begin() as conn:
    n_samples = conn.execute(text("SELECT count(*) FROM samples")).fetchone()[0]
    n_pvd = conn.execute(text("SELECT count(*) FROM pvd_deposition")).fetchone()[0]
    elec_stats = conn.execute(text(
        "SELECT count(*), count(DISTINCT sample_id) FROM char_electrical WHERE test_type='PE_Loop'"
    )).fetchone()
    n_elec = elec_stats[0]
    n_elec_samples = elec_stats[1]
    last_update = conn.execute(text(
        "SELECT to_char(MAX(test_date), 'YYYY-MM-DD') FROM char_electrical WHERE test_type='PE_Loop'"
    )).fetchone()[0] or 'N/A'
    batch_counts = conn.execute(text(
        "SELECT substring(sample_id,1,2) as batch, count(*) FROM samples GROUP BY 1 ORDER BY 1"
    )).fetchall()

    # batch elec counts
    batch_elec = {}
    for batch, _ in batch_counts:
        ec = conn.execute(text(
            "SELECT count(DISTINCT sample_id) FROM char_electrical WHERE sample_id LIKE :p AND test_type='PE_Loop'"
        ), {'p': batch + '%'}).fetchone()[0]
        batch_elec[batch] = ec

# Stats row
st.markdown("### 数据库总览")
cols = st.columns(6)
cols[0].metric("样品总数", n_samples)
cols[1].metric("工艺参数", n_pvd, delta="{:.0f}%".format(100 * n_pvd / max(n_samples, 1)) if n_pvd != n_samples else "全覆盖")
cols[2].metric("电学曲线", n_elec)
cols[3].metric("电学样品", n_elec_samples, delta="{:.0f}%".format(100 * n_elec_samples / max(n_samples, 1)))
cols[4].metric("批次", len(batch_counts))
cols[5].metric("更新日期", last_update)

# Batch breakdown
st.markdown("#### 批次分布")
batch_cols = st.columns(len(batch_counts))
for i, (batch, cnt) in enumerate(batch_counts):
    elec_cnt = batch_elec.get(batch, 0)
    batch_cols[i].metric(batch, "{} 样品".format(cnt), delta="{} 有电学".format(elec_cnt) if elec_cnt else None)

st.divider()

# Navigation cards
st.markdown("### 功能导航")

nav_cols = st.columns(4)

with nav_cols[0]:
    st.page_link("pages/1_browse.py", label="数据浏览与编辑", icon="📋")
    st.caption("查看、编辑所有数据表，查看 PE Loop 曲线画廊")

with nav_cols[1]:
    st.page_link("pages/2_import.py", label="工艺数据导入", icon="📥")
    st.caption("上传 Excel 工艺记录，自动识别批次并入库")

with nav_cols[2]:
    st.page_link("pages/3_analysis.py", label="工艺参数分析", icon="📊")
    st.caption("单变量分布、批次对比、21 个参数全景统计")

with nav_cols[3]:
    st.page_link("pages/4_electrical.py", label="电学性能分析", icon="⚡")
    st.caption("异常检测、工艺-性能关联、电压依赖性")

st.divider()
st.caption("提示：点击上方链接进入对应功能页面，或在左侧边栏使用页面导航。管理员登录后可编辑数据库。")
