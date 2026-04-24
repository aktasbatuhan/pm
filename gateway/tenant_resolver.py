"""Gateway tenant mapping utilities.

Maps platform/source identifiers (Slack channel IDs, Telegram chat IDs, etc.)
to tenant IDs so gateway-triggered tool runs execute in the right tenant scope.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional

from gateway.session import SessionSource


@dataclass
class TenantResolver:
    """Tenant resolver interface used by gateway dispatch paths."""

    def resolve(self, source: SessionSource) -> Optional[str]:
        raise NotImplementedError


class EnvTenantResolver(TenantResolver):
    """Resolve tenant IDs from TENANT_SOURCE_MAP JSON env configuration.

    Example:
      TENANT_SOURCE_MAP='{"slack:C123":"tenant-a","telegram:-10012345":"tenant-b"}'
    """

    def __init__(self, mapping: Optional[Dict[str, str]] = None):
        self.mapping = mapping if mapping is not None else self._load_mapping()

    @staticmethod
    def _load_mapping() -> Dict[str, str]:
        raw = os.getenv("TENANT_SOURCE_MAP", "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items() if str(v).strip()}
        except Exception:
            pass
        return {}

    def resolve(self, source: SessionSource) -> Optional[str]:
        platform = source.platform.value if source.platform else ""
        candidates = [
            f"{platform}:{source.chat_id}",
            f"{platform}:{source.chat_name}" if source.chat_name else "",
        ]
        for key in candidates:
            if key and key in self.mapping:
                return self.mapping[key]
        return None
