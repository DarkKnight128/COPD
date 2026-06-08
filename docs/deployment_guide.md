# COPD MVP 部署说明

## 运行环境

- Windows 10/11
- Python 3.10 或以上
- 本地 SQLite 数据库
- 浏览器访问 FastAPI + Jinja 页面

## 安装步骤

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 通义千问配置

复制 `.env.example` 为 `.env`，只在 `.env` 中填写真实配置。

```text
DASHSCOPE_API_KEY=
QWEN_MODEL_NAME=
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_TIMEOUT_SECONDS=30
QWEN_ENABLE=false
```

安全要求：

- `.env` 已被 `.gitignore` 忽略，不要上传 GitHub。
- `.env.example` 只能保留占位字段。
- 操作日志、页面和 API 返回中不得出现 API Key。

## 启动系统

```powershell
python scripts\run_poc_server.py
```

访问：

```text
http://127.0.0.1:8001
```

## 演示账号

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 管理员 | admin | admin123 |
| 医生 | doctor | doctor123 |
| 科研人员 | researcher | researcher123 |

## 数据文件

- 数据库默认位置：`data/poc_demo_v2.sqlite`
- 官方导入模板：`data/copd_patient_import_template.xlsx`
- 100 例样例数据：`data/copd_patient_import_sample_100.xlsx`

## 验收前检查

1. 使用管理员登录。
2. 上传 100 例样例数据。
3. 使用医生账号触发本地规则评估。
4. 查看评估结果、关键证据和模型版本。
5. 编辑、确认或驳回报告。
6. 打开导出页，浏览器打印为 PDF。
7. 使用管理员账号查看操作日志。
8. 使用管理员账号查看系统配置状态，确认 Qwen 和数据路径配置正确。
