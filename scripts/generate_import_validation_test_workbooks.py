from __future__ import annotations

from pathlib import Path

from generate_import_template import README_ROWS, SHEETS, field_dictionary_rows, write_xlsx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "import_validation_tests"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for file_name, rows_by_sheet in build_cases().items():
        worksheets = {
            "README": README_ROWS
            + [
                ["测试说明", "本文件故意包含错误数据，用于手动测试导入校验。"],
                ["预期结果", "系统应导入失败，并在页面显示具体失败原因。"],
            ],
            "field_dictionary": field_dictionary_rows(),
        }
        for sheet_name, fields in SHEETS.items():
            headers = [field[0] for field in fields]
            rows = [headers]
            for item in rows_by_sheet.get(sheet_name, []):
                rows.append([item.get(header, "") for header in headers])
            worksheets[sheet_name] = rows
        write_xlsx(OUTPUT_DIR / file_name, worksheets)
        print(f"created {OUTPUT_DIR / file_name}")


def build_cases():
    valid_patient = {
        "patient_id": "VAL-001",
        "patient_name": "校验测试001",
        "gender": "男",
        "birth_date": "1960-01-01",
        "age": 66,
        "height_cm": 170,
        "weight_kg": 68,
        "bmi": 23.5,
        "phone": "脱敏",
        "created_date": "2026-01-01",
    }
    return {
        "01_missing_required_fields.xlsx": {
            "patients": [
                {
                    **valid_patient,
                    "patient_id": "",
                    "gender": "",
                    "age": "",
                    "created_date": "",
                }
            ],
            "symptom_scores": [
                {
                    "symptom_id": "",
                    "patient_id": "",
                    "assessment_date": "",
                    "cat_score": 18,
                    "mmrc_score": 2,
                }
            ],
        },
        "02_invalid_date_format.xlsx": {
            "patients": [
                {
                    **valid_patient,
                    "created_date": "2026/01/01",
                    "birth_date": "1960年01月01日",
                }
            ],
            "symptom_scores": [
                {
                    "symptom_id": "S-VAL-001",
                    "patient_id": "VAL-001",
                    "assessment_date": "2026-13-40",
                    "cat_score": 18,
                    "mmrc_score": 2,
                }
            ],
            "pulmonary_tests": [
                {
                    "pulmonary_test_id": "PF-VAL-001",
                    "patient_id": "VAL-001",
                    "test_date": "20260102",
                    "fev1_l": 1.2,
                    "fvc_l": 2.6,
                    "fev1_fvc_ratio": 0.46,
                    "fev1_percent_predicted": 45,
                }
            ],
        },
        "03_numeric_outliers.xlsx": {
            "patients": [
                {
                    **valid_patient,
                    "age": 140,
                    "height_cm": 260,
                    "weight_kg": 8,
                    "bmi": 80,
                }
            ],
            "symptom_scores": [
                {
                    "symptom_id": "S-VAL-001",
                    "patient_id": "VAL-001",
                    "assessment_date": "2026-01-02",
                    "cat_score": 99,
                    "mmrc_score": 9,
                }
            ],
            "pulmonary_tests": [
                {
                    "pulmonary_test_id": "PF-VAL-001",
                    "patient_id": "VAL-001",
                    "test_date": "2026-01-03",
                    "fev1_l": -1,
                    "fvc_l": 20,
                    "fev1_fvc_ratio": 2,
                    "fev1_percent_predicted": 300,
                }
            ],
            "lab_results": [
                {
                    "lab_id": "L-VAL-001",
                    "patient_id": "VAL-001",
                    "lab_date": "2026-01-04",
                    "wbc": 200,
                    "neutrophil_percent": 150,
                    "spo2": 130,
                }
            ],
        },
        "04_mixed_duplicate_and_relation_errors.xlsx": {
            "patients": [
                valid_patient,
                {
                    **valid_patient,
                    "patient_name": "重复患者ID",
                    "age": 67,
                },
            ],
            "symptom_scores": [
                {
                    "symptom_id": "S-UNKNOWN",
                    "patient_id": "NOT-IN-PATIENTS",
                    "assessment_date": "2026-01-02",
                    "cat_score": 18,
                    "mmrc_score": 2,
                }
            ],
            "medications": [
                {
                    "medication_id": "MED-BAD",
                    "patient_id": "VAL-001",
                    "start_date": "2026-01-05",
                    "medication_name": "",
                }
            ],
        },
    }


if __name__ == "__main__":
    main()
