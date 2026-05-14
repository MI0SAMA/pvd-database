# PVD 工艺参数数据库 — 架构文档

## 概述

AlScN（氮化铝钪）PVD 薄膜沉积实验数据库系统，管理工艺参数、电学测试原始数据及 PE 铁电回线分析。

- **服务器**: 10.10.10.142 (monitor/zabbix)
- **路径**: `/home/pvd_db`
- **Dashboard**: http://10.10.10.142:8501
- **图片服务**: http://10.10.10.142:8081

---

## 目录结构

```
/home/pvd_db/
├── .env                          # 环境变量（密码等敏感配置）
├── .env.example                  # 配置模板
├── docker-compose.yml            # 服务编排
├── ARCHITECTURE.md               # 本文档
│
├── dashboard/                    # Streamlit Web 应用 (挂载到容器 /app)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                   # 入口：页面配置 + 侧边栏登录
│   ├── config.py                 # 配置中心 (从环境变量读取)
│   ├── db.py                     # 数据库操作封装
│   ├── plotter.py                # PE Loop 实时绘图 (调用 processor)
│   ├── batch_import.py           # 批量导入脚本 (Excel + 电学)
│   └── pages/
│       ├── 1_browse.py           # 数据浏览 + 编辑 + PE Loop 画廊
│       └── 2_import.py           # Excel 单文件上传导入
│
├── processor/                    # 原始数据处理模块
│   ├── parse.py                  # Radiant 铁电测试仪 .txt 解析器
│   ├── metrics.py                # PE Loop 指标提取 (Pr/Ec/Pmax...)
│   └── run.py                    # 主处理脚本 (扫描→解析→入库)
│
├── nas_data/                     # NAS 挂载源数据 (只读，不可修改)
│   ├── parameter/                # 工艺参数 Excel + 铁电原始数据
│   │   ├── P1-1-20/              # 批次1: 样品1-20#
│   │   ├── P2-21-40/             # 批次2: 样品21-40#
│   │   ├── P3-41-60/             # 批次3: 样品41-60#
│   │   ├── P4-61-80/             # 批次4: 样品61-80#
│   │   └── P5-81-129/            # 批次5: 样品81-129#
│   ├── characterization/         # 表征数据目录 (预留)
│   └── #recycle/                 # 回收站
│
├── pgdata/                       # PostgreSQL 持久化数据卷
├── backup/                       # 旧代码备份
├── raw_data/                     # (已废弃)
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
         │ 上传到 2_import.py (单文件)
         │ 或 batch_import.py (批量)
         ▼
┌─────────────────┐     ┌─────────────────┐
│  samples        │────▶│  pvd_deposition │
│  样品主表        │     │  工艺参数详情    │
│  169 条记录      │     │  129 条记录      │
└─────────────────┘     └─────────────────┘

┌─────────────────┐
│  Radiant 铁电   │
│  测试仪 .txt    │
│  (含 zip 打包)  │
└────────┬────────┘
         │ processor/run.py 扫描
         │ parse.py 解析 (2001 点/文件)
         │ metrics.py 提取 Pr/Ec/Pmax...
         ▼
┌──────────────────────┐
│  char_electrical     │
│  电学测试结果         │
│  580 条记录, 89 样品  │
└──────┬───────────────┘
       │ plotter.py 实时绘图
       ▼
┌──────────────────────┐
│  Dashboard (8501)    │
│  PE Loop 画廊         │
│  3 种查看模式         │
└──────────────────────┘
```

---

## 数据库 Schema

### samples — 样品主表 (主键: sample_id)

| 列 | 类型 | 说明 |
|----|------|------|
| sample_id | VARCHAR(50) | 主键，格式 `P{批次}-{日期}-{编号}` 如 `P1-20260317-01` |
| substrate_type | VARCHAR(100) | 衬底类型 (Si(100)/Si(111)/Si/SiO₂...) |
| substrate_info | TEXT | 衬底掺杂信息 |
| sample_type | VARCHAR(100) | 样品类型 (薄膜/器件) |
| top_electrode_material | VARCHAR(50) | 顶电极材料 (Mo/W/Al/AI/...) |
| bottom_electrode_material | VARCHAR(50) | 底电极材料 |
| top_electrode_method | VARCHAR(100) | 制备方式 (掩膜/光刻) |
| batch_tag | VARCHAR(20) | 批次分类 (Pilot/Medium/Stable-A/B/C) |
| storage_location | VARCHAR(100) | 存储位置 |
| collector_name | VARCHAR(50) | 负责人 |
| collection_date | DATE | 采集日期 |
| dft_sync_status | BOOLEAN | DFT 同步状态 |

### pvd_deposition — 工艺参数 (主键: pvd_id, 唯一: sample_id)

| 列 | 类型 | 说明 |
|----|------|------|
| film_target_thickness_nm | DOUBLE | 膜层目标厚度 |
| top_elec_target_thickness_nm | DOUBLE | 顶电极厚度 |
| bottom_elec_target_thickness_nm | DOUBLE | 底电极厚度 |
| al_power_w / sc_power_w | DOUBLE | Al/Sc 靶功率 |
| n2_flow_sccm / ar_flow_sccm | DOUBLE | N₂/Ar 流量 |
| substrate_temp_set | DOUBLE | 衬底温度 |
| base_vacuum_pa / working_pressure_pa | DOUBLE | 本底/工作真空度 (Pa) |
| total_duration_sec | INTEGER | 沉积时长 (秒) |
| equipment_model | VARCHAR(100) | 设备型号 (布劳恩 OPTIvap 5s) |
| ... | | 还有靶距、角度、转速、电压、电流、频率、占空比等 |

