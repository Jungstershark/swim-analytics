"""
Pydantic schemas for FastAPI request/response models.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class PaginationInfo(BaseModel):
    page: int
    limit: int
    total: int
    total_pages: int


# ---------------------------------------------------------------------------
# Swimmer
# ---------------------------------------------------------------------------

class SwimmerBase(BaseModel):
    name: str
    age: Optional[int] = None
    team: Optional[str] = None


class SwimmerBrief(SwimmerBase):
    id: int
    model_config = {"from_attributes": True}


class SwimmerListItem(SwimmerBrief):
    meet_count: int = 0
    result_count: int = 0
    latest_meet: Optional[str] = None


class PersonalBest(BaseModel):
    event: str
    time: str
    time_in_seconds: Optional[float] = None
    meet: str
    date: str


class SwimmerDetail(SwimmerBrief):
    personal_bests: list[PersonalBest] = []
    recent_results: list["ResultListItem"] = []
    stats: dict = {}


class SwimmerListResponse(BaseModel):
    data: list[SwimmerListItem]
    pagination: PaginationInfo


# ---------------------------------------------------------------------------
# Meet
# ---------------------------------------------------------------------------

class MeetBase(BaseModel):
    name: str
    date: datetime  # startDate, mapped to "date" column
    end_date: Optional[datetime] = None
    location: Optional[str] = None


class MeetBrief(MeetBase):
    id: int
    model_config = {"from_attributes": True}


class MeetListItem(MeetBrief):
    result_count: int = 0
    swimmer_count: int = 0


class MeetListResponse(BaseModel):
    data: list[MeetListItem]
    pagination: PaginationInfo


class EventGroup(BaseModel):
    name: str
    results: list["ResultBrief"] = []


class MeetDetail(MeetBrief):
    events: list[EventGroup] = []


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

class ResultBase(BaseModel):
    """Slim result — used in list views (no splits/reaction_time to keep payloads small)."""
    event: str
    time: Optional[str] = None
    seed_time: Optional[str] = None
    placement: Optional[int] = None
    is_dq: bool = False
    dq_code: Optional[str] = None
    dq_description: Optional[str] = None
    is_guest: bool = False
    qualifier: Optional[str] = None
    round: Optional[str] = None
    swim_date: Optional[datetime] = None


class ResultBrief(ResultBase):
    id: int
    swimmer: SwimmerBrief
    model_config = {"from_attributes": True}


class ResultListItem(ResultBase):
    id: int
    swimmer: SwimmerBrief
    meet: MeetBrief
    model_config = {"from_attributes": True}


class ResultListResponse(BaseModel):
    data: list[ResultListItem]
    pagination: PaginationInfo


class ResultDetail(ResultBase):
    """Full result — includes splits and reaction time, fetched on demand."""
    id: int
    reaction_time: Optional[str] = None
    splits: Optional[str] = None
    swimmer: SwimmerBrief
    meet: MeetBrief
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

class PreviewResultRow(BaseModel):
    """A single result row in the upload preview."""
    event: str
    name: str
    age: Optional[int] = None
    team: str
    time: Optional[str] = None
    seed_time: Optional[str] = None
    round: str
    placement: Optional[int] = None
    is_dq: bool = False
    is_guest: bool = False
    qualifier: Optional[str] = None


class ConfidenceCheck(BaseModel):
    name: str
    passed: bool


class PreviewEventGroup(BaseModel):
    """An event with its results in the upload preview."""
    event: str
    round: str
    result_count: int
    results: list[PreviewResultRow]


class UploadPreviewResponse(BaseModel):
    """Response from /api/upload/preview — parsed data without DB insertion."""
    parser_format: str
    confidence_score: float
    confidence_passed: bool
    confidence_checks: list[ConfidenceCheck]
    unmatched_lines: list[str]
    meet_name: str
    meet_dates: Optional[str] = None
    session: Optional[str] = None
    events_count: int
    results_count: int
    swimmers_count: int
    events: list[PreviewEventGroup]


class UploadResponse(BaseModel):
    success: bool
    meet: MeetBrief
    results_count: int
    swimmers_count: int
    events_count: int
    duplicates_skipped: int = 0
    errors: list[str] = []


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class ProgressionDataPoint(BaseModel):
    date: str
    time: str
    time_in_seconds: float
    meet: str
    placement: Optional[int] = None


class ProgressionResponse(BaseModel):
    swimmer: SwimmerBrief
    event: str
    data_points: list[ProgressionDataPoint]
    summary: dict


# Resolve forward references
SwimmerDetail.model_rebuild()
MeetDetail.model_rebuild()
