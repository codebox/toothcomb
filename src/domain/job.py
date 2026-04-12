from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from domain.types import JobId, JobStatus


@dataclass
class Job:
    id: JobId
    title: str
    config: str = "{}"
    status: JobStatus = JobStatus.INIT
    started_at: Optional[str] = None
    created_at: str = ""

    @property
    def config_data(self) -> dict:
        return json.loads(self.config) if self.config else {}

    @property
    def realtime(self) -> bool:
        return self.config_data.get("realtime", True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "config": self.config,
            "status": self.status.value,
            "started_at": self.started_at,
            "created_at": self.created_at,
        }
