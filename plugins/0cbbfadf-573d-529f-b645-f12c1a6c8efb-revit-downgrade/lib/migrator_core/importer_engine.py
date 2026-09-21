# -*- coding: utf-8 -*-
"""
migrator_core.importer_engine
=============================
Revit 2020 Reconstruction Engine.
Executes multi-phase reconstruction following the strict dependency hierarchy:
Datums -> Materials -> Types -> Hosts -> Hosted -> MEP -> Views -> Validation.
"""

import os
from .compat import IS_REVIT, DB, RevitVersionAdapter
from .constants import Phase, ActionStatus
from .infra.logger import logger
from .infra.cancellation import CancellationToken
from .infra.batching import BatchTransactionRunner
from .infra.journal import MigrationJournal
from .converters import ConverterRegistry
from .converters.level_converter import LevelConverter
from .converters.grid_converter import GridConverter
from .converters.material_converter import MaterialConverter
from .converters.view_converter import ViewConverter, SheetConverter
from .validation.validator import ModelValidator
from .validation.report_generator import ReportGenerator

class MigrationContext(object):
    """Execution context shared across all converters and phases."""

    def __init__(self, doc, reader, config=None, cancellation_token=None):
        self.doc = doc
        self.reader = reader
        self.config = config
        self.package_id = reader.manifest.package_id if reader else "UNKNOWN_PACKAGE"
        self.cancellation_token = cancellation_token or CancellationToken()
        self.adapter = RevitVersionAdapter(doc)

        # In-memory mapping lookups: source_uid -> target_element_id
        self._uid_to_target_id = {}
        self._source_level_id_to_target = {}

    def register_mapping(self, source_unique_id, source_element_id, target_element_id, target_unique_id, status=ActionStatus.SUCCESS):
        self._uid_to_target_id[str(source_unique_id)] = target_element_id
        if self.reader:
            self.reader.record_element_mapping(source_unique_id, source_element_id, target_element_id, target_unique_id, status)

    def get_target_element_by_source_uid(self, source_unique_id):
        if not source_unique_id or not IS_REVIT or not self.doc:
            return None
        target_id_int = self._uid_to_target_id.get(str(source_unique_id))
        if target_id_int is not None:
            return self.doc.GetElement(DB.ElementId(target_id_int))
        # Query reader SQLite
        if self.reader:
            mapping = self.reader.get_target_mapping(source_unique_id)
            if mapping and mapping[0]:
                self._uid_to_target_id[str(source_unique_id)] = mapping[0]
                return self.doc.GetElement(DB.ElementId(mapping[0]))
        return None

    def get_target_level_id(self, source_level_id):
        if source_level_id in self._source_level_id_to_target:
            return self._source_level_id_to_target[source_level_id]
        return None

    def apply_parameters(self, target_elem, param_records):
        """Sets non-readonly parameter values on target Revit element."""
        if not IS_REVIT or not target_elem or not param_records:
            return
        for p in param_records:
            if p.read_only:
                continue
            param = target_elem.LookupParameter(p.name)
            if param and not param.IsReadOnly:
                val = p.get_raw_value()
                if val is not None:
                    self.adapter.set_parameter_value(param, val)

