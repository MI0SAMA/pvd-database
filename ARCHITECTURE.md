# PVD 工艺参数数据库 — 架构文档

## 概述

AlScN（氮化铝钪）PVD 薄膜沉积实验数据库系统，管理工艺参数、电学测试原始数据及 PE 铁电回线分析。

- **服务器**: 10.10.10.142 (monitor/zabbix)
- **路径**: `/home/pvd_db`
- **Dashboard**: http://10.10.10.142:8501
- **图片服务**: http://10.10.10.142:8081
- **GitHub**: https://github.com/MI0SAMA/pvd-database

---

## 目录结构

```
/home/pvd_db/
├── .env                          # 环境变量（密码等敏感配置，不入 git）
├── .env.example                  # 配置模板
├── .gitignore                    # Git 排除规则
├── docker-compose.yml            # Docker 服务编排
├── ARCHITECTURE.md               # 本文档
├── backup.sh                     # 自动备份脚本（cron: 每日 03:00）
│
├── dashboard/                    # Streamlit Web 应用 (挂载到容器 /app)
│   ├── Dockerfile
│   ├── requirements.txt          # Python 依赖
│   ├── main.py                   # 首页：数据库总览 + 导航
│   ├── config.py                 # 配置中心 (从环境变量读取)
│   ├── db.py                     # 数据库操作封装
│   ├── plotter.py                # PE Loop 实时绘图 (调用 processor)
│   ├── batch_import.py           # 批量导入脚本 (Excel + 电学)
│   ├── sync.py                   # NAS 原始数据同步
│   └── pages/
│       ├── 1_browse.py           # 数据浏览 + 编辑 + PE Loop 画廊（3 模式）
│       ├── 2_import.py           # Excel 单文件上传导入
│       ├── 3_analysis.py         # 工艺参数分布分析
│       └── 4_electrical.py       # 电学性能分析 + 异常检测
│
├── processor/                    # 原始数据处理模块 (挂载到容器 /app/processor)
│   ├── parse.py                  # Radiant 铁电测试仪 .txt 解析器
│   ├── metrics.py                # PE Loop 指标提取 (Pr/Ec+/Ec−/Pmax/Ps/LoopArea)
│   └── run.py                    # 主处理脚本 (扫描→解析→入库)
│
├── nas_data/                     # NAS 远程挂载源数据 (只读，不可修改)
│   ├── parameter/                # 工艺参数 Excel + 铁电原始数据
│   │   ├── P1-1-20/              # 批次1: 样品1-20#
│   │   ├── P2-21-40/             # 批次2: 样品21-40#
│   │   ├── P3-41-60/             # 批次3: 样品41-60#
│   │   ├── P4-61-80/             # 批次4: 样品61-80#
│   │   └── P5-81-129/            # 批次5: 样品81-129#
│   ├── characterization/         # 表征数据目录 (预留)
│   └── #recycle/                 # 回收站
│
├── pgdata/                       # PostgreSQL 持久化数据卷 (不入 git)
├── backup/                       # 备份目录
│   ├── pvd_db_latest.sql         # 数据库 dump
│   ├── code_latest.tar.gz        # 代码快照
│   └── nas_data/                 # NAS 数据 rsync 副本
└── migrations/                   # (预留) 数据库迁移脚本
```

---

## 数据流

```
┌─────────────────┐
│  实验员填写      │
│  PVD 工艺 Excel  │
│  P1~P5 .xlsx    │
└────────┬────────┘
         │ 2_import.py (单文件) 或 batch_import.py (批量)
         │ 自动识别批次前缀 → UPSERT
         ▼
┌─────────────────┐     ┌─────────────────┐
│  samples        │────▶│  pvd_deposition │
│  样品主表 129条  │     │  工艺参数 129条  │
└─────────────────┘     └─────────────────┘

┌─────────────────┐
│  Radiant 铁电   │
│  测试仪 .txt    │
│  (含 zip 打包)  │
└────────┬────────┘
         │ processor/run.py
         │ parse.py 解析 (列2=DriveV, 列3=Polarization)
         │ metrics.py 提取 Pr/Ec+/Ec−/Pmax/Ps/LoopArea
         ▼
┌──────────────────────┐
│  char_electrical     │
│  电学测试 580条,89样品│
└──────┬───────────────┘
       │ plotter.py 实时绘图 (processor/parse.py)
       ▼
┌──────────────────────┐
│  Dashboard :8501     │
│  数据浏览 / 工艺分析  │
│  电学分析 / 异常检测  │
└──────────────────────┘
```

---

## 数据库 Schema

