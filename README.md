# COPD LangGraph 智能辅助评估 POC

这是一个慢阻肺病智能诊疗决策支持系统的第 3-4 周 POC Demo。当前目标是跑通内部演示主流程：

```text
导入 20-50 例样例数据
-> 患者列表与检索
-> 患者总览
-> 病程时间轴
-> 触发 LangGraph 智能评估
-> 展示结构化评估结果
-> 生成报告草稿
```

当前仍然是 POC，不处理原始 CT、DICOM、PACS、HIS、EMR，也不输出具体用药或处置建议。

## 当前能力

- 本地 FastAPI + SQLite + Jinja 页面 Demo。
- 支持导入现有 Excel 样例数据：
  - `Patients`
  - `Visits`
  - `Labs`
  - `ModelOutputs`
- 提供 5 个核心页面：
  - 患者列表页
  - 患者总览页
  - 病程时间轴页
  - 智能评估结果页
  - 报告生成页
- 保留 LangGraph 最小节点顺序：
  - `load_patient_data`
  - `data_quality_check`
  - `timeline_analyzer`
  - `assessment_generator`
  - `evidence_builder`
  - `safety_check`
  - `report_generator`
- `key_evidence` 已增强为可追踪结构，包含 `source`、`source_dates`、`source_fields`。

## 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 运行单患者 LangGraph Sample

```bash
python scripts\run_sample.py
```

## 启动 POC Demo

```bash
python scripts\run_poc_server.py
```

启动后访问：

```text
http://127.0.0.1:8000
```

默认导入按钮会读取：

```text
C:\Users\Owner\Desktop\plan\copd_mock_data_v1(1).xlsx
```

## API

- `POST /api/import/patients`
- `GET /api/patients?q=`
- `GET /api/patients/{patient_id}`
- `GET /api/patients/{patient_id}/timeline`
- `POST /api/patients/{patient_id}/assessment`
- `GET /api/assessments/{assessment_id}`
- `POST /api/assessments/{assessment_id}/report`

## 测试

当前环境如果还没有安装 pytest，也可以直接运行：

```bash
python -m unittest discover -s tests -v
```

如果已安装 pytest：

```bash
python -m pytest -q
```

## POC 边界

- CT 只使用报告文本或已提取影像特征。
- mNGS/病原学结果只作为感染相关线索。
- 报告仅为辅助评估草稿，不能替代医生临床判断。
- 当前不做医生复核、报告编辑导出、权限、日志和版本管理；这些留到 MVP 增量阶段。
