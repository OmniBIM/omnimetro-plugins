# -*- coding: utf-8 -*-
"""
migrator_core.infra.cancellation
================================
Cancellation token pattern for safe interruption of migration loops.
"""

from ..exceptions import CancellationError

class CancellationToken(object):
    """
    Thread-safe flag coordinating user cancellation requests with
    batch transaction processing.
    """
    def __init__(self):
        self._is_cancelled = False
        self._reason = ""

    @property
    def is_cancellation_requested(self):
        return self._is_cancelled

    def request_cancel(self, reason="User requested cancellation"):
        self._is_cancelled = True
        self._reason = reason

    def reset(self):
        self._is_cancelled = False
        self._reason = ""

    def throw_if_cancellation_requested(self):
        if self._is_cancelled:
            raise CancellationError(self._reason or "Operation was cancelled.")