### char_electrical — 电学测试 (主键: elec_id, 唯一: sample_id + raw_data_path)

| 列 | 类型 | 说明 |
|----|------|------|
| sample_id | VARCHAR(50) | 外键 → samples |
| raw_data_path | VARCHAR(255) | 原始数据文件路径 (相对于 NAS 根目录) |
| test_type | VARCHAR(50) | 测试类型 (PE_Loop) |
| **核心指标** | | |
| remnant_polarization_pr | DOUBLE | 剩余极化 Pr (μC/cm²) |
| coercive_field_ec | DOUBLE | 矫顽场 Ec (V) |
| ec_pos / ec_neg | DOUBLE | 正/负矫顽场 |
| pr_pos / pr_neg | DOUBLE | 正/负剩余极化 |
| pmax / pmin | DOUBLE | 最大/最小极化 |
| ps_pos / ps_neg | DOUBLE | 饱和极化 |
| loop_area | DOUBLE | 回线面积 |
| **测试条件** | | |
| test_voltage | DOUBLE | 测试电压幅值 (V) |
| period_ms | DOUBLE | 测试周期 (ms) |
| profile | VARCHAR(50) | 波形类型 (Standard Bipolar) |
| task_name | VARCHAR(50) | 任务名称 (Hyst-1) |
| sample_area_cm2 | DOUBLE | 样品面积 (cm²) |

---

## 样品命名规则

```
{P批次}-{日期}-{编号2位}

示例:
  P1-20260317-01   → 批次1, 2026年3月17日, 1号样品
  P5-20260424-129  → 批次5, 2026年4月24日, 129号样品
```

- 批次前缀从 Excel 文件名自动解析: `P1-20260317.xlsx` → `P1-20260317`
- 样品编号从 Excel 列 `样品编号` (如 `1#`, `21#`) 自动补零
- 原始数据文件: `{编号}#（{点位}-{序号}）.txt` (如 `5#（1-1）.txt`)

---

## Processor 模块

### parse.py — 解析 Radiant 原始数据

```
Radiant .txt 文件格式:
┌─────────────────────────────────────┐
│ Header: 软件版本、测试仪信息          │
│ Sample Info: 面积、厚度              │
│ Hysteresis Info: 电压、周期、波形    │
├─────────────────────────────────────┤
│ Point │ Time │ Drive V │ Polzn │ ... │  ← 8 列 tab 分隔
│   1   │ 0.0  │ 0.0626  │ -.035 │ ... │
│  ...  │ ...  │  ...    │  ...  │ ... │
│ 2001  │ 10.0 │ -0.015  │ 0.72  │ ... │  ← 2001 点/文件
└─────────────────────────────────────┘

列 2 = Drive Voltage → X 轴 (PE Loop)
列 3 = Measured Polarization → Y 轴 (PE Loop)
```

### metrics.py — 指标提取

从 2001 个数据点自动计算:
- **Pr**: V≈0 附近的平均 |P|
- **Ec+/Ec-**: P=0 交叉点的电压 (线性插值)
- **Pmax/Pmin**: 极化极值
- **Ps**: 最大电压处的饱和极化
- **Loop Area**: Shoelace 公式计算回线面积

### run.py — 批量处理

```
扫描 NAS parameter/ 下所有批次
  → 发现 5 个批次, 590 个原始文件 (.txt + .zip 内)
  → 逐文件解析 + 提取指标 + UPSERT 入库
  → 580 条成功, 0 错误
```

---

## Docker 服务

| 容器 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| pvd_postgres | postgres:15 | 5433→5432 | PostgreSQL 数据库 |
| pvd_dashboard | python:3.10-slim | 8501→8501 | Streamlit Web 应用 |
| pvd_image_server | nginx:alpine | 8081→80 | NAS 文件静态服务 |

### 常用命令

```bash
# 重建并启动
cd /home/pvd_db && docker compose up -d --build

# 重新导入全部数据
docker exec pvd_dashboard python batch_import.py

# 单独处理电学数据
docker exec pvd_dashboard python processor/run.py

# 查看日志
docker logs pvd_dashboard
```

---

## Dashboard 功能

### 1_browse — 数据浏览
- 任意表查看 + 管理员编辑
- **PE Loop 画廊** (char_electrical 表) 三种模式:
  - 样品概览: 每样品一条代表曲线 + 指标卡片
  - 单样品详细: 全部曲线 + 指标仪表盘
  - 多样品对比: 最多 6 条曲线叠加 + 指标对比表

### 2_import — 数据导入
- 上传 Excel → 自动识别批次前缀 → UPSERT 到 samples + pvd_deposition
- 文件名格式: `P1-20260317.xlsx`

---

## 关键设计决策

1. **原始数据优先**: PE Loop 从 Radiant .txt 实时绘制，不依赖手动截图
2. **列映射修正**: 初版误用 Time 列作为 Voltage，v2 修正为正确的 Drive Voltage 列
3. **每个文件独立事务**: 避免单文件解析失败导致整批回滚
4. **配置外部化**: 所有密码/路径从环境变量注入，不硬编码
5. **NAS 只读**: nas_data 严格只读挂载，永不对其写入
