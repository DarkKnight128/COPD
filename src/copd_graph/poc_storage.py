from __future__ import annotations

import json
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from copd_graph.xlsx_importer import WorkbookData
from copd_graph.time_utils import local_isoformat, now_local


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "poc_demo_v2.sqlite"


TEMPLATE_REQUIRED_FIELDS = {
    "patients": ["patient_id", "gender", "age", "created_date"],
    "smoking_history": ["patient_id", "smoking_status"],
    "comorbidities": ["patient_id"],
    "symptom_scores": ["symptom_id", "patient_id", "assessment_date"],
    "pulmonary_tests": ["pulmonary_test_id", "patient_id", "test_date"],
    "lab_results": ["lab_id", "patient_id", "lab_date"],
    "pathogen_results": ["pathogen_id", "patient_id", "pathogen_test_date"],
    "ct_features": ["ct_id", "patient_id", "ct_date"],
    "medications": ["medication_id", "patient_id", "start_date", "medication_name"],
    "exacerbations": ["exacerbation_id", "patient_id", "exacerbation_date"],
    "followups": ["followup_id", "patient_id", "followup_date"],
}

TEMPLATE_DATE_FIELDS = {
    "patients": ["birth_date", "created_date"],
    "comorbidities": ["copd_diagnosis_date"],
    "symptom_scores": ["assessment_date"],
    "pulmonary_tests": ["test_date"],
    "lab_results": ["lab_date"],
    "pathogen_results": ["pathogen_test_date"],
    "ct_features": ["ct_date"],
    "medications": ["start_date", "end_date"],
    "exacerbations": ["exacerbation_date"],
    "followups": ["followup_date"],
}

TEMPLATE_NUMERIC_RANGES = {
    "patients": {
        "age": (0, 120),
        "height_cm": (80, 230),
        "weight_kg": (20, 220),
        "bmi": (10, 60),
    },
    "smoking_history": {
        "cigarettes_per_day": (0, 120),
        "smoking_years": (0, 90),
        "pack_years": (0, 200),
        "quit_years": (0, 90),
    },
    "symptom_scores": {
        "cat_score": (0, 40),
        "mmrc_score": (0, 4),
    },
    "pulmonary_tests": {
        "fev1_l": (0.2, 8),
        "fvc_l": (0.3, 8),
        "fev1_fvc_ratio": (0.1, 1.2),
        "fev1_percent_predicted": (10, 150),
        "fvc_percent_predicted": (10, 150),
        "feno": (0, 300),
    },
    "lab_results": {
        "wbc": (0, 100),
        "neutrophil_percent": (0, 100),
        "eosinophil_count": (0, 10),
        "crp": (0, 300),
        "pct": (0, 100),
        "spo2": (50, 100),
        "pao2": (20, 200),
        "paco2": (10, 120),
    },
    "ct_features": {
        "emphysema_percent": (0, 100),
        "airway_wall_thickness": (0, 10),
        "lung_volume_index": (0, 20),
    },
}


class ImportValidationError(ValueError):
    def __init__(self, result: Dict[str, Any]):
        super().__init__("Excel导入校验失败")
        self.result = result


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    return connection


