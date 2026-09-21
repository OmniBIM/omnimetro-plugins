# Revit 跨版本模型降级与原生重建平台 (OmniMetro 插件版)

## 中文说明

本插件基于中立 `.rvtmig` ZIP/SQLite 容器格式与五级降级策略（Native 原生 > Family 族重建 > Geometry 族几何兜底 > DirectShape 几何兜底 > Skip 跳过），解决 Revit 高版本模型向低版本安全降级、非破坏性参数提取与高质量原生重建。

### 核心功能
1. **非破坏性静态模型扫描**：快速提取项目信息、标高、轴网、物理构件、族与类型、材质与工程视图。
2. **0.5 秒实时扫描进度监控**：专属弹出窗口，实时显示阶段、已处理数、扫描吞吐速度、正在处理的构件图元及平滑进度条。
3. **降级可行性评分与风险矩阵**：0-100 分综合打分，分类别呈现原生保真率、几何兜底比例与不支持项。
4. **流式 `.rvtmig` 中间包打包**：包含 28 张核心关系数据表与去重 SHA-256 几何/材质资源。
5. **Revit 2020 / 2018 原生多阶段重建**：拓扑依赖排序、批量事务提交（1000图元/批）、断点恢复日志与可扩展存储溯源标记。
6. **自动化三层质检与 HTML 交互式报告**：容差几何体积对比、参数完整性分析与可视化质量看板。

### 支持版本
- 导出端：Revit 2027、Revit 2026、Revit 2025、Revit 2024
- 导入重建端：Revit 2020、Revit 2018

---

## English Description

Cross-version Revit BIM model migration and downgrade platform based on neutral `.rvtmig` containers and 5-level degradation strategy. Enables safe, high-fidelity native model reconstruction in Revit 2020/2018 from Revit 2027/2024 projects.
