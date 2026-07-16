"""
Structured shapes for compliance audit results. Replacing a single
free-form markdown blob with these lets Doc Review render severity-coded
risk cards and an overall score instead of a wall of text, and lets each
flag carry a citation into BOTH the regulation and the reviewed contract.
"""

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class RiskSeverity(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class RiskFlag(BaseModel):
    severity: RiskSeverity
    category: str = Field(description="Short label, e.g. 'AML', 'Data Privacy', 'Margin Requirements'")
    description: str
    regulation_source: Optional[str] = None
    regulation_reference: Optional[str] = None
    contract_reference: Optional[str] = None
    recommendation: Optional[str] = None


class ChunkRiskExtraction(BaseModel):
    """Structured output of ONE map step (one contract chunk)."""
    flags: List[RiskFlag] = Field(default_factory=list)


class ComplianceAuditReport(BaseModel):
    overall_risk_score: int = Field(ge=0, le=100)
    overall_severity: RiskSeverity
    summary: str
    flags: List[RiskFlag]
    language: Literal["ar", "en"]


class DueDiligenceLevel(str, Enum):
    SIMPLIFIED = "Simplified"
    STANDARD = "Standard"
    ENHANCED = "Enhanced"


class KYCRiskFactor(BaseModel):
    factor: str
    severity: RiskSeverity


class KYCRiskProfile(BaseModel):
    """Structured output of a KYC/CDD customer risk assessment (Compliance
    Gen's 'automated KYC risk assessment' report type)."""
    customer_name: str
    risk_level: RiskSeverity
    due_diligence_level: DueDiligenceLevel
    risk_factors: List[KYCRiskFactor] = Field(default_factory=list)
    required_documents: List[str] = Field(default_factory=list)
    summary: str
    language: Literal["ar", "en"]