### samples — 样品主表 (PK: sample_id, 129 条)

| 列 | 类型 | 说明 |
|----|------|------|
| sample_id | VARCHAR(50) | `P{批次}-{日期}-{编号2位}` |
| substrate_type | VARCHAR(100) | 衬底类型 |
| substrate_info | TEXT | 掺杂信息 |
| sample_type | VARCHAR(100) | 薄膜/器件 |
| top/bottom_electrode_material | VARCHAR(50) | 电极材料 |
| top_electrode_method | VARCHAR(100) | 掩膜/光刻 |
| batch_tag | VARCHAR(20) | Pilot/Medium/Stable-A/B/C |
| storage_location | VARCHAR(100) | 存储位置 |
| collector_name | VARCHAR(50) | 负责人 |

### pvd_deposition — 工艺参数 (PK: pvd_id, UK: sample_id, 129 条)

21 个数值参数列，其中 **10 列完全有效**，5 列部分有效，**6 列全 NULL**：

| 状态 | 列 | 说明 |
|------|----|------|
| ✅ 有效 | film_target_thickness_nm | 膜层厚度 |
| ✅ 有效 | n2_flow_sccm, ar_flow_sccm | 气体流量 |
| ✅ 有效 | target_dist_mm | 靶距 |
| ✅ 有效 | rotation_speed_rpm | 基底转速 |
| ✅ 有效 | total_duration_sec | 沉积时长 |
| ✅ 有效 | base_vacuum_pa, working_pressure_pa | 真空度 |
| ✅ 有效 | pulse_freq_khz | 脉冲频率 |
| ✅ 有效 | pre_sputtering_min | 预溅射时间 |
| ⚠️ 部分 | al_power_w, sc_power_w | 靶功率（部分未用该靶） |
| ⚠️ 部分 | top/bottom_elec_target_thickness_nm | 电极厚度（薄膜样品无） |
| ⚠️ 部分 | substrate_temp_set | 衬底温度 |
| ❌ 全空 | bias_voltage_v, sputter_angle_deg | 未记录 |
| ❌ 全空 | total_power_w, discharge_voltage_v | 未记录 |
| ❌ 全空 | discharge_current_a, duty_cycle_pct | 未记录 |

### char_electrical — 电学测试 (PK: elec_id, UK: sample_id+raw_data_path, 580 条)

| 类别 | 列 | 说明 |
|------|----|------|
| 标识 | sample_id | FK → samples |
| 标识 | raw_data_path | 原始数据相对路径 |
| 标识 | test_type | PE_Loop |
| **指标** | remnant_polarization_pr | Pr (μC/cm²) |
| **指标** | coercive_field_ec | Ec (V) |
| **指标** | ec_pos, ec_neg | 正/负矫顽场 |
| **指标** | pr_pos, pr_neg | 正/负剩余极化 |
| **指标** | pmax, pmin | 极化极值 |
| **指标** | ps_pos, ps_neg | 饱和极化 |
| **指标** | loop_area | 回线面积 |
| **指标** | v_max, v_min | 实测电压范围 |
| **条件** | test_voltage, period_ms | 测试电压、周期 |
| **条件** | profile, task_name | 波形、任务名 |
| **条件** | sample_area_cm2 | 样品面积 |

---

## 样品命名规则

```
{P批次}-{日期}-{编号2位}

示例:
  P1-20260317-01   → 批次1, 2026年3月17日, 1号样品
  P5-20260424-129  → 批次5, 2026年4月24日, 129号样品
```

- 批次前缀从 Excel 文件名自动解析: `P1-20260317.xlsx` → `P1-20260317`
- 原始数据文件: `{编号}#（{点位}-{序号}）.txt` → 同一样品多点位多电压测量

### 批次数分布

| 批次 | 样品数 | 编号范围 | 有电学数据 |
|------|--------|---------|-----------|
| P1 | 20 | 01-20 | 11 |
| P2 | 20 | 21-40 | 16 |
| P3 | 20 | 41-60 | 14 |
| P4 | 20 | 61-80 | 17 |
| P5 | 49 | 81-129 | 31 |
| **合计** | **129** | | **89** |

---

## Processor 模块

### parse.py — 解析 Radiant 原始数据

