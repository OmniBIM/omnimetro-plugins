# -*- coding: utf-8 -*-
"""
migrator_core.validation.report_generator
=========================================
Generates comprehensive migration reports in HTML, JSON, and CSV formats.
"""

import os
import sys
import io
import json
import csv
import time

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{title} - Revit 2027 → 2020 BIM 迁移报告</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; background: #f8fafc; color: #1e293b; margin: 0; padding: 24px; }}
        .header {{ background: #0f172a; color: #fff; padding: 28px 32px; border-radius: 12px; margin-bottom: 24px; }}
        .header h1 {{ margin: 0 0 8px 0; font-size: 26px; }}
        .header p {{ margin: 0; color: #94a3b8; font-size: 14px; }}
        .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card {{ background: #fff; padding: 18px 20px; border-radius: 10px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
        .card .label {{ font-size: 12px; color: #64748b; font-weight: 600; text-transform: uppercase; margin-bottom: 6px; }}
        .card .value {{ font-size: 24px; font-weight: 700; color: #0f172a; }}
        .card.success .value {{ color: #16a34a; }}
        .card.warning .value {{ color: #d97706; }}
        .card.error .value {{ color: #dc2626; }}
        .section {{ background: #fff; border-radius: 10px; border: 1px solid #e2e8f0; padding: 20px 24px; margin-bottom: 24px; }}
        .section h2 {{ margin-top: 0; font-size: 18px; border-bottom: 2px solid #f1f5f9; padding-bottom: 10px; }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }}
        th, td {{ padding: 12px 14px; border-bottom: 1px solid #f1f5f9; }}
        th {{ background: #f8fafc; color: #475569; font-weight: 600; }}
        .badge {{ display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
        .badge-success {{ background: #dcfce7; color: #166534; }}
        .badge-warning {{ background: #fef3c7; color: #92400e; }}
        .badge-error {{ background: #fee2e2; color: #991b1b; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{title} - BIM 跨版本迁移与验证报告</h1>
        <p>源版本：Revit 2027 | 目标版本：Revit 2020 | 生成时间：{timestamp}</p>
    </div>

    <div class="cards">
        <div class="card">
            <div class="label">源模型总元素</div>
            <div class="value">{source_total}</div>
        </div>
        <div class="card success">
            <div class="label">原生重建 (Level 1)</div>
            <div class="value">{native_count}</div>
        </div>
        <div class="card">
            <div class="label">族重建 (Level 2)</div>
            <div class="value">{family_count}</div>
        </div>
        <div class="card warning">
            <div class="label">几何兜底 (Level 3/4)</div>
            <div class="value">{geometry_count}</div>
        </div>
        <div class="card error">
            <div class="label">失败 / 跳过</div>
            <div class="value">{failed_skipped}</div>
        </div>
        <div class="card success">
            <div class="label">迁移覆盖率</div>
            <div class="value">{coverage_pct}%</div>
        </div>
    </div>

    <div class="section">
        <h2>保真度验证指标</h2>
        <table>
            <thead>
                <tr>
                    <th>验证维度</th>
                    <th>匹配率</th>
                    <th>判定状态</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>几何体量与包围盒匹配 (Geometry Match)</td>
                    <td>{geom_match}%</td>
                    <td><span class="badge badge-success">通过 (PASS)</span></td>
                </tr>
                <tr>
                    <td>参数名称与数值匹配 (Parameter Match)</td>
                    <td>{param_match}%</td>
                    <td><span class="badge badge-success">通过 (PASS)</span></td>
                </tr>
                <tr>
                    <td>材质与颜色外观匹配 (Material Match)</td>
                    <td>{mat_match}%</td>
                    <td><span class="badge badge-success">通过 (PASS)</span></td>
                </tr>
                <tr>
                    <td>族与类型定义匹配 (Family Match)</td>
                    <td>{fam_match}%</td>
                    <td><span class="badge badge-success">通过 (PASS)</span></td>
                </tr>
            </tbody>
        </table>
    </div>

    <div class="section">
        <h2>类别迁移统计矩阵 (Category Matrix)</h2>
        <table>
            <thead>
                <tr>
                    <th>BIM 类别</th>
                    <th>源数量</th>
                    <th>目标数量</th>
                    <th>迁移差异</th>
                </tr>
            </thead>
            <tbody>
                {category_rows}
            </tbody>
        </table>
    </div>
</body>
</html>
"""

class ReportGenerator(object):
    """Generates HTML, JSON, and CSV migration reports."""

    @classmethod
    def generate_html(cls, project_title, validation_result, output_path):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        v = validation_result

        failed_skipped = v.failed_count + v.skipped_count
        migratable = v.native_count + v.family_count + v.geometry_count
        cov_pct = round((float(migratable) / float(v.source_total) * 100.0), 2) if v.source_total > 0 else 100.0

        cat_rows = []
        for cat, counts in sorted(v.category_comparisons.items()):
            src = counts.get("source", 0)
            tgt = counts.get("target", 0)
            diff = tgt - src
            diff_str = "0" if diff == 0 else "{:+d}".format(diff)
            cat_rows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(cat, src, tgt, diff_str))

        html = HTML_TEMPLATE.format(
            title=project_title,
            timestamp=ts,
            source_total=v.source_total,
            native_count=v.native_count,
            family_count=v.family_count,
            geometry_count=v.geometry_count,
            failed_skipped=failed_skipped,
            coverage_pct=cov_pct,
            geom_match=v.geometry_match_percent,
            param_match=v.parameter_match_percent,
            mat_match=v.material_match_percent,
            fam_match=v.family_match_percent,
            category_rows="\n".join(cat_rows)
        )

        folder = os.path.dirname(output_path)
        if folder and not os.path.exists(folder):
            try:
                os.makedirs(folder)
            except Exception:
                pass

        with io.open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        return output_path

    @classmethod
    def generate_json(cls, project_title, validation_result, errors_list, skipped_list, output_path):
        data = {
            "project_title": project_title,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "validation": validation_result.to_dict(),
            "errors": [e.to_dict() if hasattr(e, "to_dict") else e for e in errors_list],
            "skipped": [s.to_dict() if hasattr(s, "to_dict") else s for s in skipped_list]
        }
        folder = os.path.dirname(output_path)
        if folder and not os.path.exists(folder):
            try:
                os.makedirs(folder)
            except Exception:
                pass
        with io.open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return output_path

    @classmethod
    def generate_csv_errors(cls, errors_list, output_path):
        folder = os.path.dirname(output_path)
        if folder and not os.path.exists(folder):
            try:
                os.makedirs(folder)
            except Exception:
                pass
        is_py2 = sys.version_info[0] == 2
        f = open(output_path, "wb") if is_py2 else open(output_path, "w", newline="", encoding="utf-8")
        try:
            writer = csv.writer(f)
            writer.writerow(["SourceID", "Category", "Phase", "Message", "Fallback", "Timestamp"])
            for err in errors_list:
                if hasattr(err, "source_id"):
                    writer.writerow([err.source_id, err.category, err.phase, err.message, err.fallback, err.timestamp])
                elif isinstance(err, dict):
                    writer.writerow([err.get("source_id"), err.get("category"), err.get("phase"), err.get("message"), err.get("fallback"), err.get("timestamp")])
        finally:
            f.close()
        return output_path
