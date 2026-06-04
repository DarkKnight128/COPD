from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from copd_graph.xlsx_importer import WorkbookData


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "poc_demo_v2.sqlite"


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
        """
    )
    connection.commit()


def import_workbook(connection: sqlite3.Connection, workbook: WorkbookData) -> Dict[str, int]:
    init_database(connection)
    now = datetime.utcnow().isoformat(timespec="seconds")
    if _sheet(workbook, "patients"):
        return _import_template_workbook(connection, workbook, now)

    patients = _sheet(workbook, "Patients")
    visits = _sheet(workbook, "Visits")
    labs = _sheet(workbook, "Labs")
    model_outputs = _sheet(workbook, "ModelOutputs")

    _validate_required_patients(patients)

    for row in patients:
        connection.execute(
            """
            INSERT INTO patients(patient_id, data_json, imported_at)
            VALUES (?, ?, ?)
            ON CONFLICT(patient_id) DO UPDATE SET
                data_json = excluded.data_json,
                imported_at = excluded.imported_at
            """,
            (str(row["patient_id"]), json.dumps(row, ensure_ascii=False), now),
        )

    for row in visits:
        if not row.get("patient_id"):
            continue
        event_id = str(row.get("event_id") or f"{row.get('patient_id')}-{row.get('event_date')}")
        connection.execute(
            """
            INSERT INTO visits(event_id, patient_id, event_date, data_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                patient_id = excluded.patient_id,
                event_date = excluded.event_date,
                data_json = excluded.data_json
            """,
            (
                event_id,
                str(row["patient_id"]),
                _as_text(row.get("event_date")),
                json.dumps(row, ensure_ascii=False),
            ),
        )

    for row in labs:
        if not row.get("patient_id"):
            continue
        lab_id = str(row.get("lab_id") or f"{row.get('patient_id')}-{row.get('sample_date')}")
        connection.execute(
            """
            INSERT INTO labs(lab_id, patient_id, sample_date, data_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(lab_id) DO UPDATE SET
                patient_id = excluded.patient_id,
                sample_date = excluded.sample_date,
                data_json = excluded.data_json
            """,
            (
                lab_id,
                str(row["patient_id"]),
                _as_text(row.get("sample_date")),
                json.dumps(row, ensure_ascii=False),
            ),
        )

    for row in model_outputs:
        if not row.get("patient_id"):
            continue
        assessment_id = str(row.get("assessment_id") or f"mock-{row.get('patient_id')}")
        connection.execute(
            """
            INSERT INTO model_outputs(assessment_id, patient_id, assessment_date, data_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(assessment_id) DO UPDATE SET
                patient_id = excluded.patient_id,
                assessment_date = excluded.assessment_date,
                data_json = excluded.data_json
            """,
            (
                assessment_id,
                str(row["patient_id"]),
                _as_text(row.get("assessment_date")),
                json.dumps(row, ensure_ascii=False),
            ),
        )

    connection.commit()
    return {
        "patients": len(patients),
        "visits": len(visits),
        "labs": len(labs),
        "model_outputs": len(model_outputs),
    }


def list_patients(connection: sqlite3.Connection, query: str = "") -> List[Dict[str, Any]]:
    init_database(connection)
    rows = connection.execute("SELECT patient_id, data_json FROM patients ORDER BY patient_id").fetchall()
    patients = []
    for row in rows:
        patient = json.loads(row["data_json"])
        patient_id = str(patient.get("patient_id", ""))
        if query and query.lower() not in patient_id.lower():
            continue
        model_output = get_latest_model_output(connection, patient_id)
        latest_assessment = get_latest_assessment(connection, patient_id)
        patients.append(
            {
                "patient_id": patient_id,
                "sex": patient.get("sex", patient.get("gender", "")),
                "age": patient.get("age", ""),
                "cat_score": patient.get("CAT_score", patient.get("cat_score", "")),
                "mmrc_score": patient.get("mMRC_score", patient.get("mmrc_score", "")),
                "risk_level": (model_output or {}).get("exacerbation_risk_level", "未评估"),
                "assessment_status": "已评估" if latest_assessment else "未评估",
                "latest_assessment_id": (latest_assessment or {}).get("assessment_id"),
            }
        )
    return patients


def get_patient_bundle(connection: sqlite3.Connection, patient_id: str) -> Dict[str, Any] | None:
    init_database(connection)
    row = connection.execute(
        "SELECT data_json FROM patients WHERE patient_id = ?", (patient_id,)
    ).fetchone()
    if row is None:
        return None
    return {
        "patient": json.loads(row["data_json"]),
        "visits": _load_many(connection, "visits", patient_id, "event_date"),
        "labs": _load_many(connection, "labs", patient_id, "sample_date"),
        "model_output": get_latest_model_output(connection, patient_id),
        "latest_assessment": get_latest_assessment(connection, patient_id),
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

    return {
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


def save_assessment(
    connection: sqlite3.Connection, patient_id: str, result: Dict[str, Any]
) -> Dict[str, Any]:
    init_database(connection)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    assessment_id = f"POC-{patient_id}-{timestamp}"
    connection.execute(
        """
        INSERT INTO assessments(assessment_id, patient_id, created_at, result_json)
        VALUES (?, ?, ?, ?)
        """,
        (
            assessment_id,
            patient_id,
            datetime.utcnow().isoformat(timespec="seconds"),
            json.dumps(result, ensure_ascii=False),
        ),
    )
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


def _import_template_workbook(
    connection: sqlite3.Connection, workbook: WorkbookData, imported_at: str
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
            INSERT INTO patients(patient_id, data_json, imported_at)
            VALUES (?, ?, ?)
            ON CONFLICT(patient_id) DO UPDATE SET
                data_json = excluded.data_json,
                imported_at = excluded.imported_at
            """,
            (patient_id, json.dumps(normalized_patient, ensure_ascii=False), imported_at),
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

    _upsert_visits(connection, visit_rows)
    _upsert_labs(connection, lab_rows)
    connection.commit()
    return {
        "patients": len(patients),
        "visits": len(visit_rows),
        "labs": len(lab_rows),
        "model_outputs": 0,
        "template_format": 1,
    }


def _upsert_visits(connection: sqlite3.Connection, rows: List[Dict[str, Any]]) -> None:
    for row in rows:
        if not row.get("patient_id"):
            continue
        event_id = str(row.get("event_id") or f"{row.get('patient_id')}-{row.get('event_date')}-{row.get('event_type')}")
        connection.execute(
            """
            INSERT INTO visits(event_id, patient_id, event_date, data_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                patient_id = excluded.patient_id,
                event_date = excluded.event_date,
                data_json = excluded.data_json
            """,
            (
                event_id,
                str(row["patient_id"]),
                _as_text(row.get("event_date")),
                json.dumps(row, ensure_ascii=False),
            ),
        )


def _upsert_labs(connection: sqlite3.Connection, rows: List[Dict[str, Any]]) -> None:
    for row in rows:
        if not row.get("patient_id"):
            continue
        lab_id = str(row.get("lab_id") or f"{row.get('patient_id')}-{row.get('sample_date')}")
        connection.execute(
            """
            INSERT INTO labs(lab_id, patient_id, sample_date, data_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(lab_id) DO UPDATE SET
                patient_id = excluded.patient_id,
                sample_date = excluded.sample_date,
                data_json = excluded.data_json
            """,
            (
                lab_id,
                str(row["patient_id"]),
                _as_text(row.get("sample_date")),
                json.dumps(row, ensure_ascii=False),
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
