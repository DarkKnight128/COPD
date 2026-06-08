from __future__ import annotations

import hashlib
import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from copd_graph.graph import build_graph
from copd_graph.poc_storage import (
    DEFAULT_DB_PATH,
    ImportValidationError,
    build_patient_state_data,
    connect,
    delete_patients,
    ensure_report_for_assessment,
    confirm_report,
    get_assessment,
    get_assessment_model_logs,
    get_assessment_node_logs,
    get_import_batch,
    get_latest_assessment,
    get_patient_bundle,
    get_report,
    get_report_by_assessment,
    get_user_by_id,
    import_workbook,
    init_database,
    authenticate_user,
    list_audit_logs,
    list_import_batches,
    list_patients,
    list_users,
    log_audit_event,
    reject_report,
    review_assessment,
    save_assessment,
    save_report_version,
)
from copd_graph.time_utils import LOCAL_TIMEZONE
from copd_graph.xlsx_importer import parse_xlsx_bytes


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"

@asynccontextmanager
async def lifespan(_: FastAPI):
    with connect(DEFAULT_DB_PATH) as connection:
        init_database(connection)
    yield


app = FastAPI(title="COPD POC Demo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
SESSION_COOKIE = "copd_demo_session"
SESSION_SECRET = os.getenv("COPD_SESSION_SECRET", "copd-poc-demo-session-secret-change-me")

VIEW_ROLES = {"管理员", "医生", "科研人员"}
ADMIN_ROLES = {"管理员"}
CLINICAL_ROLES = {"管理员", "医生"}
DOCTOR_ROLES = {"医生"}


def render_template(request: Request, template_name: str, context: Dict[str, Any]) -> HTMLResponse:
    payload = dict(context)
    payload["current_user"] = get_current_user(request)
    return templates.TemplateResponse(request, template_name, payload)


def sign_session(user_id: int | str) -> str:
    user_text = str(user_id)
    signature = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        user_text.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{user_text}.{signature}"


def verify_session(token: str) -> int | None:
    if "." not in token:
        return None
    user_text, signature = token.split(".", 1)
    expected = hmac.new(
        SESSION_SECRET.encode("utf-8"),
        user_text.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        return int(user_text)
    except ValueError:
        return None


def get_current_user(request: Request) -> Dict[str, Any] | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user_id = verify_session(token)
    if user_id is None:
        return None
    with connect(DEFAULT_DB_PATH) as connection:
        return get_user_by_id(connection, user_id)


def login_redirect(request: Request) -> RedirectResponse:
    next_url = request.url.path
    if request.url.query:
        next_url += f"?{request.url.query}"
    return RedirectResponse(url=f"/login?next={quote(next_url)}", status_code=303)


def require_page_role(
    request: Request, allowed_roles: set[str] = VIEW_ROLES
) -> Dict[str, Any] | RedirectResponse:
    user = get_current_user(request)
    if user is None:
        return login_redirect(request)
    if user["role"] not in allowed_roles:
        raise HTTPException(status_code=403, detail="当前账号没有权限访问该功能")
    return user


def require_api_role(request: Request, allowed_roles: set[str] = VIEW_ROLES) -> Dict[str, Any]:
    user = get_current_user(request)
    if user is None:
        record_audit(None, "unauthorized_access", result="失败", failure_reason="未登录")
        raise HTTPException(status_code=401, detail="请先登录")
    if user["role"] not in allowed_roles:
        record_audit(
            user,
            "forbidden_access",
            result="失败",
            failure_reason="当前账号没有权限访问该功能",
        )
        raise HTTPException(status_code=403, detail="当前账号没有权限访问该功能")
    return user


def record_audit(
    user: Dict[str, Any] | None,
    action: str,
    *,
    object_type: str | None = None,
    object_id: str | None = None,
    result: str = "成功",
    failure_reason: str | None = None,
) -> None:
    with connect(DEFAULT_DB_PATH) as connection:
        log_audit_event(
            connection,
            username=(user or {}).get("username"),
            role=(user or {}).get("role"),
            action=action,
            object_type=object_type,
            object_id=object_id,
            result=result,
            failure_reason=failure_reason,
        )


def format_local_time(value: Any) -> str:
    if not value:
        return "-"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def format_node_logs(node_logs: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    formatted = []
    for log in node_logs:
        item = dict(log)
        item["started_at_display"] = format_local_time(item.get("started_at"))
        item["ended_at_display"] = format_local_time(item.get("ended_at"))
        formatted.append(item)
    return formatted


@app.get("/", response_class=HTMLResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/patients", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/patients", error: str = "") -> HTMLResponse:
    return render_template(request, "login.html", {"next": next or "/patients", "error": error})


@app.post("/login")
def login_submit(
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/patients"),
) -> RedirectResponse:
    with connect(DEFAULT_DB_PATH) as connection:
        user = authenticate_user(connection, username.strip(), password)
    if user is None:
        record_audit(
            {"username": username.strip(), "role": None},
            "login",
            result="失败",
            failure_reason="用户名或密码错误",
        )
        return RedirectResponse(
            url=f"/login?next={quote(next or '/patients')}&error={quote('用户名或密码错误')}",
            status_code=303,
        )
    response = RedirectResponse(url=next or "/patients", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        sign_session(user["user_id"]),
        httponly=True,
        samesite="lax",
    )
    record_audit(user, "login")
    return response


@app.post("/logout")
def logout(request: Request) -> RedirectResponse:
    user = get_current_user(request)
    if user:
        record_audit(user, "logout")
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/admin/logs", response_class=HTMLResponse)
def admin_logs_page(
    request: Request,
    action: str = "",
    user: str = "",
    result: str = "",
    date_from: str = "",
    date_to: str = "",
) -> Any:
    current_user = require_page_role(request, ADMIN_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        logs = list_audit_logs(
            connection,
            action=action,
            user=user,
            result=result,
            date_from=date_from,
            date_to=date_to,
        )
    return render_template(
        request,
        "admin_logs.html",
        {
            "logs": logs,
            "action": action,
            "user": user,
            "result": result,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request) -> Any:
    current_user = require_page_role(request, ADMIN_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        users = list_users(connection)
    return render_template(request, "admin_users.html", {"users": users})


@app.get("/admin/config", response_class=HTMLResponse)
def admin_config_page(request: Request) -> Any:
    current_user = require_page_role(request, ADMIN_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    config = {
        "database_path": str(DEFAULT_DB_PATH),
        "template_path": str(PROJECT_ROOT / "data" / "copd_patient_import_template.xlsx"),
        "sample_data_path": str(PROJECT_ROOT / "data" / "copd_patient_import_sample_100.xlsx"),
        "qwen_enable": os.getenv("QWEN_ENABLE", "false"),
        "qwen_model_name": os.getenv("QWEN_MODEL_NAME", "未配置") or "未配置",
        "qwen_base_url": os.getenv(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        "qwen_timeout_seconds": os.getenv("QWEN_TIMEOUT_SECONDS", "30"),
        "dashscope_api_key_status": "已配置" if os.getenv("DASHSCOPE_API_KEY") else "未配置",
    }
    return render_template(request, "admin_config.html", {"config": config})


@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request) -> Any:
    current_user = require_page_role(request, ADMIN_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        batches = list_import_batches(connection)
    return render_template(request, "import.html", {"batches": batches})


@app.post("/import-upload")
async def import_upload(request: Request, file: UploadFile = File(...)) -> HTMLResponse:
    current_user = require_page_role(request, ADMIN_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    if not file.filename.lower().endswith(".xlsx"):
        record_audit(
            current_user,
            "import_patients",
            object_type="import_batch",
            result="失败",
            failure_reason="上传文件不是 .xlsx",
        )
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file")
    content = await file.read()
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            result = import_workbook(connection, parse_xlsx_bytes(content), file.filename)
        except ImportValidationError as error:
            result = error.result
    record_audit(
        current_user,
        "import_patients",
        object_type="import_batch",
        object_id=str(result.get("batch_id", "")),
        result="成功" if result.get("status") == "success" else "失败",
        failure_reason="" if result.get("status") == "success" else "导入校验失败",
    )
    return render_template(request, "import_result.html", {"result": result})


@app.get("/imports", response_class=HTMLResponse)
def imports_page(request: Request) -> Any:
    current_user = require_page_role(request, ADMIN_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        batches = list_import_batches(connection)
    return render_template(request, "imports.html", {"batches": batches})


@app.get("/imports/{batch_id}", response_class=HTMLResponse)
def import_detail_page(request: Request, batch_id: int) -> Any:
    current_user = require_page_role(request, ADMIN_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        batch = get_import_batch(connection, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return render_template(request, "import_detail.html", {"batch": batch})


@app.get("/patients", response_class=HTMLResponse)
def patients_page(
    request: Request,
    q: str = "",
    risk: str = "",
    assessment_status: str = "",
    followup_status: str = "",
    import_batch_id: str = "",
    review_status: str = "",
    report_status: str = "",
) -> HTMLResponse:
    current_user = require_page_role(request, VIEW_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        patients = list_patients(
            connection,
            q,
            risk=risk,
            assessment_status=assessment_status,
            followup_status=followup_status,
            import_batch_id=import_batch_id,
            review_status=review_status,
            report_status=report_status,
        )
        batches = list_import_batches(connection)
    return render_template(
        request,
        "patients.html",
        {
            "patients": patients,
            "q": q,
            "risk": risk,
            "assessment_status": assessment_status,
            "followup_status": followup_status,
            "import_batch_id": import_batch_id,
            "review_status": review_status,
            "report_status": report_status,
            "batches": batches,
        },
    )


@app.post("/patients/delete")
def delete_patients_page(request: Request, patient_ids: list[str] = Form(default=[])) -> RedirectResponse:
    current_user = require_page_role(request, ADMIN_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        counts = delete_patients(connection, patient_ids)
    record_audit(
        current_user,
        "delete_patients",
        object_type="patient",
        object_id=",".join(patient_ids),
        result="成功",
        failure_reason="" if counts.get("patients", 0) else "未删除患者",
    )
    return RedirectResponse(url="/patients", status_code=303)


@app.post("/patients/{patient_id}/delete")
def delete_patient_page(request: Request, patient_id: str) -> RedirectResponse:
    current_user = require_page_role(request, ADMIN_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        counts = delete_patients(connection, [patient_id])
    record_audit(
        current_user,
        "delete_patient",
        object_type="patient",
        object_id=patient_id,
        result="成功",
        failure_reason="" if counts.get("patients", 0) else "未删除患者",
    )
    return RedirectResponse(url="/patients", status_code=303)


@app.get("/patients/{patient_id}", response_class=HTMLResponse)
def patient_detail_page(request: Request, patient_id: str) -> Any:
    current_user = require_page_role(request, VIEW_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        bundle = get_patient_bundle(connection, patient_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return render_template(request, "patient_detail.html", bundle)


@app.get("/patients/{patient_id}/timeline", response_class=HTMLResponse)
def timeline_page(request: Request, patient_id: str) -> Any:
    current_user = require_page_role(request, VIEW_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        bundle = get_patient_bundle(connection, patient_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    events = build_timeline_events(bundle)
    return render_template(
        request,
        "timeline.html",
        {
            "patient": bundle["patient"],
            "events": events,
        },
    )


@app.post("/patients/{patient_id}/assessment")
def run_assessment_page(
    request: Request,
    patient_id: str,
    assessment_mode: str = Form(default="api"),
) -> RedirectResponse:
    current_user = require_page_role(request, CLINICAL_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    try:
        assessment = run_patient_assessment(patient_id, assessment_mode=assessment_mode)
    except HTTPException as error:
        record_audit(
            current_user,
            "run_assessment",
            object_type="patient",
            object_id=patient_id,
            result="失败",
            failure_reason=str(error.detail),
        )
        raise
    record_audit(
        current_user,
        "run_assessment",
        object_type="assessment",
        object_id=assessment["assessment_id"],
    )
    return RedirectResponse(url=f"/assessments/{assessment['assessment_id']}", status_code=303)


@app.get("/patients/{patient_id}/assessment", response_class=HTMLResponse)
def patient_assessment_page(request: Request, patient_id: str) -> Any:
    current_user = require_page_role(request, VIEW_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        bundle = get_patient_bundle(connection, patient_id)
        assessment = get_latest_assessment(connection, patient_id)
        model_logs = (
            get_assessment_model_logs(connection, assessment["assessment_id"])
            if assessment
            else []
        )
        node_logs = (
            get_assessment_node_logs(connection, assessment["assessment_id"])
            if assessment
            else []
        )
        report = (
            ensure_report_for_assessment(connection, assessment["assessment_id"])
            if assessment
            else None
        )
    if bundle is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return render_template(
        request,
        "assessment.html",
        {
            "patient": bundle["patient"],
            "assessment": assessment,
            "report_record": report,
            "model_logs": model_logs,
            "node_logs": format_node_logs(node_logs),
        },
    )


@app.get("/assessments/{assessment_id}", response_class=HTMLResponse)
def assessment_page(request: Request, assessment_id: str) -> Any:
    current_user = require_page_role(request, VIEW_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        assessment = get_assessment(connection, assessment_id)
        model_logs = get_assessment_model_logs(connection, assessment_id)
        node_logs = get_assessment_node_logs(connection, assessment_id)
        report = ensure_report_for_assessment(connection, assessment_id) if assessment else None
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return render_template(
        request,
        "assessment.html",
        {
            "patient": {"patient_id": assessment["patient_id"]},
            "assessment": assessment,
            "report_record": report,
            "model_logs": model_logs,
            "node_logs": format_node_logs(node_logs),
        },
    )


@app.get("/assessments/{assessment_id}/report", response_class=HTMLResponse)
def report_page(request: Request, assessment_id: str) -> Any:
    current_user = require_page_role(request, VIEW_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        assessment = get_assessment(connection, assessment_id)
        report = ensure_report_for_assessment(connection, assessment_id) if assessment else None
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return render_template(
        request,
        "report.html",
        {
            "assessment": assessment,
            "report_record": report,
            "report": assessment.get("report_draft", ""),
        },
    )


@app.get("/assessments/{assessment_id}/review", response_class=HTMLResponse)
def review_page(request: Request, assessment_id: str) -> Any:
    current_user = require_page_role(request, DOCTOR_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        assessment = get_assessment(connection, assessment_id)
        if assessment is None:
            raise HTTPException(status_code=404, detail="Assessment not found")
        report = ensure_report_for_assessment(connection, assessment_id)
    return render_template(
        request,
        "review.html",
        {"assessment": assessment, "report_record": report},
    )


@app.post("/assessments/{assessment_id}/review")
def submit_review(
    request: Request,
    assessment_id: str,
    action: str = Form(...),
    reviewer_name: str = Form(default=""),
    review_comment: str = Form(default=""),
) -> RedirectResponse:
    current_user = require_page_role(request, DOCTOR_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    reviewer = reviewer_name or current_user["display_name"]
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            report = review_assessment(
                connection,
                assessment_id,
                action,
                reviewer_name=reviewer,
                review_comment=review_comment,
            )
        except KeyError as error:
            record_audit(
                current_user,
                "review_assessment",
                object_type="assessment",
                object_id=assessment_id,
                result="失败",
                failure_reason=str(error),
            )
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            record_audit(
                current_user,
                "review_assessment",
                object_type="assessment",
                object_id=assessment_id,
                result="失败",
                failure_reason=str(error),
            )
            raise HTTPException(status_code=400, detail=str(error)) from error
    record_audit(
        current_user,
        "review_assessment",
        object_type="assessment",
        object_id=assessment_id,
    )
    return RedirectResponse(url=f"/reports/{report['report_id']}/edit", status_code=303)


@app.get("/reports/{report_id}/edit", response_class=HTMLResponse)
def report_edit_page(request: Request, report_id: int) -> Any:
    current_user = require_page_role(request, DOCTOR_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        report = get_report(connection, report_id)
        assessment = get_assessment(connection, report["assessment_id"]) if report else None
    if report is None or assessment is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return render_template(
        request,
        "report_edit.html",
        {"report_record": report, "assessment": assessment},
    )


@app.post("/reports/{report_id}/edit")
def save_report_edit(
    request: Request,
    report_id: int,
    content: str = Form(...),
    edited_by: str = Form(default=""),
    change_summary: str = Form(default=""),
) -> RedirectResponse:
    current_user = require_page_role(request, DOCTOR_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    editor = edited_by or current_user["display_name"]
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            report = save_report_version(
                connection,
                report_id,
                content,
                edited_by=editor,
                change_summary=change_summary,
            )
        except KeyError as error:
            record_audit(
                current_user,
                "edit_report",
                object_type="report",
                object_id=str(report_id),
                result="失败",
                failure_reason=str(error),
            )
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            record_audit(
                current_user,
                "edit_report",
                object_type="report",
                object_id=str(report_id),
                result="失败",
                failure_reason=str(error),
            )
            raise HTTPException(status_code=400, detail=str(error)) from error
    record_audit(current_user, "edit_report", object_type="report", object_id=str(report_id))
    return RedirectResponse(url=f"/reports/{report['report_id']}/edit", status_code=303)


@app.post("/reports/{report_id}/confirm")
def confirm_report_page(
    request: Request,
    report_id: int,
    reviewer_name: str = Form(default=""),
    review_comment: str = Form(default=""),
) -> RedirectResponse:
    current_user = require_page_role(request, DOCTOR_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    reviewer = reviewer_name or current_user["display_name"]
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            report = confirm_report(
                connection,
                report_id,
                reviewer_name=reviewer,
                review_comment=review_comment,
            )
        except KeyError as error:
            record_audit(
                current_user,
                "confirm_report",
                object_type="report",
                object_id=str(report_id),
                result="失败",
                failure_reason=str(error),
            )
            raise HTTPException(status_code=404, detail=str(error)) from error
    record_audit(current_user, "confirm_report", object_type="report", object_id=str(report_id))
    return RedirectResponse(url=f"/reports/{report['report_id']}/edit", status_code=303)


@app.post("/reports/{report_id}/reject")
def reject_report_page(
    request: Request,
    report_id: int,
    reviewer_name: str = Form(default=""),
    review_comment: str = Form(default=""),
) -> RedirectResponse:
    current_user = require_page_role(request, DOCTOR_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    reviewer = reviewer_name or current_user["display_name"]
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            report = reject_report(
                connection,
                report_id,
                reviewer_name=reviewer,
                review_comment=review_comment,
            )
        except KeyError as error:
            record_audit(
                current_user,
                "reject_report",
                object_type="report",
                object_id=str(report_id),
                result="失败",
                failure_reason=str(error),
            )
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            record_audit(
                current_user,
                "reject_report",
                object_type="report",
                object_id=str(report_id),
                result="失败",
                failure_reason=str(error),
            )
            raise HTTPException(status_code=400, detail=str(error)) from error
    record_audit(current_user, "reject_report", object_type="report", object_id=str(report_id))
    return RedirectResponse(url=f"/reports/{report['report_id']}/edit", status_code=303)


@app.get("/reports/{report_id}/export", response_class=HTMLResponse)
def report_export_page(request: Request, report_id: int) -> Any:
    current_user = require_page_role(request, CLINICAL_ROLES)
    if isinstance(current_user, RedirectResponse):
        return current_user
    with connect(DEFAULT_DB_PATH) as connection:
        report = get_report(connection, report_id)
        assessment = get_assessment(connection, report["assessment_id"]) if report else None
        model_logs = (
            get_assessment_model_logs(connection, report["assessment_id"])
            if report
            else []
        )
    if report is None or assessment is None:
        raise HTTPException(status_code=404, detail="Report not found")
    record_audit(current_user, "export_report", object_type="report", object_id=str(report_id))
    return render_template(
        request,
        "report_export.html",
        {"report_record": report, "assessment": assessment, "model_logs": model_logs},
    )


@app.post("/api/import/patients")
async def api_import_patients(request: Request, file: UploadFile = File(...)) -> Dict[str, Any]:
    current_user = require_api_role(request, ADMIN_ROLES)
    if not file.filename.lower().endswith(".xlsx"):
        record_audit(
            current_user,
            "import_patients",
            object_type="import_batch",
            result="失败",
            failure_reason="上传文件不是 .xlsx",
        )
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file")
    workbook = parse_xlsx_bytes(await file.read())
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            result = import_workbook(connection, workbook, file.filename)
        except ImportValidationError as error:
            record_audit(
                current_user,
                "import_patients",
                object_type="import_batch",
                object_id=str(error.result.get("batch_id", "")),
                result="失败",
                failure_reason="导入校验失败",
            )
            raise HTTPException(status_code=400, detail=error.result) from error
    record_audit(
        current_user,
        "import_patients",
        object_type="import_batch",
        object_id=str(result.get("batch_id", "")),
    )
    return result


@app.get("/api/imports")
def api_imports(request: Request) -> Dict[str, Any]:
    require_api_role(request, ADMIN_ROLES)
    with connect(DEFAULT_DB_PATH) as connection:
        batches = list_import_batches(connection)
    return {"imports": batches, "count": len(batches)}


@app.get("/api/imports/{batch_id}")
def api_import(request: Request, batch_id: int) -> Dict[str, Any]:
    require_api_role(request, ADMIN_ROLES)
    with connect(DEFAULT_DB_PATH) as connection:
        batch = get_import_batch(connection, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return batch


@app.get("/api/patients")
def api_patients(
    request: Request,
    q: str = "",
    risk: str = "",
    assessment_status: str = "",
    followup_status: str = "",
    import_batch_id: str = "",
    review_status: str = "",
    report_status: str = "",
) -> Dict[str, Any]:
    require_api_role(request, VIEW_ROLES)
    with connect(DEFAULT_DB_PATH) as connection:
        patients = list_patients(
            connection,
            q,
            risk=risk,
            assessment_status=assessment_status,
            followup_status=followup_status,
            import_batch_id=import_batch_id,
            review_status=review_status,
            report_status=report_status,
        )
    return {"patients": patients, "count": len(patients)}


@app.post("/api/patients/delete")
async def api_delete_patients(request: Request) -> Dict[str, Any]:
    current_user = require_api_role(request, ADMIN_ROLES)
    payload = await request.json()
    patient_ids = payload.get("patient_ids", [])
    if not isinstance(patient_ids, list):
        raise HTTPException(status_code=400, detail="patient_ids must be a list")
    with connect(DEFAULT_DB_PATH) as connection:
        counts = delete_patients(connection, patient_ids)
    record_audit(
        current_user,
        "delete_patients",
        object_type="patient",
        object_id=",".join(patient_ids),
    )
    return {"deleted": counts}


@app.delete("/api/patients/{patient_id}")
def api_delete_patient(request: Request, patient_id: str) -> Dict[str, Any]:
    current_user = require_api_role(request, ADMIN_ROLES)
    with connect(DEFAULT_DB_PATH) as connection:
        counts = delete_patients(connection, [patient_id])
    record_audit(current_user, "delete_patient", object_type="patient", object_id=patient_id)
    return {"deleted": counts}


@app.get("/api/patients/{patient_id}")
def api_patient(request: Request, patient_id: str) -> Dict[str, Any]:
    require_api_role(request, VIEW_ROLES)
    with connect(DEFAULT_DB_PATH) as connection:
        bundle = get_patient_bundle(connection, patient_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return bundle


@app.get("/api/patients/{patient_id}/timeline")
def api_timeline(request: Request, patient_id: str) -> Dict[str, Any]:
    require_api_role(request, VIEW_ROLES)
    with connect(DEFAULT_DB_PATH) as connection:
        bundle = get_patient_bundle(connection, patient_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return {"patient_id": patient_id, "events": build_timeline_events(bundle)}


@app.post("/api/patients/{patient_id}/assessment")
def api_run_assessment(
    request: Request, patient_id: str, assessment_mode: str = "api"
) -> Dict[str, Any]:
    current_user = require_api_role(request, CLINICAL_ROLES)
    try:
        assessment = run_patient_assessment(patient_id, assessment_mode=assessment_mode)
    except HTTPException as error:
        record_audit(
            current_user,
            "run_assessment",
            object_type="patient",
            object_id=patient_id,
            result="失败",
            failure_reason=str(error.detail),
        )
        raise
    record_audit(
        current_user,
        "run_assessment",
        object_type="assessment",
        object_id=assessment["assessment_id"],
    )
    return assessment


@app.get("/api/assessments/{assessment_id}")
def api_assessment(request: Request, assessment_id: str) -> Dict[str, Any]:
    require_api_role(request, VIEW_ROLES)
    with connect(DEFAULT_DB_PATH) as connection:
        assessment = get_assessment(connection, assessment_id)
        model_logs = get_assessment_model_logs(connection, assessment_id)
        node_logs = get_assessment_node_logs(connection, assessment_id)
        report = ensure_report_for_assessment(connection, assessment_id) if assessment else None
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    assessment["report"] = report
    assessment["model_logs"] = model_logs
    assessment["node_logs"] = format_node_logs(node_logs)
    return assessment


@app.post("/api/assessments/{assessment_id}/report")
def api_report(request: Request, assessment_id: str) -> Dict[str, Any]:
    require_api_role(request, VIEW_ROLES)
    with connect(DEFAULT_DB_PATH) as connection:
        assessment = get_assessment(connection, assessment_id)
        report = ensure_report_for_assessment(connection, assessment_id) if assessment else None
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return {
        "assessment_id": assessment_id,
        "patient_id": assessment["patient_id"],
        "report_id": report["report_id"],
        "report_status": report["report_status"],
        "review_status": report["review_status"],
        "current_version": report["current_version"],
        "report_draft": report.get("current_content") or assessment.get("report_draft", ""),
    }


@app.get("/api/reports/{report_id}")
def api_get_report(request: Request, report_id: int) -> Dict[str, Any]:
    require_api_role(request, VIEW_ROLES)
    with connect(DEFAULT_DB_PATH) as connection:
        report = get_report(connection, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@app.post("/api/reports/{report_id}/confirm")
async def api_confirm_report(report_id: int, request: Request) -> Dict[str, Any]:
    current_user = require_api_role(request, DOCTOR_ROLES)
    payload = await request.json()
    reviewer = payload.get("reviewer_name") or current_user["display_name"]
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            report = confirm_report(
                connection,
                report_id,
                reviewer_name=reviewer,
                review_comment=payload.get("review_comment", ""),
            )
        except KeyError as error:
            record_audit(
                current_user,
                "confirm_report",
                object_type="report",
                object_id=str(report_id),
                result="失败",
                failure_reason=str(error),
            )
            raise HTTPException(status_code=404, detail=str(error)) from error
    record_audit(current_user, "confirm_report", object_type="report", object_id=str(report_id))
    return report


@app.post("/api/reports/{report_id}/reject")
async def api_reject_report(report_id: int, request: Request) -> Dict[str, Any]:
    current_user = require_api_role(request, DOCTOR_ROLES)
    payload = await request.json()
    reviewer = payload.get("reviewer_name") or current_user["display_name"]
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            report = reject_report(
                connection,
                report_id,
                reviewer_name=reviewer,
                review_comment=payload.get("review_comment", ""),
            )
        except KeyError as error:
            record_audit(
                current_user,
                "reject_report",
                object_type="report",
                object_id=str(report_id),
                result="失败",
                failure_reason=str(error),
            )
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            record_audit(
                current_user,
                "reject_report",
                object_type="report",
                object_id=str(report_id),
                result="失败",
                failure_reason=str(error),
            )
            raise HTTPException(status_code=400, detail=str(error)) from error
    record_audit(current_user, "reject_report", object_type="report", object_id=str(report_id))
    return report


@app.get("/api/me")
def api_me(request: Request) -> Dict[str, Any]:
    return {"user": require_api_role(request, VIEW_ROLES)}


@app.get("/api/audit-logs")
def api_audit_logs(
    request: Request,
    action: str = "",
    user: str = "",
    result: str = "",
    date_from: str = "",
    date_to: str = "",
) -> Dict[str, Any]:
    require_api_role(request, ADMIN_ROLES)
    with connect(DEFAULT_DB_PATH) as connection:
        logs = list_audit_logs(
            connection,
            action=action,
            user=user,
            result=result,
            date_from=date_from,
            date_to=date_to,
        )
    return {"logs": logs, "count": len(logs)}


def run_patient_assessment(patient_id: str, assessment_mode: str = "api") -> Dict[str, Any]:
    mode = assessment_mode if assessment_mode in {"api", "local_rules"} else "api"
    with connect(DEFAULT_DB_PATH) as connection:
        try:
            patient_data = build_patient_state_data(connection, patient_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        graph = build_graph()
        result = graph.invoke({"raw_patient_data": patient_data, "assessment_mode": mode})
        return save_assessment(connection, patient_id, result)


def build_timeline_events(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    events = []
    for visit in bundle["visits"]:
        events.append(
            {
                "date": visit.get("event_date", ""),
                "type": visit.get("event_type", "病程事件"),
                "title": visit.get("event_type", "病程事件"),
                "detail": visit.get("event_detail", ""),
                "severity": visit.get("severity", ""),
            }
        )
    for lab in bundle["labs"]:
        events.append(
            {
                "date": lab.get("sample_date", ""),
                "type": "检验",
                "title": "实验室检验",
                "detail": f"WBC {lab.get('WBC_109L', '未知')}，CRP {lab.get('CRP_mgL', '未知')}，病原学：{lab.get('pathogen_result', '未记录')}",
                "severity": "",
            }
        )
    events.sort(key=lambda item: str(item.get("date", "")))
    return events
