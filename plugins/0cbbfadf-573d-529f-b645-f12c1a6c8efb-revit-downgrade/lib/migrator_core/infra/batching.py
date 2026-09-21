# -*- coding: utf-8 -*-
"""
migrator_core.infra.batching
============================
Batch transaction management ensuring memory efficiency and non-catastrophic
error recovery during massive model reconstructions.
"""

from ..compat import IS_REVIT, DB
from .logger import logger
from ..exceptions import CancellationError

class BatchTransactionRunner(object):
    """
    Executes element reconstruction tasks in transaction batches (default 500-1000 items).
    Safely captures individual element failures without failing the entire batch.
    """

    @staticmethod
    def run_batch(
        doc,
        items,
        convert_fn,
        batch_size=500,
        transaction_prefix="Migrating",
        cancellation_token=None,
        on_progress=None
    ):
        """
        Processes items in batches.
        convert_fn is called as convert_fn(item, context).
        Returns (success_count, error_count, failed_items).
        """
        total = len(items)
        success_count = 0
        error_count = 0
        failed_items = []

        if total == 0:
            return 0, 0, []

        def _call_progress(cnt, tot, desc=""):
            if not on_progress:
                return
            try:
                on_progress(cnt, tot, desc)
            except TypeError:
                try:
                    on_progress(cnt, tot)
                except Exception:
                    pass
            except Exception:
                pass

        batch_start = 0
        while batch_start < total:
            if cancellation_token and cancellation_token.is_cancellation_requested:
                logger.warning("Batch processing cancelled by user at item {}/{}".format(batch_start, total))
                break

            batch_end = min(batch_start + batch_size, total)
            current_batch = items[batch_start:batch_end]
            batch_tx_name = "{} ({} - {} of {})".format(transaction_prefix, batch_start + 1, batch_end, total)

            tx = None
            if IS_REVIT and doc:
                tx = DB.Transaction(doc, batch_tx_name)
                tx.Start()

            try:
                for idx, item in enumerate(current_batch):
                    if cancellation_token and cancellation_token.is_cancellation_requested:
                        break

                    curr_count = batch_start + idx + 1
                    item_desc = getattr(item, "category_name", "") or getattr(item, "element_class", "") or getattr(item, "name", "图元")
                    _call_progress(curr_count, total, item_desc)

                    try:
                        convert_fn(item)
                        success_count += 1
                    except Exception as ex:
                        error_count += 1
                        failed_items.append((item, str(ex)))
                        logger.error(
                            "Failed converting item: {}".format(str(ex)),
                            phase=transaction_prefix,
                            source_id=getattr(item, "source_unique_id", None) or getattr(item, "source_id", None)
                        )

                if tx and tx.HasStarted():
                    tx.Commit()

            except Exception as batch_ex:
                if tx and tx.HasStarted():
                    tx.RollBack()
                logger.critical(
                    "Batch transaction failed: {}. Rolling back batch.".format(str(batch_ex)),
                    phase=transaction_prefix
                )
                error_count += len(current_batch)
                for itm in current_batch:
                    failed_items.append((itm, str(batch_ex)))

            batch_start = batch_end
            _call_progress(batch_end, total, "批次提交完成")

        return success_count, error_count, failed_items
