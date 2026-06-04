from __future__ import annotations

from pathlib import Path

from generate_import_template import README_ROWS, SHEETS, write_xlsx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "data" / "copd_patient_import_sample_40.xlsx"


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    worksheets = {
        "README": README_ROWS
        + [
            ["样例数据说明", "本文件包含40例模拟患者数据，仅用于POC/MVP导入和页面演示。"],
            ["数据边界", "样例不包含真实患者隐私数据，不包含原始CT、DICOM、PACS数据。"],
        ],
        "field_dictionary": field_dictionary_rows(),
    }
    samples = build_samples()
    for sheet_name, fields in SHEETS.items():
        headers = [field[0] for field in fields]
        rows = [headers]
        for item in samples.get(sheet_name, []):
            rows.append([item.get(header, "") for header in headers])
        worksheets[sheet_name] = rows

    write_xlsx(OUTPUT_PATH, worksheets)
    print(f"created {OUTPUT_PATH}")


def field_dictionary_rows():
    rows = [["sheet", "field_name", "中文名", "类型", "是否必填", "示例", "说明"]]
    for sheet_name, fields in SHEETS.items():
        for field in fields:
            rows.append([sheet_name, *field])
    return rows


def build_samples():
    data = {sheet_name: [] for sheet_name in SHEETS}
    medications = [
        ("噻托溴铵", "LAMA"),
        ("茚达特罗/格隆溴铵", "LAMA/LABA"),
        ("布地奈德/福莫特罗", "LABA/ICS"),
        ("乌美溴铵/维兰特罗", "LAMA/LABA"),
    ]
    pathogens = ["未检出", "流感嗜血杆菌", "肺炎链球菌", "铜绿假单胞菌", "病毒核酸阳性"]
    comorbidity_sets = [
        {"hypertension": "是", "diabetes": "否", "coronary_disease": "否", "other_comorbidities": ""},
        {"hypertension": "否", "diabetes": "是", "coronary_disease": "否", "other_comorbidities": ""},
        {"hypertension": "是", "diabetes": "是", "coronary_disease": "否", "other_comorbidities": "骨质疏松"},
        {"hypertension": "是", "diabetes": "否", "coronary_disease": "是", "other_comorbidities": ""},
    ]

    for index in range(1, 41):
        patient_id = f"COPD-S{index:03d}"
        age = 50 + (index * 3 % 34)
        gender = "男" if index % 3 else "女"
        created_month = 1 + index % 6
        height = 158 + index % 18
        weight = 52 + index % 24
        bmi = round(weight / ((height / 100) ** 2), 1)
        cat = 8 + index % 25
        mmrc = index % 5
        fev1 = round(0.85 + (index % 16) * 0.08, 2)
        fvc = round(fev1 + 1.05 + (index % 6) * 0.15, 2)
        ratio = round(fev1 / fvc, 2)
        fev1_pct = 32 + index % 46
        crp = round(4.5 + (index % 12) * 4.2, 1)
        feno = 12 + index % 48
        eos = round(0.06 + (index % 9) * 0.07, 2)
        emphysema = 8 + index % 52
        medication_name, medication_type = medications[index % len(medications)]
        pathogen = pathogens[index % len(pathogens)]
        exacerbation_count = index % 4
        readmission = "是" if index % 7 in {0, 3} else "否"
        survival = "存活" if index % 19 else "失访"

        data["patients"].append(
            {
                "patient_id": patient_id,
                "patient_name": f"患者{index:03d}",
                "gender": gender,
                "birth_date": f"{2026 - age}-0{1 + index % 9}-15",
                "age": age,
                "height_cm": height,
                "weight_kg": weight,
                "bmi": bmi,
                "phone": "脱敏",
                "created_date": f"2026-{created_month:02d}-01",
            }
        )
        data["smoking_history"].append(
            {
                "patient_id": patient_id,
                "smoking_status": "既往吸烟" if index % 4 else "当前吸烟",
                "cigarettes_per_day": 10 + (index % 3) * 10,
                "smoking_years": 15 + index % 30,
                "pack_years": 15 + index % 45,
                "quit_smoking": "是" if index % 4 else "否",
                "quit_years": index % 12 if index % 4 else "",
            }
        )
        comorbidity = comorbidity_sets[index % len(comorbidity_sets)]
        data["comorbidities"].append(
            {
                "patient_id": patient_id,
                "copd_diagnosis_date": f"{2015 + index % 9}-06-01",
                "gold_grade": f"GOLD {1 + index % 4}",
                "bronchiectasis": "是" if index % 11 == 0 else "否",
                "asthma": "是" if index % 13 == 0 else "否",
                **comorbidity,
            }
        )
        data["symptom_scores"].append(
            {
                "symptom_id": f"S{index:04d}",
                "patient_id": patient_id,
                "assessment_date": f"2026-05-{1 + index % 27:02d}",
                "cat_score": cat,
                "mmrc_score": mmrc,
                "cough": "明显" if cat >= 18 else "轻度",
                "sputum": "有" if index % 2 else "无",
                "dyspnea": "活动后气促" if mmrc >= 2 else "轻微活动后不适",
                "other_symptoms": "夜间喘息" if index % 10 == 0 else "",
            }
        )
        data["pulmonary_tests"].append(
            {
                "pulmonary_test_id": f"PF{index:04d}",
                "patient_id": patient_id,
                "test_date": f"2026-05-{2 + index % 26:02d}",
                "fev1_l": fev1,
                "fvc_l": fvc,
                "fev1_fvc_ratio": ratio,
                "fev1_percent_predicted": fev1_pct,
                "fvc_percent_predicted": 48 + index % 40,
                "feno": feno,
                "pulmonary_test_summary": "阻塞性通气功能障碍，需结合临床评估",
            }
        )
        for lab_index in range(1, 3):
            data["lab_results"].append(
                {
                    "lab_id": f"L{index:03d}{lab_index}",
                    "patient_id": patient_id,
                    "lab_date": f"2026-0{3 + lab_index}-{1 + (index + lab_index) % 27:02d}",
                    "wbc": round(6.5 + (index + lab_index) % 8 * 0.9, 1),
                    "neutrophil_percent": round(55 + (index + lab_index) % 25, 1),
                    "eosinophil_count": eos,
                    "crp": crp if lab_index == 2 else round(crp * 0.7, 1),
                    "pct": round(0.04 + (index % 7) * 0.04, 2),
                    "spo2": 88 + index % 10,
                    "pao2": 58 + index % 24,
                    "paco2": 38 + index % 16,
                }
            )
        if pathogen != "未检出":
            data["pathogen_results"].append(
                {
                    "pathogen_id": f"M{index:04d}",
                    "patient_id": patient_id,
                    "pathogen_test_date": f"2026-05-{3 + index % 25:02d}",
                    "sample_type": "痰液" if index % 2 else "BALF",
                    "test_method": "mNGS" if index % 3 else "培养",
                    "detected_pathogens": pathogen,
                    "pathogen_abundance": f"{80 + index * 3} reads" if pathogen != "病毒核酸阳性" else "阳性",
                    "clinical_relevance": "待医生判断",
                }
            )
        data["ct_features"].append(
            {
                "ct_id": f"CT{index:04d}",
                "patient_id": patient_id,
                "ct_date": f"2026-05-{4 + index % 24:02d}",
                "ct_report_text": "双肺透亮度增高，肺气肿改变；气道壁增厚。" if emphysema >= 25 else "双肺纹理增多，局部气道壁轻度增厚。",
                "emphysema_percent": emphysema,
                "airway_wall_thickness": round(1.1 + index % 8 * 0.2, 1),
                "lung_volume_index": round(4.2 + index % 11 * 0.3, 1),
                "airway_wall_thickening": "是" if index % 3 else "否",
                "bullae": "是" if index % 17 == 0 else "否",
                "infection_signs": "是" if crp > 20 else "否",
                "ct_summary": "CT报告或已提取影像特征提示慢阻肺相关改变",
            }
        )
        data["medications"].append(
            {
                "medication_id": f"MED{index:04d}",
                "patient_id": patient_id,
                "start_date": f"2026-01-{1 + index % 27:02d}",
                "end_date": "",
                "medication_name": medication_name,
                "medication_type": medication_type,
                "dosage": "按医嘱规律使用",
                "maintenance_treatment": "是",
                "medication_note": "模拟维持治疗记录",
            }
        )
        for ae_index in range(exacerbation_count):
            data["exacerbations"].append(
                {
                    "exacerbation_id": f"AE{index:03d}{ae_index + 1}",
                    "patient_id": patient_id,
                    "exacerbation_date": f"2026-0{2 + ae_index}-{5 + index % 20:02d}",
                    "severity": "重度" if ae_index == 2 else ("中度" if ae_index == 1 else "轻度"),
                    "hospitalization": "是" if ae_index >= 1 else "否",
                    "antibiotics_used": "是" if pathogen != "未检出" else "否",
                    "steroid_used": "是" if ae_index >= 1 else "否",
                    "trigger_factor": "感染可能" if pathogen != "未检出" else "未明确",
                    "outcome": "好转后随访",
                }
            )
        data["followups"].append(
            {
                "followup_id": f"FU{index:04d}",
                "patient_id": patient_id,
                "followup_date": f"2026-06-{1 + index % 27:02d}",
                "symptom_change": "气促较前加重" if cat >= 20 else "症状较稳定",
                "new_exacerbation": "是" if exacerbation_count >= 2 else "否",
                "rehospitalization": readmission,
                "pulmonary_function_change": "FEV1较前下降" if fev1_pct < 45 else "肺功能较稳定",
                "survival_status": survival,
                "followup_note": "继续门诊随访",
            }
        )
    return data


if __name__ == "__main__":
    main()
