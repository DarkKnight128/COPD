# COPD LangGraph 智能辅助评估 POC

这是一个慢阻肺病智能诊疗决策支持系统的 POC/MVP Demo。当前已经从第 3-4 周 POC 主流程，推进到第 7-8 周 MVP 模型层增强：

```text
导入固定模板样例数据
-> 患者列表与检索
-> 风险/评估/随访/导入批次筛选
-> 患者总览
-> 病程时间轴
-> 触发 LangGraph 智能评估
-> 可选调用通义千问 API
-> 展示结构化评估结果
-> 生成报告草稿
```

当前仍然是 POC，不处理原始 CT、DICOM、PACS、HIS、EMR，也不输出具体用药或处置建议。

## 当前能力

- 本地 FastAPI + SQLite + Jinja 页面 Demo。
- 支持固定 Excel 模板导入：
  - `data/copd_patient_import_template.xlsx`
  - `data/copd_patient_import_sample_100.xlsx`
- 支持导入前校验：
  - 必填字段
  - 日期格式
  - 数值范围
  - 重复患者
  - 跨 sheet 患者 ID 关联
- 支持导入日志：
  - 导入批次
  - 成功/失败状态
  - 导入统计
  - 错误和提示明细
- 支持 MVP 模型层增强：
  - 通义千问 API 配置入口
  - 当前状态、表型、风险节点拆分
  - 模型调用日志
  - LangGraph 节点运行日志
  - 模型失败时规则 fallback
- 提供 5 个核心页面：
  - 患者列表页
  - 患者总览页
  - 病程时间轴页
  - 智能评估结果页
  - 报告生成页
- LangGraph 节点顺序：
  - `load_patient_data`
  - `data_quality_check`
  - `timeline_analyzer`
  - `current_status_summarizer`
  - `phenotype_assessor`
  - `risk_assessor`
  - `evidence_builder`
  - `safety_harness_check`
  - `safety_check`
  - `report_generator`
- `key_evidence` 已增强为可追踪结构，包含 `source`、`source_dates`、`source_fields`。

## 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 通义千问配置

项目默认不调用在线模型，`QWEN_ENABLE=false` 时会使用规则占位评估。

如需启用通义千问 API：

1. 复制 `.env.example` 为 `.env`。
2. 在 `.env` 中填写：

```text
DASHSCOPE_API_KEY=你的API Key
QWEN_MODEL_NAME=你的模型名
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_TIMEOUT_SECONDS=30
QWEN_ENABLE=true
```

安全注意：

- `.env` 已在 `.gitignore` 中忽略，不要提交到 GitHub。
- `.env.example` 只能放占位字段，不要填写真实 API Key。
- 系统不会在页面、API 返回或数据库日志中保存 API Key。

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

系统不会自动读取任何默认位置的数据。启动后进入“导入”页面，手动上传固定模板 Excel。

推荐演示数据：

```text
data\copd_patient_import_sample_100.xlsx
```

官方空模板：

```text
data\copd_patient_import_template.xlsx
```

## API

- `POST /api/import/patients`
- `GET /api/imports`
- `GET /api/imports/{batch_id}`
- `GET /api/patients?q=&risk=&assessment_status=&followup_status=&import_batch_id=&review_status=&report_status=`
- `GET /api/patients/{patient_id}`
- `GET /api/patients/{patient_id}/timeline`
- `POST /api/patients/{patient_id}/assessment`
- `GET /api/assessments/{assessment_id}`
- `POST /api/assessments/{assessment_id}/report`
- `GET /api/reports/{report_id}`
- `POST /api/reports/{report_id}/confirm`
- `POST /api/reports/{report_id}/reject`

## 医生复核与报告流程

1. 在患者详情页触发“本地规则评估”或“API 智能评估”。
2. 系统保存评估结果后，会自动生成一份 `待复核` 报告版本。
3. 在评估结果页点击“提交复核”，医生可以保存意见、确认结果或驳回结果。
4. 在报告编辑页修改正文，每次保存都会生成新的报告版本。
5. 已确认报告再次编辑后会回到 `待复核` 状态，避免直接覆盖已确认版本。
6. 在报告导出页点击“打印 / 导出 PDF”，使用浏览器打印生成基础版慢阻肺智能辅助评估报告。

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
- 当前已实现导入日志、模型调用日志、节点运行日志、医生复核日志和报告版本追踪；复杂权限系统仍留到后续 MVP 验收阶段。
