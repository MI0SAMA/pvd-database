import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
import pandas as pd
import re, os
from sqlalchemy import text
from db import get_engine

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


def clean_num(val):
    if pd.isna(val) or str(val).strip() in ["/", "", "nan", "None"]:
        return None
    s = str(val).replace(" ", "").upper()
    match = re.search(r"[-+]?\d*\.?\d+(?:E[-+]?\d+)?", s)
    if match:
        try:
            return float(match.group(0))
        except (ValueError, TypeError):
            return None
    return None


def parse_batch_from_filename(filename):
    match = re.match(r"(P\d+)-(\d{8})\.xlsx?", filename)
    if match:
        return match.group(1), match.group(2)
    return None, None


def process_and_import(df, batch_prefix, batch_date):
    engine = get_engine()
    count = 0
    skipped = 0
    with engine.begin() as conn:
        for _, row in df.iterrows():
            raw_id = str(row["样品编号"]).replace("#", "").strip()
            if not raw_id.isdigit():
                skipped += 1
                continue
            sid = f"{batch_prefix}-{batch_date}-{raw_id.zfill(2)}"

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
                "sid": sid, "sub_t": row.get("衬底类型"),
                "sub_i": row.get("衬底信息（如N/P型Si，掺杂浓度等）", row.get("衬底信息（如N/P型Si，掺杂浓度等）")),
                "sam_t": row.get("样品类型"), "tem": row.get("顶电极材料"),
                "bem": row.get("底电极材料"),
                "temm": row.get("顶电极制备方式（如光刻/硬掩膜）", row.get("顶电极制备方式（如光刻/硬掩膜）")),
                "tag": row.get("归属（Pilot/Medium/Stable-A/B/C）"),
            })

            base_pa = clean_num(row.get("本底真空度")) * 100 if clean_num(row.get("本底真空度")) else None
            work_pa = clean_num(row.get("工作气压")) * 100 if clean_num(row.get("工作气压")) else None
            duration_sec = clean_num(row.get("总沉积时长（min）")) * 60 if clean_num(row.get("总沉积时长（min）")) else None

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
                    al_power_w = EXCLUDED.al_power_w,
                    sc_power_w = EXCLUDED.sc_power_w,
                    n2_flow_sccm = EXCLUDED.n2_flow_sccm,
                    ar_flow_sccm = EXCLUDED.ar_flow_sccm,
                    substrate_temp_set = EXCLUDED.substrate_temp_set,
                    total_duration_sec = EXCLUDED.total_duration_sec,
                    base_vacuum_pa = EXCLUDED.base_vacuum_pa,
                    working_pressure_pa = EXCLUDED.working_pressure_pa,
                    anomalies = EXCLUDED.anomalies,
                    remarks = EXCLUDED.remarks
            """), {
                "sid": sid,
                "t_th": clean_num(row.get("顶电极厚度(nm)")),
                "f_th": clean_num(row.get("膜层厚度(nm)")),
                "b_th": clean_num(row.get("底电极厚度(nm)")),
                "al": clean_num(row.get("Al(W)")), "sc": clean_num(row.get("Sc(W)")),
                "n2": clean_num(row.get("N2(sccm)")), "ar": clean_num(row.get("Ar2(sccm)")),
                "temp": clean_num(row.get("制备温度")), "bias": clean_num(row.get("基底偏压")),
                "dist": clean_num(row.get("靶截距")), "ang": clean_num(row.get("溅射角度（若有）")),
                "rot": clean_num(row.get("基底转速")), "pre": clean_num(row.get("预溅射时间（min）")),
                "dur": duration_sec, "base": base_pa, "work": work_pa,
                "volt": clean_num(row.get("电压")), "curr": clean_num(row.get("电流")),
                "freq": clean_num(row.get("脉冲频率")),
                "duty": clean_num(row.get("占空比（电信号相关，若有请提供）")),
                "model": row.get("设备型号"), "rem": row.get("备注（重点需要做哪些测试）"),
                "ano": row.get("异常记录")
            })
            count += 1
    return count, skipped


st.title("实验数据导入")

if not st.session_state.is_admin:
    st.warning("请在左侧输入管理员密码后使用此功能。")
    st.stop()

st.markdown("上传 PVD 工艺记录 Excel，系统自动识别批次前缀和日期。")

uploaded_file = st.file_uploader("选择 Excel 文件", type=["xlsx", "csv"])

if uploaded_file:
    batch_prefix, batch_date = parse_batch_from_filename(uploaded_file.name)

    if not batch_prefix or not batch_date:
        st.error(f"无法从文件名 '{uploaded_file.name}' 解析批次信息。请使用格式: P1-20260317.xlsx")
        st.stop()

    st.info(f"识别批次: **{batch_prefix}-{batch_date}**, 样品编号示例: `{batch_prefix}-{batch_date}-01`")

    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"读取文件失败: {e}")
        st.stop()

    st.write(f"数据预览 (共 {len(df)} 行):")
    st.dataframe(df.head(), use_container_width=True)

    if st.button("开始入库 / 更新", use_container_width=True, type="primary"):
        with st.status("正在解析并同步数据库...", expanded=True) as status:
            try:
                count, skipped = process_and_import(df, batch_prefix, batch_date)
                msg = f"成功导入/更新 {count} 条数据"
                if skipped:
                    msg += f"，跳过 {skipped} 行（无效编号）"
                status.update(label=f"✅ {msg}", state="complete", expanded=False)
                st.success(f"任务完成！共有 {count} 个样品的工艺参数已入库。")
                st.balloons()
            except Exception as e:
                status.update(label="❌ 导入中断", state="error")
                st.error(f"错误详情: {e}")
