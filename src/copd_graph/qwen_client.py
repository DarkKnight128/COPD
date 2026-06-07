from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class QwenConfig:
    enabled: bool
    api_key: str
    model_name: str
    base_url: str
    timeout_seconds: int


def load_qwen_config() -> QwenConfig:
    timeout_text = os.getenv("QWEN_TIMEOUT_SECONDS", "30")
    try:
        timeout_seconds = int(timeout_text)
    except ValueError:
        timeout_seconds = 30
    return QwenConfig(
        enabled=os.getenv("QWEN_ENABLE", "false").strip().lower() in {"1", "true", "yes", "on"},
        api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
        model_name=os.getenv("QWEN_MODEL_NAME", "").strip(),
        base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").strip().rstrip("/"),
        timeout_seconds=timeout_seconds,
    )


def qwen_metadata(config: QwenConfig | None = None) -> Dict[str, Any]:
    config = config or load_qwen_config()
    return {
        "provider": "aliyun-dashscope",
        "model_name": config.model_name or "未配置",
        "model_version": config.model_name or "未配置",
        "enabled": config.enabled,
    }


def call_qwen_structured(
    task_name: str,
    patient_payload: Dict[str, Any],
    output_schema: Dict[str, Any],
    force_local_rules: bool = False,
) -> Dict[str, Any]:
    config = load_qwen_config()
    metadata = qwen_metadata(config)
    if force_local_rules:
        return _failure(metadata, "local_rules", "本次选择本地规则评估，未调用通义千问 API。")
    if not config.enabled:
        return _failure(metadata, "disabled", "QWEN_ENABLE=false，使用规则占位评估。")
    if not config.api_key:
        return _failure(metadata, "missing_api_key", "缺少 DASHSCOPE_API_KEY，使用规则占位评估。")
    if not config.model_name:
        return _failure(metadata, "missing_model_name", "缺少 QWEN_MODEL_NAME，使用规则占位评估。")

    messages = [
        {
            "role": "system",
            "content": (
                "你是慢阻肺辅助评估系统中的结构化信息抽取与风险解释模块。"
                "只能输出 JSON，不得输出具体治疗方案、处方、最终诊断或替代医生判断。"
                "CT 只能基于报告文本或已提取影像特征，mNGS 只能作为感染相关线索。"
                "安全声明请使用“不替代医生临床判断”，不要使用“最终诊断”这个词。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": task_name,
                    "patient_data": patient_payload,
                    "required_output_schema": output_schema,
                },
                ensure_ascii=False,
            ),
        },
    ]
    body = {
        "model": config.model_name,
        "messages": messages,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        f"{config.base_url}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        reason = _safe_error_text(error)
        return _failure(metadata, "http_error", reason)
    except (urllib.error.URLError, TimeoutError) as error:
        return _failure(metadata, "network_error", str(error))
    except json.JSONDecodeError:
        return _failure(metadata, "invalid_response", "通义千问响应不是合法 JSON。")

    try:
        content = raw["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return _failure(metadata, "invalid_model_json", "模型输出无法解析为结构化 JSON。")

    return {
        "status": "success",
        "failure_reason": "",
        "output": parsed,
        **metadata,
    }


def _failure(metadata: Dict[str, Any], status: str, reason: str) -> Dict[str, Any]:
    return {
        "status": status,
        "failure_reason": reason,
        "output": {},
        **metadata,
    }


def _safe_error_text(error: urllib.error.HTTPError) -> str:
    try:
        text = error.read().decode("utf-8", errors="replace")
    except Exception:
        text = str(error)
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if api_key:
        text = text.replace(api_key, "[redacted]")
    return text
