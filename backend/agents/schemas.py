from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class AgentStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    STOP = "STOP"

class AgentName(str, Enum):
    MANAGER = "manager"
    ORDER = "order"
    ARTWORK = "artwork"
    PREFLIGHT = "preflight"
    PRINT_READY = "print_ready"
    RECIPE = "recipe"
    OPTIMIZATION = "optimization"
    PRODUCTION = "production"
    QC = "qc"
    COMPLETE = "complete"

class AgentResult(BaseModel):
    job_id: str
    agent: AgentName
    status: AgentStatus
    next_agent: AgentName
    summary: str
    data: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    stop_reasons: List[str] = Field(default_factory=list)

class JobState(BaseModel):
    job_id: str
    product: str = "business_card"
    quantity: int
    order_spec: Dict[str, Any] = Field(default_factory=dict)
    artwork: Dict[str, Any] = Field(default_factory=dict)
    preflight: Dict[str, Any] = Field(default_factory=dict)
    print_ready: Dict[str, Any] = Field(default_factory=dict)
    recipe: Dict[str, Any] = Field(default_factory=dict)
    optimization: Dict[str, Any] = Field(default_factory=dict)
    production: Dict[str, Any] = Field(default_factory=dict)
    qc: Dict[str, Any] = Field(default_factory=dict)
    approved_file_id: Optional[str] = None
    approved_checksum: Optional[str] = None
    human_authorized: bool = False
    connector_ready: bool = False
    physical_print_enabled: bool = False