def init_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS import_batches (
            batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            status TEXT NOT NULL,
            counts_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS import_issues (
            issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            sheet_name TEXT NOT NULL,
            row_number INTEGER,
            field_name TEXT,
            severity TEXT NOT NULL,
            message TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS visits (
            event_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            event_date TEXT,
            data_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS labs (
            lab_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            sample_date TEXT,
            data_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS model_outputs (
            assessment_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            assessment_date TEXT,
            data_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS assessments (
            assessment_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            result_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS model_call_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            assessment_id TEXT NOT NULL,
            patient_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            called_at TEXT NOT NULL,
            input_data_version TEXT,
            model_name TEXT,
            model_version TEXT,
            provider TEXT,
            status TEXT NOT NULL,
            failure_reason TEXT,
            output_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS graph_node_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            assessment_id TEXT NOT NULL,
            patient_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT,
            status TEXT NOT NULL,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            assessment_id TEXT NOT NULL UNIQUE,
            patient_id TEXT NOT NULL,
            report_status TEXT NOT NULL,
            review_status TEXT NOT NULL,
            current_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            confirmed_at TEXT,
            rejected_at TEXT,
            reviewer_name TEXT,
            review_comment TEXT
        );

        CREATE TABLE IF NOT EXISTS report_versions (
            version_id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            content TEXT NOT NULL,
            edited_by TEXT,
            edited_at TEXT NOT NULL,
            change_summary TEXT
        );

        CREATE TABLE IF NOT EXISTS review_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            assessment_id TEXT NOT NULL,
            report_id INTEGER,
            patient_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reviewer_name TEXT,
            review_comment TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    _ensure_column(connection, "patients", "import_batch_id", "INTEGER")
    _ensure_column(connection, "visits", "import_batch_id", "INTEGER")
    _ensure_column(connection, "labs", "import_batch_id", "INTEGER")
    _ensure_column(connection, "model_outputs", "import_batch_id", "INTEGER")
    connection.commit()


def import_workbook(
    connection: sqlite3.Connection, workbook: WorkbookData, source_filename: str = "uploaded.xlsx"
) -> Dict[str, Any]:
    init_database(connection)
    now = local_isoformat(timespec="seconds")
    batch_id = _create_import_batch(connection, source_filename, now)
    validation = validate_workbook(connection, workbook)
    _save_import_issues(connection, batch_id, validation["issues"])
    if validation["errors"]:
        result = {
            "batch_id": batch_id,
            "source": source_filename,
            "status": "failed",
            "counts": {},
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        }
        _update_import_batch(connection, batch_id, "failed", result["counts"])
        connection.commit()
        raise ImportValidationError(result)

    if _sheet(workbook, "patients"):
        counts = _import_template_workbook(connection, workbook, now, batch_id)
    else:
        counts = _import_legacy_workbook(connection, workbook, now, batch_id)

    result = {
        "batch_id": batch_id,
        "source": source_filename,
        "status": "success",
        "counts": counts,
        "errors": [],
        "warnings": validation["warnings"],
    }
    _update_import_batch(connection, batch_id, "success", counts)
    connection.commit()
    return result


def validate_workbook(connection: sqlite3.Connection, workbook: WorkbookData) -> Dict[str, Any]:
    if _sheet(workbook, "patients"):
        issues = _validate_template_workbook(connection, workbook)
    else:
        issues = _validate_legacy_workbook(workbook)
    errors = [issue for issue in issues if issue["severity"] == "error"]
    warnings = [issue for issue in issues if issue["severity"] == "warning"]
    return {"issues": issues, "errors": errors, "warnings": warnings}


def _import_legacy_workbook(
    connection: sqlite3.Connection,
    workbook: WorkbookData,
    imported_at: str,
    batch_id: int,
) -> Dict[str, int]:

    patients = _sheet(workbook, "Patients")
    visits = _sheet(workbook, "Visits")
    labs = _sheet(workbook, "Labs")
    model_outputs = _sheet(workbook, "ModelOutputs")

    for row in patients:
        connection.execute(
            """
            INSERT INTO patients(patient_id, data_json, imported_at, import_batch_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(patient_id) DO UPDATE SET
                data_json = excluded.data_json,
                imported_at = excluded.imported_at,
                import_batch_id = excluded.import_batch_id
            """,
            (str(row["patient_id"]), json.dumps(row, ensure_ascii=False), imported_at, batch_id),
        )

    for row in visits:
        if not row.get("patient_id"):
            continue
        event_id = str(row.get("event_id") or f"{row.get('patient_id')}-{row.get('event_date')}")
        connection.execute(
            """
            INSERT INTO visits(event_id, patient_id, event_date, data_json, import_batch_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                patient_id = excluded.patient_id,
                event_date = excluded.event_date,
                data_json = excluded.data_json,
                import_batch_id = excluded.import_batch_id
            """,
            (
                event_id,
                str(row["patient_id"]),
                _as_text(row.get("event_date")),
                json.dumps(row, ensure_ascii=False),
                batch_id,
            ),
        )

    for row in labs:
        if not row.get("patient_id"):
            continue
        lab_id = str(row.get("lab_id") or f"{row.get('patient_id')}-{row.get('sample_date')}")
        connection.execute(
            """
            INSERT INTO labs(lab_id, patient_id, sample_date, data_json, import_batch_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(lab_id) DO UPDATE SET
                patient_id = excluded.patient_id,
                sample_date = excluded.sample_date,
                data_json = excluded.data_json,
                import_batch_id = excluded.import_batch_id
            """,
            (
                lab_id,
                str(row["patient_id"]),
                _as_text(row.get("sample_date")),
                json.dumps(row, ensure_ascii=False),
                batch_id,
            ),
        )

    for row in model_outputs:
        if not row.get("patient_id"):
            continue
        assessment_id = str(row.get("assessment_id") or f"mock-{row.get('patient_id')}")
        connection.execute(
            """
            INSERT INTO model_outputs(assessment_id, patient_id, assessment_date, data_json, import_batch_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(assessment_id) DO UPDATE SET
                patient_id = excluded.patient_id,
                assessment_date = excluded.assessment_date,
                data_json = excluded.data_json,
                import_batch_id = excluded.import_batch_id
            """,
            (
                assessment_id,
                str(row["patient_id"]),
                _as_text(row.get("assessment_date")),
                json.dumps(row, ensure_ascii=False),
                batch_id,
            ),
        )

    return {
        "patients": len(patients),
        "visits": len(visits),
        "labs": len(labs),
        "model_outputs": len(model_outputs),
    }


def list_patients(
    connection: sqlite3.Connection,
    query: str = "",
    risk: str = "",
    assessment_status: str = "",
    followup_status: str = "",
    import_batch_id: str | int = "",
    review_status: str = "",
    report_status: str = "",
) -> List[Dict[str, Any]]:
    init_database(connection)
    rows = connection.execute(
        "SELECT patient_id, data_json, import_batch_id FROM patients ORDER BY patient_id"
    ).fetchall()
    patients = []
    for row in rows:
        patient = json.loads(row["data_json"])
        patient_id = str(patient.get("patient_id", ""))
        if query and query.lower() not in patient_id.lower():
            continue
        model_output = get_latest_model_output(connection, patient_id)
        latest_assessment = get_latest_assessment(connection, patient_id)
        latest_report = (
            get_report_by_assessment(connection, latest_assessment["assessment_id"])
            if latest_assessment
            else None
        )
        risk_level = (model_output or {}).get("exacerbation_risk_level", "未评估")
        current_assessment_status = "已评估" if latest_assessment else "未评估"
        current_followup_status = _followup_status(patient)
        current_review_status = (latest_report or {}).get("review_status", "未生成")
        current_report_status = (latest_report or {}).get("report_status", "未生成")
        if risk and risk_level != risk:
            continue
        if assessment_status and current_assessment_status != assessment_status:
            continue
        if followup_status and current_followup_status != followup_status:
            continue
        if import_batch_id and str(row["import_batch_id"] or "") != str(import_batch_id):
            continue
        if review_status and current_review_status != review_status:
            continue
        if report_status and current_report_status != report_status:
            continue
        patients.append(
            {
                "patient_id": patient_id,
                "sex": patient.get("sex", patient.get("gender", "")),
                "age": patient.get("age", ""),
                "cat_score": patient.get("CAT_score", patient.get("cat_score", "")),
                "mmrc_score": patient.get("mMRC_score", patient.get("mmrc_score", "")),
                "risk_level": risk_level,
                "assessment_status": current_assessment_status,
                "followup_status": current_followup_status,
                "review_status": current_review_status,
                "report_status": current_report_status,
                "import_batch_id": row["import_batch_id"],
                "latest_assessment_id": (latest_assessment or {}).get("assessment_id"),
                "latest_report_id": (latest_report or {}).get("report_id"),
            }
        )
    return patients


def delete_patients(connection: sqlite3.Connection, patient_ids: Iterable[str]) -> Dict[str, int]:
    init_database(connection)
    ids = [str(patient_id).strip() for patient_id in patient_ids if str(patient_id).strip()]
    if not ids:
        return {
            "requested": 0,
            "patients": 0,
            "visits": 0,
            "labs": 0,
            "model_outputs": 0,
            "assessments": 0,
            "reports": 0,
            "report_versions": 0,
            "review_logs": 0,
            "model_call_logs": 0,
            "graph_node_logs": 0,
        }

    counts = {"requested": len(ids)}
    report_ids = []
    for patient_id in ids:
        report_rows = connection.execute(
            "SELECT report_id FROM reports WHERE patient_id = ?", (patient_id,)
        ).fetchall()
        report_ids.extend([row["report_id"] for row in report_rows])
    deleted_versions = 0
    for report_id in report_ids:
        cursor = connection.execute(
            "DELETE FROM report_versions WHERE report_id = ?", (report_id,)
        )
        deleted_versions += cursor.rowcount if cursor.rowcount != -1 else 0
    counts["report_versions"] = deleted_versions
    for table_name in [
        "visits",
        "labs",
        "model_outputs",
        "review_logs",
        "reports",
        "model_call_logs",
        "graph_node_logs",
        "assessments",
        "patients",
    ]:
        deleted = 0
        for patient_id in ids:
            cursor = connection.execute(
                f"DELETE FROM {table_name} WHERE patient_id = ?", (patient_id,)
            )
            deleted += cursor.rowcount if cursor.rowcount != -1 else 0
        counts[table_name] = deleted
    connection.commit()
    return counts


def get_patient_bundle(connection: sqlite3.Connection, patient_id: str) -> Dict[str, Any] | None:
    init_database(connection)
    row = connection.execute(
        "SELECT data_json FROM patients WHERE patient_id = ?", (patient_id,)
    ).fetchone()
    if row is None:
        return None
    latest_assessment = get_latest_assessment(connection, patient_id)
    latest_report = (
        get_report_by_assessment(connection, latest_assessment["assessment_id"])
        if latest_assessment
        else None
    )
    return {
        "patient": json.loads(row["data_json"]),
        "visits": _load_many(connection, "visits", patient_id, "event_date"),
        "labs": _load_many(connection, "labs", patient_id, "sample_date"),
        "model_output": get_latest_model_output(connection, patient_id),
        "latest_assessment": latest_assessment,
        "latest_report": latest_report,
        "longitudinal_records": _longitudinal_records(connection, patient_id),
    }


def build_patient_state_data(connection: sqlite3.Connection, patient_id: str) -> Dict[str, Any]:
    bundle = get_patient_bundle(connection, patient_id)
    if bundle is None:
        raise KeyError(f"Unknown patient_id: {patient_id}")

    patient = bundle["patient"]
    visits = bundle["visits"]
    labs = bundle["labs"]
    pathogen_rows = _pathogen_rows(patient, labs)

    clinical_tests = [
        {
            "date": _as_text(patient.get("last_followup_date")) or "日期不详",
            "CAT": patient.get("CAT_score", 0),
            "mMRC": patient.get("mMRC_score", 0),
            "FEV1": patient.get("FEV1_L"),
            "FVC": patient.get("FVC_L"),
            "FEV1_FVC": patient.get("FEV1_FVC"),
            "FEV1_percent_predicted": patient.get("FEV1_percent_predicted", patient.get("FEV1_percent_predicted_pct", "未知")),
            "FeNO": patient.get("FeNO_ppb"),
            "eosinophil_count": patient.get("eosinophil_109L"),
            "CRP": patient.get("CRP_mgL", 0),
            "WBC": _latest_value(labs, "WBC_109L", 0),
            "neutrophil_percent": _latest_value(labs, "neutrophil_pct", 0),
        }
    ]

    state_data = {
        "patient": {
            "patient_id": patient.get("patient_id"),
            "age": patient.get("age"),
            "sex": patient.get("sex", patient.get("gender")),
            "smoking_history": f"{patient.get('smoking_pack_years', '未知')}包年",
            "comorbidity": _split_text(patient.get("comorbidity", "")),
        },
        "timeline_events": [
            {
                "date": _as_text(row.get("event_date")),
                "event_type": row.get("event_type", ""),
                "event_detail": row.get("event_detail", ""),
                "severity": row.get("severity", ""),
            }
            for row in visits
        ],
        "clinical_tests": clinical_tests,
        "ct_records": [
            {
                "date": _as_text(patient.get("last_followup_date")) or "日期不详",
                "ct_feature": {
                    "emphysema_percent": patient.get("ct_feature_emphysema_pct"),
                    "airway_wall_thickening": patient.get("ct_feature_airway_wall_thickening"),
                },
                "ct_report": patient.get("ct_report_summary", ""),
                "data_type": "CT报告及已提取影像特征",
            }
        ],
        "pathogen_tests": pathogen_rows,
        "medication": {"maintenance": _split_text(patient.get("current_medication", ""))},
        "follow_up": {
            "readmission_within_90_days": _yes(patient.get("readmission_90d")),
            "survival_status": patient.get("survival_status", ""),
            "last_followup_date": _as_text(patient.get("last_followup_date")),
        },
        "mock_model_output": bundle["model_output"],
    }
    state_data["data_version"] = _data_version(state_data)
    return state_data


def save_assessment(
    connection: sqlite3.Connection, patient_id: str, result: Dict[str, Any]
) -> Dict[str, Any]:
    init_database(connection)
    timestamp = now_local().strftime("%Y%m%d%H%M%S%f")
    assessment_id = f"POC-{patient_id}-{timestamp}"
    created_at = local_isoformat(timespec="seconds")
    connection.execute(
        """
        INSERT INTO assessments(assessment_id, patient_id, created_at, result_json)
        VALUES (?, ?, ?, ?)
        """,
        (
            assessment_id,
            patient_id,
            created_at,
            json.dumps(result, ensure_ascii=False),
        ),
    )
    _save_model_call_logs(connection, assessment_id, patient_id, created_at, result)
    _save_node_run_logs(connection, assessment_id, patient_id, result)
    _ensure_report_for_assessment(connection, assessment_id, patient_id, result)
    connection.commit()
    return {"assessment_id": assessment_id, **result}


def get_assessment(connection: sqlite3.Connection, assessment_id: str) -> Dict[str, Any] | None:
    init_database(connection)
    row = connection.execute(
        "SELECT assessment_id, patient_id, created_at, result_json FROM assessments WHERE assessment_id = ?",
        (assessment_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "assessment_id": row["assessment_id"],
        "patient_id": row["patient_id"],
        "created_at": row["created_at"],
        **json.loads(row["result_json"]),
    }


def get_latest_assessment(connection: sqlite3.Connection, patient_id: str) -> Dict[str, Any] | None:
    init_database(connection)
    row = connection.execute(
        """
        SELECT assessment_id, patient_id, created_at, result_json
        FROM assessments
        WHERE patient_id = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "assessment_id": row["assessment_id"],
        "patient_id": row["patient_id"],
        "created_at": row["created_at"],
        **json.loads(row["result_json"]),
    }


def get_latest_model_output(connection: sqlite3.Connection, patient_id: str) -> Dict[str, Any] | None:
    init_database(connection)
    row = connection.execute(
        """
        SELECT data_json FROM model_outputs
        WHERE patient_id = ?
        ORDER BY assessment_date DESC
        LIMIT 1
        """,
        (patient_id,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["data_json"])


def get_assessment_model_logs(
    connection: sqlite3.Connection, assessment_id: str
) -> List[Dict[str, Any]]:
    init_database(connection)
    rows = connection.execute(
        """
        SELECT node_name, called_at, input_data_version, model_name, model_version,
               provider, status, failure_reason, output_json
        FROM model_call_logs
        WHERE assessment_id = ?
        ORDER BY log_id
        """,
        (assessment_id,),
    ).fetchall()
    logs = []
    for row in rows:
        item = dict(row)
        item["output"] = json.loads(item.pop("output_json") or "{}")
        logs.append(item)
    return logs


def get_assessment_node_logs(
    connection: sqlite3.Connection, assessment_id: str
) -> List[Dict[str, Any]]:
    init_database(connection)
    rows = connection.execute(
        """
        SELECT node_name, started_at, ended_at, status, error_message
        FROM graph_node_logs
        WHERE assessment_id = ?
        ORDER BY log_id
        """,
        (assessment_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_report_by_assessment(
    connection: sqlite3.Connection, assessment_id: str
) -> Dict[str, Any] | None:
    init_database(connection)
    row = connection.execute(
        """
        SELECT report_id, assessment_id, patient_id, report_status, review_status,
               current_version, created_at, updated_at, confirmed_at, rejected_at,
               reviewer_name, review_comment
        FROM reports
        WHERE assessment_id = ?
        """,
        (assessment_id,),
    ).fetchone()
    return _report_from_row(connection, row) if row else None


def get_report(connection: sqlite3.Connection, report_id: int | str) -> Dict[str, Any] | None:
    init_database(connection)
    row = connection.execute(
        """
        SELECT report_id, assessment_id, patient_id, report_status, review_status,
               current_version, created_at, updated_at, confirmed_at, rejected_at,
               reviewer_name, review_comment
        FROM reports
        WHERE report_id = ?
        """,
        (report_id,),
    ).fetchone()
    return _report_from_row(connection, row) if row else None


def ensure_report_for_assessment(
    connection: sqlite3.Connection, assessment_id: str
) -> Dict[str, Any]:
    init_database(connection)
    assessment = get_assessment(connection, assessment_id)
    if assessment is None:
        raise KeyError(f"Unknown assessment_id: {assessment_id}")
    report = _ensure_report_for_assessment(
        connection,
        assessment_id,
        assessment["patient_id"],
        assessment,
    )
    connection.commit()
    return report


def save_report_version(
    connection: sqlite3.Connection,
    report_id: int | str,
    content: str,
    edited_by: str = "",
    change_summary: str = "",
) -> Dict[str, Any]:
    init_database(connection)
    report = get_report(connection, report_id)
    if report is None:
        raise KeyError(f"Unknown report_id: {report_id}")
    clean_content = (content or "").strip()
    if not clean_content:
        raise ValueError("报告内容不能为空")
    now = local_isoformat(timespec="seconds")
    next_version = int(report["current_version"]) + 1
    connection.execute(
        """
        INSERT INTO report_versions(
            report_id, version_number, content, edited_by, edited_at, change_summary
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            report_id,
            next_version,
            clean_content,
            (edited_by or "医生").strip(),
            now,
            (change_summary or "医生编辑报告内容").strip(),
        ),
    )
    connection.execute(
        """
        UPDATE reports
        SET current_version = ?, updated_at = ?, report_status = ?, review_status = ?,
            confirmed_at = NULL, rejected_at = NULL
        WHERE report_id = ?
        """,
        (next_version, now, "待复核", "待复核", report_id),
    )
    _insert_review_log(
        connection,
        report["assessment_id"],
        int(report_id),
        report["patient_id"],
        "edit",
        edited_by or "医生",
        change_summary or "医生编辑报告内容",
        now,
    )
    connection.commit()
    return get_report(connection, report_id) or {}


def review_assessment(
    connection: sqlite3.Connection,
    assessment_id: str,
    action: str,
    reviewer_name: str = "",
    review_comment: str = "",
) -> Dict[str, Any]:
    init_database(connection)
    assessment = get_assessment(connection, assessment_id)
    if assessment is None:
        raise KeyError(f"Unknown assessment_id: {assessment_id}")
    report = _ensure_report_for_assessment(
        connection,
        assessment_id,
        assessment["patient_id"],
        assessment,
    )
    if action == "confirm":
        return confirm_report(connection, report["report_id"], reviewer_name, review_comment)
    if action == "reject":
        return reject_report(connection, report["report_id"], reviewer_name, review_comment)
    if action == "save_comment":
        now = local_isoformat(timespec="seconds")
        connection.execute(
            """
            UPDATE reports
            SET reviewer_name = ?, review_comment = ?, updated_at = ?
            WHERE report_id = ?
            """,
            (
                (reviewer_name or "医生").strip(),
                (review_comment or "").strip(),
                now,
                report["report_id"],
            ),
        )
        _insert_review_log(
            connection,
            assessment_id,
            report["report_id"],
            assessment["patient_id"],
            "save_comment",
            reviewer_name or "医生",
            review_comment,
            now,
        )
        connection.commit()
        return get_report(connection, report["report_id"]) or {}
    raise ValueError("Unsupported review action")


def confirm_report(
    connection: sqlite3.Connection,
    report_id: int | str,
    reviewer_name: str = "",
    review_comment: str = "",
) -> Dict[str, Any]:
    init_database(connection)
    report = get_report(connection, report_id)
    if report is None:
        raise KeyError(f"Unknown report_id: {report_id}")
    now = local_isoformat(timespec="seconds")
    reviewer = (reviewer_name or "医生").strip()
    comment = (review_comment or "").strip()
    connection.execute(
        """
        UPDATE reports
        SET report_status = ?, review_status = ?, reviewer_name = ?, review_comment = ?,
            confirmed_at = ?, rejected_at = NULL, updated_at = ?
        WHERE report_id = ?
        """,
        ("已确认", "已确认", reviewer, comment, now, now, report_id),
    )
    _insert_review_log(
        connection,
        report["assessment_id"],
        int(report_id),
        report["patient_id"],
        "confirm",
        reviewer,
        comment,
        now,
    )
    connection.commit()
    return get_report(connection, report_id) or {}


def reject_report(
    connection: sqlite3.Connection,
    report_id: int | str,
    reviewer_name: str = "",
    review_comment: str = "",
) -> Dict[str, Any]:
    init_database(connection)
    report = get_report(connection, report_id)
    if report is None:
        raise KeyError(f"Unknown report_id: {report_id}")
    comment = (review_comment or "").strip()
    if not comment:
        raise ValueError("驳回报告必须填写原因")
    now = local_isoformat(timespec="seconds")
    reviewer = (reviewer_name or "医生").strip()
    connection.execute(
        """
        UPDATE reports
        SET report_status = ?, review_status = ?, reviewer_name = ?, review_comment = ?,
            rejected_at = ?, confirmed_at = NULL, updated_at = ?
        WHERE report_id = ?
        """,
        ("已驳回", "已驳回", reviewer, comment, now, now, report_id),
    )
    _insert_review_log(
        connection,
        report["assessment_id"],
        int(report_id),
        report["patient_id"],
        "reject",
        reviewer,
        comment,
        now,
    )
    connection.commit()
    return get_report(connection, report_id) or {}


def list_import_batches(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    init_database(connection)
    rows = connection.execute(
        """
        SELECT batch_id, file_name, imported_at, status, counts_json
        FROM import_batches
        ORDER BY batch_id DESC
        """
    ).fetchall()
    return [_import_batch_from_row(row, include_issues=False) for row in rows]


def get_import_batch(connection: sqlite3.Connection, batch_id: int) -> Dict[str, Any] | None:
    init_database(connection)
    row = connection.execute(
        """
        SELECT batch_id, file_name, imported_at, status, counts_json
        FROM import_batches
        WHERE batch_id = ?
        """,
        (batch_id,),
    ).fetchone()
    if row is None:
        return None
    batch = _import_batch_from_row(row, include_issues=False)
    issue_rows = connection.execute(
        """
        SELECT sheet_name, row_number, field_name, severity, message
        FROM import_issues
        WHERE batch_id = ?
        ORDER BY issue_id
        """,
        (batch_id,),
    ).fetchall()
    batch["issues"] = [dict(issue) for issue in issue_rows]
    batch["errors"] = [issue for issue in batch["issues"] if issue["severity"] == "error"]
    batch["warnings"] = [issue for issue in batch["issues"] if issue["severity"] == "warning"]
    return batch


def _load_many(
    connection: sqlite3.Connection, table_name: str, patient_id: str, order_field: str
) -> List[Dict[str, Any]]:
    rows = connection.execute(
        f"SELECT data_json FROM {table_name} WHERE patient_id = ? ORDER BY {order_field}",
        (patient_id,),
    ).fetchall()
    return [json.loads(row["data_json"]) for row in rows]


def _sheet(workbook: WorkbookData, name: str) -> List[Dict[str, Any]]:
    return workbook.sheets.get(name) or workbook.sheets.get(name.lower()) or []


def _ensure_column(
    connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str
) -> None:
    existing = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in existing:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _create_import_batch(connection: sqlite3.Connection, file_name: str, imported_at: str) -> int:
    cursor = connection.execute(
        """
        INSERT INTO import_batches(file_name, imported_at, status, counts_json)
        VALUES (?, ?, ?, ?)
        """,
        (file_name or "uploaded.xlsx", imported_at, "running", "{}"),
    )
    return int(cursor.lastrowid)


def _update_import_batch(
    connection: sqlite3.Connection, batch_id: int, status: str, counts: Dict[str, Any]
) -> None:
    connection.execute(
        """
        UPDATE import_batches
        SET status = ?, counts_json = ?
        WHERE batch_id = ?
        """,
        (status, json.dumps(counts, ensure_ascii=False), batch_id),
    )


def _save_import_issues(
    connection: sqlite3.Connection, batch_id: int, issues: List[Dict[str, Any]]
) -> None:
    for issue in issues:
        connection.execute(
            """
            INSERT INTO import_issues(batch_id, sheet_name, row_number, field_name, severity, message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                issue.get("sheet_name", ""),
                issue.get("row_number"),
                issue.get("field_name", ""),
                issue.get("severity", "warning"),
                issue.get("message", ""),
            ),
        )


def _import_batch_from_row(row: sqlite3.Row, include_issues: bool = False) -> Dict[str, Any]:
    batch = {
        "batch_id": row["batch_id"],
        "file_name": row["file_name"],
        "imported_at": row["imported_at"],
        "status": row["status"],
        "counts": json.loads(row["counts_json"] or "{}"),
    }
    if include_issues:
        batch["issues"] = []
    return batch


def _validate_template_workbook(
    connection: sqlite3.Connection, workbook: WorkbookData
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    patients = _sheet(workbook, "patients")
    patient_ids = [str(row.get("patient_id", "")).strip() for row in patients]
    valid_patient_ids = {patient_id for patient_id in patient_ids if patient_id}

    if not patients:
        issues.append(_issue("patients", None, "patient_id", "error", "patients sheet 不能为空"))

    seen: set[str] = set()
    for row_number, patient_id in enumerate(patient_ids, start=2):
        if not patient_id:
            continue
        if patient_id in seen:
            issues.append(
                _issue("patients", row_number, "patient_id", "error", f"同一次导入内患者ID重复：{patient_id}")
            )
        seen.add(patient_id)

    existing = _existing_patient_ids(connection, valid_patient_ids)
    for patient_id in sorted(existing):
        issues.append(
            _issue("patients", None, "patient_id", "warning", f"患者 {patient_id} 已存在，本次导入将覆盖/更新该患者数据")
        )

    for sheet_name, required_fields in TEMPLATE_REQUIRED_FIELDS.items():
        rows = _sheet(workbook, sheet_name)
        for row_number, row in enumerate(rows, start=2):
            for field_name in required_fields:
                if _blank(row.get(field_name)):
                    issues.append(
                        _issue(sheet_name, row_number, field_name, "error", f"{field_name} 为必填字段")
                    )
            if sheet_name != "patients":
                patient_id = str(row.get("patient_id", "")).strip()
                if patient_id and patient_id not in valid_patient_ids:
                    issues.append(
                        _issue(sheet_name, row_number, "patient_id", "error", f"患者ID {patient_id} 不存在于 patients sheet")
                    )

    for sheet_name, fields in TEMPLATE_DATE_FIELDS.items():
        for row_number, row in enumerate(_sheet(workbook, sheet_name), start=2):
            for field_name in fields:
                value = row.get(field_name)
                if not _blank(value) and not _valid_date(value):
                    issues.append(
                        _issue(sheet_name, row_number, field_name, "error", f"{field_name} 日期格式应为 YYYY-MM-DD")
                    )

    for sheet_name, fields in TEMPLATE_NUMERIC_RANGES.items():
        for row_number, row in enumerate(_sheet(workbook, sheet_name), start=2):
            for field_name, limits in fields.items():
                value = row.get(field_name)
                if _blank(value):
                    continue
                number = _number(value)
                if number is None:
                    issues.append(
                        _issue(sheet_name, row_number, field_name, "error", f"{field_name} 应为数值")
                    )
                    continue
                lower, upper = limits
                if number < lower or number > upper:
                    issues.append(
                        _issue(sheet_name, row_number, field_name, "error", f"{field_name} 数值超出合理范围 {lower}-{upper}")
                    )

    return issues


def _validate_legacy_workbook(workbook: WorkbookData) -> List[Dict[str, Any]]:
    issues = [
        _issue("Workbook", None, "", "warning", "当前导入的是旧 mock 表格格式，仅作为兼容输入；正式演示请使用固定模板")
    ]
    patients = _sheet(workbook, "Patients")
    if not patients:
        issues.append(_issue("Patients", None, "patient_id", "error", "Patients sheet 不能为空"))
    patient_ids = set()
    for row_number, row in enumerate(patients, start=2):
        patient_id = str(row.get("patient_id", "")).strip()
        if not patient_id:
            issues.append(_issue("Patients", row_number, "patient_id", "error", "patient_id 为必填字段"))
            continue
        if patient_id in patient_ids:
            issues.append(_issue("Patients", row_number, "patient_id", "error", f"同一次导入内患者ID重复：{patient_id}"))
        patient_ids.add(patient_id)

    legacy_dates = {
        "Visits": "event_date",
        "Labs": "sample_date",
        "ModelOutputs": "assessment_date",
    }
    for sheet_name, date_field in legacy_dates.items():
        for row_number, row in enumerate(_sheet(workbook, sheet_name), start=2):
            patient_id = str(row.get("patient_id", "")).strip()
            if patient_id and patient_id not in patient_ids:
                issues.append(_issue(sheet_name, row_number, "patient_id", "error", f"患者ID {patient_id} 不存在于 Patients sheet"))
            value = row.get(date_field)
            if not _blank(value) and not _valid_date(value):
                issues.append(_issue(sheet_name, row_number, date_field, "error", f"{date_field} 日期格式应为 YYYY-MM-DD"))
    return issues


def _existing_patient_ids(connection: sqlite3.Connection, patient_ids: set[str]) -> set[str]:
    if not patient_ids:
        return set()
    existing = set()
    for patient_id in patient_ids:
        row = connection.execute(
            "SELECT patient_id FROM patients WHERE patient_id = ?", (patient_id,)
        ).fetchone()
        if row:
            existing.add(patient_id)
    return existing


def _issue(
    sheet_name: str,
    row_number: int | None,
    field_name: str,
    severity: str,
    message: str,
) -> Dict[str, Any]:
    return {
        "sheet_name": sheet_name,
        "row_number": row_number,
        "field_name": field_name,
        "severity": severity,
        "message": message,
    }


def _blank(value: Any) -> bool:
    return value in ("", None)


def _valid_date(value: Any) -> bool:
    text = _as_text(value)
    if not text:
        return True
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _import_template_workbook(
    connection: sqlite3.Connection, workbook: WorkbookData, imported_at: str, batch_id: int
) -> Dict[str, int]:
    patients = _sheet(workbook, "patients")
    _validate_required_patients(patients)

    smoking_by_patient = _one_by_patient(_sheet(workbook, "smoking_history"))
    comorbidity_by_patient = _one_by_patient(_sheet(workbook, "comorbidities"))
    symptoms_by_patient = _many_by_patient(_sheet(workbook, "symptom_scores"))
    pulmonary_by_patient = _many_by_patient(_sheet(workbook, "pulmonary_tests"))
    labs_by_patient = _many_by_patient(_sheet(workbook, "lab_results"))
    pathogens_by_patient = _many_by_patient(_sheet(workbook, "pathogen_results"))
    cts_by_patient = _many_by_patient(_sheet(workbook, "ct_features"))
    meds_by_patient = _many_by_patient(_sheet(workbook, "medications"))
    exacerbations_by_patient = _many_by_patient(_sheet(workbook, "exacerbations"))
    followups_by_patient = _many_by_patient(_sheet(workbook, "followups"))

    visit_rows: List[Dict[str, Any]] = []
    lab_rows: List[Dict[str, Any]] = []

    for patient in patients:
        patient_id = str(patient["patient_id"])
        latest_symptom = _latest_by_date(symptoms_by_patient.get(patient_id, []), "assessment_date")
        latest_pulmonary = _latest_by_date(pulmonary_by_patient.get(patient_id, []), "test_date")
        latest_lab = _latest_by_date(labs_by_patient.get(patient_id, []), "lab_date")
        latest_pathogen = _latest_by_date(pathogens_by_patient.get(patient_id, []), "pathogen_test_date")
        latest_ct = _latest_by_date(cts_by_patient.get(patient_id, []), "ct_date")
        latest_med = _latest_by_date(meds_by_patient.get(patient_id, []), "start_date")
        latest_followup = _latest_by_date(followups_by_patient.get(patient_id, []), "followup_date")
        exacerbation_rows = exacerbations_by_patient.get(patient_id, [])
        comorbidity = comorbidity_by_patient.get(patient_id, {})
        smoking = smoking_by_patient.get(patient_id, {})

        normalized_patient = {
            **patient,
            "sex": patient.get("gender", patient.get("sex", "")),
            "smoking_pack_years": smoking.get("pack_years", ""),
            "comorbidity": _comorbidity_text(comorbidity),
            "CAT_score": latest_symptom.get("cat_score", ""),
            "mMRC_score": latest_symptom.get("mmrc_score", ""),
            "FEV1_L": latest_pulmonary.get("fev1_l", ""),
            "FVC_L": latest_pulmonary.get("fvc_l", ""),
            "FEV1_FVC": latest_pulmonary.get("fev1_fvc_ratio", ""),
            "FEV1_percent_predicted": latest_pulmonary.get("fev1_percent_predicted", ""),
            "FeNO_ppb": latest_pulmonary.get("feno", latest_lab.get("feno", "")),
            "eosinophil_109L": latest_lab.get("eosinophil_count", ""),
            "CRP_mgL": latest_lab.get("crp", ""),
            "pathogen_result": latest_pathogen.get("detected_pathogens", "未检出"),
            "current_medication": latest_med.get("medication_name", ""),
            "ct_feature_emphysema_pct": latest_ct.get("emphysema_percent", ""),
            "ct_feature_airway_wall_thickening": latest_ct.get("airway_wall_thickening", ""),
            "ct_report_summary": latest_ct.get("ct_report_text", latest_ct.get("ct_summary", "")),
            "exacerbation_count_1y": len(exacerbation_rows),
            "readmission_90d": latest_followup.get("rehospitalization", "否"),
            "survival_status": latest_followup.get("survival_status", ""),
            "last_followup_date": latest_followup.get("followup_date", ""),
        }
        connection.execute(
            """
            INSERT INTO patients(patient_id, data_json, imported_at, import_batch_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(patient_id) DO UPDATE SET
                data_json = excluded.data_json,
                imported_at = excluded.imported_at,
                import_batch_id = excluded.import_batch_id
            """,
            (patient_id, json.dumps(normalized_patient, ensure_ascii=False), imported_at, batch_id),
        )

        visit_rows.extend(_template_timeline_rows(patient_id, symptoms_by_patient.get(patient_id, []), "symptom_id", "assessment_date", "症状评分", _symptom_detail))
        visit_rows.extend(_template_timeline_rows(patient_id, pulmonary_by_patient.get(patient_id, []), "pulmonary_test_id", "test_date", "肺功能检查", _pulmonary_detail))
        visit_rows.extend(_template_timeline_rows(patient_id, labs_by_patient.get(patient_id, []), "lab_id", "lab_date", "实验室检验", _lab_detail))
        visit_rows.extend(_template_timeline_rows(patient_id, pathogens_by_patient.get(patient_id, []), "pathogen_id", "pathogen_test_date", "病原学检测", _pathogen_detail))
        visit_rows.extend(_template_timeline_rows(patient_id, cts_by_patient.get(patient_id, []), "ct_id", "ct_date", "CT检查", _ct_detail))
        visit_rows.extend(_template_timeline_rows(patient_id, meds_by_patient.get(patient_id, []), "medication_id", "start_date", "用药记录", _medication_detail))
        visit_rows.extend(_template_timeline_rows(patient_id, exacerbation_rows, "exacerbation_id", "exacerbation_date", "急性加重", _exacerbation_detail))
        visit_rows.extend(_template_timeline_rows(patient_id, followups_by_patient.get(patient_id, []), "followup_id", "followup_date", "随访", _followup_detail))

        for row in labs_by_patient.get(patient_id, []):
            lab_rows.append(
                {
                    "lab_id": row.get("lab_id"),
                    "patient_id": patient_id,
                    "sample_date": row.get("lab_date", ""),
                    "WBC_109L": row.get("wbc", ""),
                    "neutrophil_pct": row.get("neutrophil_percent", ""),
                    "eosinophil_109L": row.get("eosinophil_count", ""),
                    "CRP_mgL": row.get("crp", ""),
                    "PCT_ngmL": row.get("pct", ""),
                    "FeNO_ppb": latest_pulmonary.get("feno", ""),
                    "pathogen_result": latest_pathogen.get("detected_pathogens", "未检出"),
                }
            )

    _upsert_visits(connection, visit_rows, batch_id)
    _upsert_labs(connection, lab_rows, batch_id)
    return {
        "patients": len(patients),
        "visits": len(visit_rows),
        "labs": len(lab_rows),
        "model_outputs": 0,
        "template_format": 1,
    }


def _upsert_visits(connection: sqlite3.Connection, rows: List[Dict[str, Any]], batch_id: int) -> None:
    for row in rows:
        if not row.get("patient_id"):
            continue
        event_id = str(row.get("event_id") or f"{row.get('patient_id')}-{row.get('event_date')}-{row.get('event_type')}")
        connection.execute(
            """
            INSERT INTO visits(event_id, patient_id, event_date, data_json, import_batch_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                patient_id = excluded.patient_id,
                event_date = excluded.event_date,
                data_json = excluded.data_json,
                import_batch_id = excluded.import_batch_id
            """,
            (
                event_id,
                str(row["patient_id"]),
                _as_text(row.get("event_date")),
                json.dumps(row, ensure_ascii=False),
                batch_id,
            ),
        )


def _upsert_labs(connection: sqlite3.Connection, rows: List[Dict[str, Any]], batch_id: int) -> None:
    for row in rows:
        if not row.get("patient_id"):
            continue
        lab_id = str(row.get("lab_id") or f"{row.get('patient_id')}-{row.get('sample_date')}")
        connection.execute(
            """
            INSERT INTO labs(lab_id, patient_id, sample_date, data_json, import_batch_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(lab_id) DO UPDATE SET
                patient_id = excluded.patient_id,
                sample_date = excluded.sample_date,
                data_json = excluded.data_json,
                import_batch_id = excluded.import_batch_id
            """,
            (
                lab_id,
                str(row["patient_id"]),
                _as_text(row.get("sample_date")),
                json.dumps(row, ensure_ascii=False),
                batch_id,
            ),
        )


def _one_by_patient(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    grouped = {}
    for row in rows:
        patient_id = str(row.get("patient_id", ""))
        if patient_id:
            grouped[patient_id] = row
    return grouped


def _many_by_patient(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        patient_id = str(row.get("patient_id", ""))
        if patient_id:
            grouped.setdefault(patient_id, []).append(row)
    return grouped


def _latest_by_date(rows: List[Dict[str, Any]], date_field: str) -> Dict[str, Any]:
    if not rows:
        return {}
    return sorted(rows, key=lambda item: _as_text(item.get(date_field)))[-1]


def _template_timeline_rows(
    patient_id: str,
    rows: List[Dict[str, Any]],
    id_field: str,
    date_field: str,
    event_type: str,
    detail_builder,
) -> List[Dict[str, Any]]:
    events = []
    for index, row in enumerate(rows, start=1):
        event_id = row.get(id_field) or f"{patient_id}-{event_type}-{index}"
        events.append(
            {
                "event_id": str(event_id),
                "patient_id": patient_id,
                "event_date": _as_text(row.get(date_field)),
                "event_type": event_type,
                "event_detail": detail_builder(row),
                "severity": row.get("severity", ""),
            }
        )
    return events


def _comorbidity_text(row: Dict[str, Any]) -> str:
    labels = [
        ("hypertension", "高血压"),
        ("diabetes", "糖尿病"),
        ("coronary_disease", "冠心病"),
        ("bronchiectasis", "支气管扩张"),
        ("asthma", "哮喘"),
    ]
    values = [label for field, label in labels if _yes(row.get(field))]
    if row.get("other_comorbidities"):
        values.append(str(row["other_comorbidities"]))
    return ";".join(values)


def _symptom_detail(row: Dict[str, Any]) -> str:
    return f"CAT {row.get('cat_score', '未知')}，mMRC {row.get('mmrc_score', '未知')}，气促：{row.get('dyspnea', '未记录')}"


def _pulmonary_detail(row: Dict[str, Any]) -> str:
    return (
        f"FEV1 {row.get('fev1_l', '未知')}L，FVC {row.get('fvc_l', '未知')}L，"
        f"FEV1/FVC {row.get('fev1_fvc_ratio', '未知')}，FEV1占预计值{row.get('fev1_percent_predicted', '未知')}%"
    )


def _lab_detail(row: Dict[str, Any]) -> str:
    return f"WBC {row.get('wbc', '未知')}，CRP {row.get('crp', '未知')}，PCT {row.get('pct', '未知')}"


def _pathogen_detail(row: Dict[str, Any]) -> str:
    return f"{row.get('test_method', '病原学检测')}提示：{row.get('detected_pathogens', '未检出')}，临床相关性：{row.get('clinical_relevance', '待医生判断')}"


def _ct_detail(row: Dict[str, Any]) -> str:
    report = row.get("ct_report_text") or row.get("ct_summary") or "CT信息未记录"
    return f"{report}；肺气肿比例{row.get('emphysema_percent', '未知')}%"


def _medication_detail(row: Dict[str, Any]) -> str:
    return f"{row.get('medication_name', '未记录')}（{row.get('medication_type', '类别不详')}），{row.get('medication_note', '')}"


def _exacerbation_detail(row: Dict[str, Any]) -> str:
    return f"{row.get('severity', '严重程度不详')}急性加重，住院：{row.get('hospitalization', '未知')}，诱因：{row.get('trigger_factor', '未记录')}"


def _followup_detail(row: Dict[str, Any]) -> str:
    return f"症状变化：{row.get('symptom_change', '未记录')}，再入院：{row.get('rehospitalization', '未知')}，生存状态：{row.get('survival_status', '未记录')}"


def _validate_required_patients(patients: Iterable[Dict[str, Any]]) -> None:
    for index, row in enumerate(patients, start=2):
        if not row.get("patient_id"):
            raise ValueError(f"Patients sheet row {index} missing patient_id")


def _longitudinal_records(
    connection: sqlite3.Connection, patient_id: str
) -> Dict[str, List[Dict[str, Any]]]:
    visits = _load_many(connection, "visits", patient_id, "event_date")
    groups = {
        "symptoms": [],
        "pulmonary_tests": [],
        "lab_events": [],
        "pathogen_tests": [],
        "ct_records": [],
        "medications": [],
        "exacerbations": [],
        "followups": [],
        "other_events": [],
    }
    mapping = {
        "症状评分": "symptoms",
        "肺功能检查": "pulmonary_tests",
        "实验室检验": "lab_events",
        "病原学检测": "pathogen_tests",
        "CT检查": "ct_records",
        "用药记录": "medications",
        "急性加重": "exacerbations",
        "随访": "followups",
    }
    for visit in visits:
        key = mapping.get(visit.get("event_type"), "other_events")
        groups[key].append(visit)
    groups["labs"] = _load_many(connection, "labs", patient_id, "sample_date")
    return groups


def _followup_status(patient: Dict[str, Any]) -> str:
    if not patient.get("last_followup_date"):
        return "未随访"
    if str(patient.get("survival_status", "")).strip() == "失访":
        return "失访"
    return "已随访"


def _save_model_call_logs(
    connection: sqlite3.Connection,
    assessment_id: str,
    patient_id: str,
    called_at: str,
    result: Dict[str, Any],
) -> None:
    input_data_version = (
        result.get("patient_data", {}).get("data_version")
        or result.get("raw_patient_data", {}).get("data_version")
        or result.get("model_metadata", {}).get("input_data_version", "")
    )
    for node_name, log in result.get("model_call_results", {}).items():
        connection.execute(
            """
            INSERT INTO model_call_logs(
                assessment_id, patient_id, node_name, called_at, input_data_version,
                model_name, model_version, provider, status, failure_reason, output_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assessment_id,
                patient_id,
                node_name,
                called_at,
                input_data_version,
                log.get("model_name", ""),
                log.get("model_version", ""),
                log.get("provider", ""),
                log.get("status", ""),
                log.get("failure_reason", ""),
                json.dumps(log.get("output", {}), ensure_ascii=False),
            ),
        )


def _save_node_run_logs(
    connection: sqlite3.Connection,
    assessment_id: str,
    patient_id: str,
    result: Dict[str, Any],
) -> None:
    for log in result.get("node_run_logs", []):
        connection.execute(
            """
            INSERT INTO graph_node_logs(
                assessment_id, patient_id, node_name, started_at, ended_at, status, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assessment_id,
                patient_id,
                log.get("node_name", ""),
                log.get("started_at", ""),
                log.get("ended_at", ""),
                log.get("status", ""),
                log.get("error_message", ""),
            ),
        )


def _ensure_report_for_assessment(
    connection: sqlite3.Connection,
    assessment_id: str,
    patient_id: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    existing = get_report_by_assessment(connection, assessment_id)
    if existing:
        return existing
    now = local_isoformat(timespec="seconds")
    content = (result.get("report_draft") or "").strip() or _structured_report_text(result)
    cursor = connection.execute(
        """
        INSERT INTO reports(
            assessment_id, patient_id, report_status, review_status, current_version,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (assessment_id, patient_id, "待复核", "待复核", 1, now, now),
    )
    report_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO report_versions(
            report_id, version_number, content, edited_by, edited_at, change_summary
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (report_id, 1, content, "系统", now, "由智能评估结果自动生成初始报告"),
    )
    _insert_review_log(
        connection,
        assessment_id,
        report_id,
        patient_id,
        "create",
        "系统",
        "生成待复核报告",
        now,
    )
    return get_report(connection, report_id) or {}


def _report_from_row(connection: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    report = dict(row)
    versions = _report_versions(connection, report["report_id"])
    logs = _report_review_logs(connection, report["report_id"])
    current = next(
        (
            version
            for version in versions
            if int(version["version_number"]) == int(report["current_version"])
        ),
        versions[-1] if versions else {},
    )
    report["versions"] = versions
    report["review_logs"] = logs
    report["current_content"] = current.get("content", "")
    report["current_version_id"] = current.get("version_id")
    return report


def _report_versions(connection: sqlite3.Connection, report_id: int | str) -> List[Dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT version_id, report_id, version_number, content, edited_by, edited_at, change_summary
        FROM report_versions
        WHERE report_id = ?
        ORDER BY version_number
        """,
        (report_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _report_review_logs(connection: sqlite3.Connection, report_id: int | str) -> List[Dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT log_id, assessment_id, report_id, patient_id, action, reviewer_name,
               review_comment, created_at
        FROM review_logs
        WHERE report_id = ?
        ORDER BY log_id
        """,
        (report_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _insert_review_log(
    connection: sqlite3.Connection,
    assessment_id: str,
    report_id: int | None,
    patient_id: str,
    action: str,
    reviewer_name: str,
    review_comment: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO review_logs(
            assessment_id, report_id, patient_id, action, reviewer_name, review_comment, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            assessment_id,
            report_id,
            patient_id,
            action,
            reviewer_name,
            review_comment,
            created_at,
        ),
    )


def _structured_report_text(result: Dict[str, Any]) -> str:
    phenotype = result.get("phenotype", {})
    risks = result.get("risk_assessment", {})
    evidence = result.get("key_evidence", [])
    evidence_lines = [
        f"- {item.get('evidence', '')}（来源：{item.get('source', '')}）"
        for item in evidence
    ]
    return "\n".join(
        [
            "# 慢阻肺智能辅助评估报告草稿",
            "",
            "## 病程摘要",
            str(result.get("patient_timeline_summary", "")),
            "",
            "## 当前状态",
            str(result.get("patient_current_summary", "")),
            "",
            "## 表型提示",
            f"主要表型：{phenotype.get('main_phenotype', '')}",
            f"相关标签：{'、'.join(phenotype.get('phenotype_tags', []))}",
            f"依据说明：{phenotype.get('basis', '')}",
            "",
            "## 风险评估",
            f"急性加重风险：{risks.get('acute_exacerbation_risk', '')}",
            f"再住院风险：{risks.get('readmission_risk', '')}",
            f"死亡风险：{risks.get('mortality_risk', '')}",
            "",
            "## 关键证据",
            "\n".join(evidence_lines),
            "",
            "## 辅助评估免责声明",
            "本报告仅作为辅助评估草稿，不替代医生临床判断，不作为独立诊疗依据，不提供具体治疗方案。",
        ]
    )


def _data_version(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _pathogen_rows(patient: Dict[str, Any], labs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    patient_pathogen = patient.get("pathogen_result")
    if patient_pathogen and str(patient_pathogen) != "未检出":
        rows.append(_pathogen_test(patient.get("last_followup_date"), patient_pathogen))
    for lab in labs:
        value = lab.get("pathogen_result")
        if value and str(value) != "未检出":
            rows.append(_pathogen_test(lab.get("sample_date"), value))
    return rows


def _pathogen_test(date: Any, value: Any) -> Dict[str, Any]:
    return {
        "date": _as_text(date) or "日期不详",
        "sample_type": "未注明样本",
        "method": "病原学检测",
        "mNGS_result": [{"pathogen": item} for item in _split_text(str(value))],
    }


def _latest_value(rows: List[Dict[str, Any]], field: str, default: Any = None) -> Any:
    for row in reversed(rows):
        value = row.get(field)
        if value not in ("", None):
            return value
    return default


def _split_text(value: Any) -> List[str]:
    if value in ("", None):
        return []
    return [item.strip() for item in str(value).replace("；", ";").split(";") if item.strip()]


def _yes(value: Any) -> bool:
    return str(value).strip() in {"是", "true", "True", "1", "Y", "yes"}


def _as_text(value: Any) -> str:
    if value in ("", None):
        return ""
    return str(value)
