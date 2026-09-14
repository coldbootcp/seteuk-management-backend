import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AdmissionWritingRequirementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source_admission_year: int
    prompt_order: int
    prompt_label: str
    prompt_text: str
    min_characters: int | None
    max_characters: int | None
    character_unit: str
    submission_method: str | None
    source_url: str
    source_status: str
    verified_at: datetime | None


class AdmissionWritingRequirementStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    requirement_status: str
    source_admission_year: int | None
    source_url: str | None
    source_status: str | None
    verification_note: str | None
    verified_at: datetime | None


class AdmissionWritingRequirementsResponse(BaseModel):
    status: AdmissionWritingRequirementStatusRead
    requirements: list[AdmissionWritingRequirementRead]
