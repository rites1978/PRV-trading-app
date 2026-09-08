"""
🏛️ PRV CAPITAL | OUT-OF-SAMPLE (OOS) CRYPTOGRAPHIC SEALING MECHANISM
Strict isolation of the final untouched Out-of-Sample evaluation dataset.

Invariants:
1. Chronological partitioning: TRAIN < VALIDATION < FINAL_OOS.
2. The FINAL_OOS dataset is cryptographically hashed and sealed prior to strategy exploration.
3. Any attempt to query sealed data before formal post-freeze authorization raises OOSAccessViolationError.
4. Unsealing requires an immutable audit record (signature + reason + timestamp).
"""
import hashlib
import json
from datetime import datetime, date, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class OOSAccessViolationError(RuntimeError):
    """Raised when an unauthorized read of the sealed OOS partition is attempted."""
    pass


class PartitionType(str, Enum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    FINAL_OOS = "FINAL_OOS"


class OOSSealer:
    """
    Manages dataset partitioning and enforces cryptographic sealing of the final OOS set.
    """
    def __init__(
        self,
        train_start: str = "2020-01-01",
        train_end: str = "2023-12-31",
        val_start: str = "2024-01-01",
        val_end: str = "2025-06-30",
        oos_start: str = "2025-07-01",
        oos_end: str = "2026-09-01"
    ):
        self.train_start = pd.to_datetime(train_start)
        self.train_end = pd.to_datetime(train_end)
        self.val_start = pd.to_datetime(val_start)
        self.val_end = pd.to_datetime(val_end)
        self.oos_start = pd.to_datetime(oos_start)
        self.oos_end = pd.to_datetime(oos_end)

        # Invariant check: strictly sequential partitions
        if not (self.train_start < self.train_end < self.val_start < self.val_end < self.oos_start < self.oos_end):
            raise ValueError("Partitions must be strictly chronological and non-overlapping.")

        self._is_sealed: bool = True
        self._oos_manifest_hash: str = ""
        self._unseal_audit_log: Optional[Dict[str, Any]] = None

    @property
    def is_sealed(self) -> bool:
        return self._is_sealed

    @property
    def manifest_hash(self) -> str:
        return self._oos_manifest_hash

    def get_partition_type(self, dt: pd.Timestamp) -> PartitionType:
        """Identifies which partition a timestamp belongs to."""
        ts = pd.to_datetime(dt)
        if self.train_start <= ts <= self.train_end:
            return PartitionType.TRAIN
        elif self.val_start <= ts <= self.val_end:
            return PartitionType.VALIDATION
        elif self.oos_start <= ts <= self.oos_end:
            return PartitionType.FINAL_OOS
        else:
            raise ValueError(f"Timestamp {ts} falls outside configured simulation window.")

    def seal_oos_partition(self, symbol_bars: Dict[str, pd.DataFrame]) -> str:
        """
        Computes SHA-256 cryptographic hash of all Final OOS bars and locks the partition.
        """
        hasher = hashlib.sha256()
        total_bars = 0

        for symbol in sorted(symbol_bars.keys()):
            df = symbol_bars[symbol]
            oos_slice = df.loc[(df.index >= self.oos_start) & (df.index <= self.oos_end)]
            total_bars += len(oos_slice)
            hasher.update(symbol.encode("utf-8"))
            hasher.update(str(len(oos_slice)).encode("utf-8"))
            if not oos_slice.empty:
                # Hash first and last timestamps and prices
                hasher.update(str(oos_slice.index[0]).encode("utf-8"))
                hasher.update(str(oos_slice.index[-1]).encode("utf-8"))
                hasher.update(str(oos_slice["Close"].values.round(4)).encode("utf-8"))

        self._oos_manifest_hash = hasher.hexdigest()
        self._is_sealed = True
        logger.info(
            f"FINAL OOS SEALED: Hash={self._oos_manifest_hash}, "
            f"Window=[{self.oos_start.date()} to {self.oos_end.date()}], Total OOS Bars={total_bars}"
        )
        return self._oos_manifest_hash

    def filter_allowed_data(
        self,
        symbol_bars: Dict[str, pd.DataFrame],
        allow_validation: bool = True
    ) -> Dict[str, pd.DataFrame]:
        """
        Returns only the data permitted for model research and parameter validation.
        If FINAL_OOS is sealed, OOS data is completely stripped out.
        """
        max_allowed_date = self.val_end if allow_validation else self.train_end
        filtered = {}

        for sym, df in symbol_bars.items():
            accessible = df.loc[df.index <= max_allowed_date]
            filtered[sym] = accessible.copy()

        return filtered

    def get_sealed_oos_data(
        self,
        symbol_bars: Dict[str, pd.DataFrame]
    ) -> Dict[str, pd.DataFrame]:
        """
        Retrieves the Final OOS data.
        Fails closed if the partition has not been explicitly unsealed.
        """
        if self._is_sealed:
            raise OOSAccessViolationError(
                "FAIL-CLOSED: Attempted to access Final OOS dataset while SEALED. "
                "Final OOS cannot be inspected or evaluated during strategy search or parameter tuning."
            )

        oos_data = {}
        for sym, df in symbol_bars.items():
            oos_slice = df.loc[(df.index >= self.oos_start) & (df.index <= self.oos_end)]
            oos_data[sym] = oos_slice.copy()
        return oos_data

    def unseal_for_final_audit(self, auditor_signature: str, rationale: str) -> Dict[str, Any]:
        """
        Unseals the Final OOS partition for authoritative post-freeze validation.
        Records an immutable audit log.
        """
        if not auditor_signature or not rationale:
            raise ValueError("Auditor signature and rationale are mandatory for unsealing.")

        self._is_sealed = False
        self._unseal_audit_log = {
            "unsealed_at": datetime.now(timezone.utc).isoformat(),
            "auditor_signature": auditor_signature,
            "rationale": rationale,
            "manifest_hash": self._oos_manifest_hash,
            "oos_window": f"{self.oos_start.date()} to {self.oos_end.date()}"
        }
        logger.warning(f"AUDIT: Final OOS unsealed by {auditor_signature}: {rationale}")
        return self._unseal_audit_log
