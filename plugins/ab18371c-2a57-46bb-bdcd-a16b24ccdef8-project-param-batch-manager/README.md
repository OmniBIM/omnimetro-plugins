# 项目参数批量管理器

## 中文说明

选择多个 Revit 文件，自动提取每个文件的：

- **项目基点**：N/S、E/W、高程、到正北角度（显示单位：毫米 / 度）
- **项目全部参数**：内置项目基本参数（项目名称、编号、客户、地址等）与项目参数（共享参数绑定到项目信息的）

支持：

- **新增项目参数**：在界面中定义参数名称、类型（文本/整数/数字/是-否/长度/面积/体积/角度）与分组，批量添加到所选文件。
- **批量修改**：在表格中直接编辑参数目标值（含基点），勾选文件后批量写入并保存；修改前有对比预览与确认对话框。

### 支持的 Revit 版本

Revit 2018 – 2026。

### 所需权限

- `revit_api`：打开文档、读取/写入项目参数、新增共享参数绑定。

### 已知限制

- 写入操作会直接保存文件，请确保文件未被其他 Revit 会话占用。
- 新增项目参数使用共享参数机制，首次使用会在临时目录创建共享参数文件（`%TEMP%\OmniMetro\OmniMetro_SharedParams.txt`）。
- 只读参数（如项目名称等系统锁定的参数）在表格中不可编辑，写入时自动跳过。

## English Description

Select multiple Revit files and extract from each:

- **Project Base Point**: N/S, E/W, elevation, angle to true north (displayed in mm / degrees)
- **All project parameters**: built-in project parameters (project name, number, client, address, etc.) and project parameters (shared parameters bound to project information)

Features:

- **Add project parameters**: define name, type (text/integer/number/yes-no/length/area/volume/angle) and group, then add to the selected files in batch.
- **Batch edit**: edit target values directly in the grid (including base point), select files and write/save in batch; a comparison preview and confirmation dialog are shown before writing.

### Supported Revit Versions

Revit 2018 – 2026.

### Permissions

- `revit_api`: open documents, read/write project parameters, bind new shared parameters.

### Known Limitations

- Writing saves files directly; make sure files are not open in another Revit session.
- New project parameters use the shared-parameter mechanism; on first use a shared parameter file is created in the temp directory (`%TEMP%\OmniMetro\OmniMetro_SharedParams.txt`).
- Read-only parameters (e.g. system-locked ones like project name) are not editable in the grid and are skipped on write.