```
Radiant .txt 文件格式:
┌─────────────────────────────────────┐
│ Header: 软件版本、测试仪信息          │
│ Sample Info: 面积、厚度              │
│ Hysteresis Info: Volts, Period,     │
│   Profile, Task Name                │
├─────────────────────────────────────┤
│ Point │ Time │ DriveV │ Polzn │ ... │  ← 8 列 tab 分隔
│   1   │ 0.0  │ 0.0626 │ -.035 │ ... │
│  ...  │ ...  │  ...   │  ...  │ ... │
│ 2001  │10.0  │ -0.015 │  0.72 │ ... │  ← 2001 点/文件
└─────────────────────────────────────┘

列 2 = Drive Voltage → X 轴 (PE Loop)
列 3 = Measured Polarization → Y 轴 (PE Loop)
```

**重要**: v1 曾误用列 1 (Time) 作为 X 轴，v2 已修正。支持本地 .txt 和 zip 包内文件。

### metrics.py — 指标提取

从 2001 点自动计算：Pr (V≈0), Ec+/Ec− (P=0 插值), Pmax/Pmin, Ps (Vmax 处), Loop Area (Shoelace)。

### run.py — 批量处理

扫描全部 5 批次 590 个原始文件 → 逐文件独立事务 UPSERT → 580 条成功 0 错误。

---

## Docker 服务

| 容器 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| pvd_postgres | postgres:15 | 5433→5432 | PostgreSQL |
| pvd_dashboard | python:3.10-slim | 8501→8501 | Streamlit |
| pvd_image_server | nginx:alpine | 8081→80 | NAS 静态文件 |

### 常用命令

```bash
# 重建
cd /home/pvd_db && docker compose up -d --build

# 批量导入 Excel + 电学
docker exec pvd_dashboard python batch_import.py

# 单独处理电学数据
docker exec pvd_dashboard python processor/run.py

# 查看日志
docker logs pvd_dashboard

# 手动备份
bash /home/pvd_db/backup.sh

# 推送代码
cd /home/pvd_db && git add -A && git commit -m "update" && git push
```

---

## Dashboard 功能

| 页面 | 路由 | 功能 |
|------|------|------|
| **首页** | `/` | 数据库总览：样品数、批次分布、导航入口、更新日期 |
| **数据浏览** | `1_browse` | 任意表查看/编辑，PE Loop 画廊（概览/详细/对比三模式） |
| **数据导入** | `2_import` | Excel 上传 → 自动识别批次 → 入库 |
| **工艺分析** | `3_analysis` | 单变量分布（直方图+KDE+统计）、批次箱线图对比、21 参数全景表 |
| **电学分析** | `4_electrical` | 异常检测（5 规则可调阈值）、样品检索+点击显图、指标分布、工艺-性能关联、电压依赖性 |

### 电学异常检测规则

| 规则 | 默认阈值 | 检测目标 |
|------|---------|---------|
| Pmax 过高 | > 200 μC/cm² | 漏电器件 |
| Pr/Pmax 比值异常 | > 0.95 | 矩形回线 (积分漏电) |
| Ec 过小 | < 0.1V | 无矫顽场 (非铁电) |
| 回线不饱满 | < 0.5 | 斜窄线 (非饱满椭圆) |
| Ec 不对称 | > 10V | 正负矫顽场差异大 |

Fullness = max(|ps_pos|, |ps_neg|) / |pmax|，正常 ≈ 1.0。

---

## 备份

| 项目 | 方式 | 位置 | 频率 |
|------|------|------|------|
| PostgreSQL | `pg_dump` | `backup/pvd_db_latest.sql` (~250KB) | 每日 03:00 |
| NAS 参数 | `rsync` 从远程挂载拉取 | `backup/nas_data/parameter/` | 每日 03:00 |
| 代码 | `tar.gz` | `backup/code_latest.tar.gz` (~31KB) | 每日 03:00 |
| GitHub | `git push` | github.com/MI0SAMA/pvd-database | 手动 |

- 脚本: `/home/pvd_db/backup.sh`
- Cron: `0 3 * * * bash /home/pvd_db/backup.sh`
- `.gitignore` 排除 `.env`, `pgdata/`, `backup/`, `nas_data/`, `__pycache__/`

---

## 关键设计决策

1. **原始数据优先**: PE Loop 从 Radiant .txt 实时绘制，不依赖手动截图
2. **列映射修正**: v1 误用 Time 列 → v2 修正为 Drive Voltage
3. **独立事务**: 每个原始文件单独事务，避免级联回滚
4. **配置外部化**: 密码/路径通过环境变量注入，`.env` 不入 git
5. **NAS 只读**: nas_data 严格只读挂载，永不对其写入
6. **数据清理**: 迁移遗留的 P1(21-40) 和 P2(41-60) 已删除，DB 与 Excel 一一对应
7. **无效列过滤**: 6 列全 NULL 参数已从分析页移除