class Revit2020ImporterEngine(object):
    """
    Executes the 10-phase migration process in Revit 2020.
    """

    def __init__(self, doc, reader, config=None, journal_path=None):
        self.doc = doc
        self.reader = reader
        self.config = config
        self.cancellation_token = CancellationToken()
        self.context = MigrationContext(doc, reader, config, self.cancellation_token)
        self.journal = MigrationJournal(journal_path)
        self.batch_size = config.batch_size if config else 1000

    def run_import(self, progress_callback=None, stage_reporter_factory=None):
        """
        Executes full model migration through all phases.
        """
        logger.info("Starting Revit 2020 Import Engine...", phase="IMPORT_ENGINE")

        cb_mat = stage_reporter_factory(u"阶段 1/5: 正在恢复材质与外观着色器...", 0.0, 10.0) if stage_reporter_factory else progress_callback
        cb_dat = stage_reporter_factory(u"阶段 2/5: 正在重建标高基准与轴网系统...", 10.0, 20.0) if stage_reporter_factory else progress_callback
        cb_elm = stage_reporter_factory(u"阶段 3/5: 正在原生批量重建构件与几何资产...", 20.0, 85.0) if stage_reporter_factory else progress_callback
        cb_viw = stage_reporter_factory(u"阶段 4/5: 正在重建工程视图与图纸视口...", 85.0, 95.0) if stage_reporter_factory else progress_callback
        cb_val = stage_reporter_factory(u"阶段 5/5: 正在执行模型质检与生成分析报告...", 95.0, 100.0) if stage_reporter_factory else progress_callback

        # Phase 0: Project Init & Materials
        self._run_phase_materials(cb=cb_mat)

        # Phase 1: Datums (Levels & Grids)
        self._run_phase_datums(cb=cb_dat)

        # Phase 2 & 3 & 4 & 5: Elements in batches
        self._run_phase_elements(progress_callback=cb_elm)

        # Phase 7 & 8: Views & Sheets
        self._run_phase_views_and_sheets(cb=cb_viw)

        # Validation & Report
        validation_result = self._run_validation(cb=cb_val)

        logger.success("Import engine finished successfully!", phase="IMPORT_ENGINE")
        return validation_result

    def _run_phase_materials(self, cb=None):
        logger.info("Phase 0: Restoring Materials...", phase="PHASE_0")
        materials = self.reader.get_materials()
        total = len(materials)
        converter = MaterialConverter()
        for idx, mat_rec in enumerate(materials):
            if cb:
                try:
                    cb(idx + 1, total, getattr(mat_rec, "name", "材质"))
                except Exception:
                    pass
            try:
                converter.convert(mat_rec, self.context)
            except Exception as ex:
                logger.error("Failed creating material '{}': {}".format(mat_rec.name, str(ex)), phase="MATERIALS")

    def _run_phase_datums(self, cb=None):
        logger.info("Phase 1: Restoring Levels & Grids...", phase="PHASE_1")
        levels = self.reader.get_levels()
        grids = self.reader.get_grids()
        total = len(levels) + len(grids)
        curr = 0

        # Levels
        lvl_conv = LevelConverter()
        for lvl_rec in levels:
            curr += 1
            if cb:
                try:
                    cb(curr, max(1, total), u"标高: {}".format(getattr(lvl_rec, "name", "")))
                except Exception:
                    pass
            try:
                target_lvl = lvl_conv.convert(lvl_rec, self.context)
                if target_lvl:
                    self.context._source_level_id_to_target[lvl_rec.source_id] = target_lvl.Id
            except Exception as ex:
                logger.error("Failed creating level '{}': {}".format(lvl_rec.name, str(ex)), phase="LEVELS")

        # Grids
        grid_conv = GridConverter()
        for grid_rec in grids:
            curr += 1
            if cb:
                try:
                    cb(curr, max(1, total), u"轴网: {}".format(getattr(grid_rec, "name", "")))
                except Exception:
                    pass
            try:
                grid_conv.convert(grid_rec, self.context)
            except Exception as ex:
                logger.error("Failed creating grid '{}': {}".format(grid_rec.name, str(ex)), phase="GRIDS")

    def _run_phase_elements(self, progress_callback=None):
        logger.info("Phase 3-6: Reconstructing Host and Hosted Elements...", phase="PHASE_ELEMENTS")
        elements = self.reader.get_all_elements()
        total = len(elements)

        def convert_element(el):
            # Check journal if already processed
            if self.journal.is_processed(el.source_unique_id):
                return

            conv = ConverterRegistry.get_converter(el, self.context)
            if conv:
                conv.convert(el, self.context)
                self.journal.record_processed(el.source_unique_id, is_success=True)

        BatchTransactionRunner.run_batch(
            doc=self.doc,
            items=elements,
            convert_fn=convert_element,
            batch_size=self.batch_size,
            transaction_prefix="Importing BIM Elements",
            cancellation_token=self.cancellation_token,
            on_progress=progress_callback
        )

    def _run_phase_views_and_sheets(self, cb=None):
        logger.info("Phase 7-8: Restoring Views and Sheets...", phase="PHASE_VIEWS")
        views = self.reader.get_views()
        sheets = self.reader.get_sheets()
        total = len(views) + len(sheets)
        curr = 0

        v_conv = ViewConverter()
        for v in views:
            curr += 1
            if cb:
                try:
                    cb(curr, max(1, total), u"视图: {}".format(getattr(v, "name", "")))
                except Exception:
                    pass
            try:
                v_conv.convert(v, self.context)
            except Exception:
                pass

        s_conv = SheetConverter()
        for s in sheets:
            curr += 1
            if cb:
                try:
                    cb(curr, max(1, total), u"图纸: {}".format(getattr(s, "sheet_number", "")))
                except Exception:
                    pass
            try:
                s_conv.convert(s, self.context)
            except Exception:
                pass

    def _run_validation(self, cb=None):
        logger.info("Phase 10: Running Model Validation Engine...", phase="VALIDATION")
        if cb:
            try:
                cb(1, 2, u"正在执行模型几何与参数对比校验...")
            except Exception:
                pass

        val_result = ModelValidator.validate(self.reader)

        if cb:
            try:
                cb(2, 2, u"正在生成质检报告与 HTML 迁移摘要...")
            except Exception:
                pass

        # Generate reports in log directory
        appdata = os.getenv("APPDATA", os.path.expanduser("~"))
        report_dir = os.path.join(appdata, "RVT2020Migrator", "reports")
        html_p = os.path.join(report_dir, "MigrationReport.html")
        json_p = os.path.join(report_dir, "MigrationReport.json")

        ReportGenerator.generate_html("Migration Result", val_result, html_p)
        ReportGenerator.generate_json("Migration Result", val_result, [], [], json_p)
        logger.success("Validation completed. Report saved to: {}".format(html_p), phase="VALIDATION")
        return val_result

# Alias for unified naming convention
ImporterEngine = Revit2020ImporterEngine
