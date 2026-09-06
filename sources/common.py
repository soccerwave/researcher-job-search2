from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class JobRecord:
    source: str
    title: str
    company: str = ""
    location: str = ""
    date: str = ""
    url: str = ""
    id: str = ""
    modality: str = ""
    description: str = ""
    search_query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
