from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ReportMeta(BaseModel):
    source_path: Optional[str] = None
    source_url: Optional[str] = None
    compact_preview: Optional[str] = None
    original_bytes: Optional[int] = None
    compact_bytes: Optional[int] = None


class AnalyzeRequest(BaseModel):
    contract_text: str = Field(..., description="Текст договора/выдержки")
    jurisdiction: str = Field("RU")
    contract_type: Optional[str] = None
    language: str = Field("ru")
    effective_date: Optional[str] = None
    model: Optional[str] = None
    max_tokens: Optional[int] = 1024
    report_format: Optional[str] = Field(
        default=None, description="Формат итогового отчёта (например, 'html')"
    )
    report_save: bool = Field(
        default=False, description="Сохранять ли итоговый отчёт на диск"
    )
    report_inline: bool = Field(
        default=False, description="Возвращать ли готовый отчёт в теле ответа"
    )
    report_name: Optional[str] = Field(
        default=None, description="Базовое имя файла для сохранения отчёта"
    )
    report_meta: Optional[ReportMeta] = Field(
        default=None, description="Дополнительные данные для генерации отчёта"
    )

# Internal
class SectionScore(BaseModel):
    key: str
    raw: int = Field(ge=0, le=5)
    comment: Optional[str] = None

class Issue(BaseModel):
    section: str
    severity: str  # high|medium|low
    text: str
    suggestion: Optional[str] = None

class SourceItem(BaseModel):
    act_title: str
    article: Optional[str] = None
    part: Optional[str] = None
    point: Optional[str] = None
    revision_date: Optional[str] = None
    jurisdiction: str
    text: str
    local_ref: Optional[str] = None
    source_hash: str

class FocusItem(BaseModel):
    key: str
    title: str
    raw: int
    score: float
    why: str
    suggestion: Optional[str] = None

# Summaries
class DocumentOverview(BaseModel):
    summary: str
    parties: Optional[str] = None
    subject: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)


class NarrativeBlock(BaseModel):
    summary: str
    analysis_points: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


# Responses
class AnalyzeResponse(BaseModel):
    score_total: int
    score_text: str
    verdict: str
    risk_color: str
    summary: str
    focus_summary: str
    top_focus: List[FocusItem]
    jurisdiction: str
    issues: List[Issue]
    section_scores: List[Dict[str, Any]]
    sources: List[SourceItem]
    business_score_total: int
    business_score_text: str
    business_verdict: str
    business_risk_color: str
    business_summary: str
    business_focus_summary: str
    business_top_focus: List[FocusItem]
    business_issues: List[Issue]
    business_section_scores: List[Dict[str, Any]]
    overview: DocumentOverview
    law_narrative: NarrativeBlock
    business_narrative: NarrativeBlock
    report_path: Optional[str] = Field(
        default=None, description="Полный путь до сохранённого HTML-отчёта"
    )
    report_html: Optional[str] = Field(
        default=None, description="Готовая HTML-вёрстка, если запрошен inline-ответ"
    )

# Ingest
class IngestItem(BaseModel):
    act_id: str
    act_title: str
    article: Optional[str] = None
    part: Optional[str] = None
    point: Optional[str] = None
    revision_date: Optional[str] = None  # формат YYYY-MM-DD, если есть
    jurisdiction: str = "RU"
    text: str
    local_ref: str

class IngestPayload(BaseModel):
    items: List[IngestItem] = Field(default_factory=list)
