# 模型统计

模型统计提供当前 Revit 文档的只读统计界面，可按全模型、当前视图或当前选择扫描族实例，再按指定族名和类型名查看数量。结果表按类别、族名和类型名聚合，并显示匹配实例数量及实例 ID。

点击“导出图纸名称”可选择导出目录和文件名，将当前模型全部图纸的图纸编号和图纸名称导出为标准 `.xlsx` 文件。导出按图纸编号排序，不依赖本机安装 Excel。

窗口同时保留模型总览：族类别、族实例、电缆桥架和图纸数量，以及电缆桥架类型和总长度。电缆桥架缺少可读取长度时会在日志中提示，不会计入总长度。

## 支持范围

- Revit 2018-2025
- 只读访问当前 Revit 文档
- 支持全模型、当前视图和当前选择范围
- 不修改模型，不需要事务权限

## Model Statistics

This feature provides a read-only WPF interface for Revit. It scans family instances in the entire model, active view, or current selection, then filters by family and type name and aggregates the matching instance counts.

The overview retains family category, family instance, cable tray, and sheet totals. Cable tray length is converted from Revit internal units to meters; instances without a readable length are reported in the log and excluded from the length total.

The UI can also export all sheets, including sheet number and sheet name, to a standard `.xlsx` workbook. The save dialog controls both the output directory and file name, and the export does not require Microsoft Excel.

## Support

- Revit 2018-2025
- Read-only access to the active Revit document
- Permission: `revit_api`
