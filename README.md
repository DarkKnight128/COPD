# COPD LangGraph 智能辅助评估骨架

本项目是一个慢阻肺病智能诊疗决策支持系统的 LangGraph 评估流程骨架。当前阶段只关注本地可运行、结构清晰、便于扩展的评估编排，不包含前端、后端、数据库、模型部署或真实患者数据。

## 当前阶段目标

- 初始化一个 Python + LangGraph 项目结构。
- 定义 COPDState 作为图流程共享状态。
- 搭建最小评估流程，并让所有节点按固定顺序执行。
- 使用规则和模板生成一份辅助评估草稿。
- 提供样例患者 JSON 和本地运行脚本，方便新同学快速验证。

## 当前做什么

- 读取样例患者输入数据。
- 执行基础数据质量检查。
- 拼接病程摘要。
- 用简单规则生成当前状态、表型和风险评估。
- 整理关键证据。
- 检查潜在越界表达。
- 生成不包含具体治疗方案的报告草稿。

## 当前不做什么

- 不做前端、FastAPI 后端、数据库或 Docker。
- 不接入 Qwen 模型、bge-m3 embedding 或模型权重。
- 不处理真实患者数据、原始 CT 图像或 DICOM。
- 不做医生复核页面、报告导出、HIS/PACS/EMR 接口。
- 不输出具体治疗方案。

## 目录结构

```text
copd-langgraph/
  README.md
  .gitignore
  requirements.txt

  data/
    sample_patient.json

  src/
    copd_graph/
      __init__.py
      state.py
      graph.py
      nodes/
        __init__.py
        load_patient_data.py
        data_quality_check.py
        timeline_analyzer.py
        assessment_generator.py
        evidence_builder.py
        safety_check.py
        report_generator.py

  scripts/
    run_sample.py

  tests/
    test_graph_import.py
```

## 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 运行 Sample

```bash
python scripts/run_sample.py
```

脚本会读取 `data/sample_patient.json`，构造初始 state，调用 LangGraph，并打印数据质量、病程摘要、当前状态、表型、风险评估、关键证据、安全检查结果和报告草稿。

## 运行测试

```bash
pytest
```

## 后续扩展方向

- 将 `load_patient_data` 扩展为标准化数据导入节点。
- 将规则占位节点逐步替换为可配置评估逻辑或大模型调用。
- 增加更完整的数据质量检查和结构化错误处理。
- 加入报告结构化输出、医生复核状态和审计字段。
- 增加更多样例数据和面向节点的单元测试。
