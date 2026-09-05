import asyncio
from dataclasses import dataclass

from app.core.config import get_settings
from app.models.activity import ActivityCategory
from app.schemas.seteuk import ActivityItem, ParseError, SeteukAnalysisResult
from app.services.parser.attendance import parse_attendance, parse_attendance_from_tables
from app.services.parser.behavior import BehaviorBlock, parse_behavior_blocks
from app.services.parser.blocks import slice_subject_blocks
from app.services.parser.career import parse_career_aspirations
from app.services.parser.changche import ChangcheBlock, parse_changche_blocks
from app.services.parser.enrollment import parse_freshman_academic_year
from app.services.parser.extract import extract_tables, extract_text, strip_noise
from app.services.parser.grades import (
    extract_subject_names_from_text,
    parse_academic_performance,
    parse_academic_performance_from_text,
)
from app.services.parser.llm import get_provider, parse_block
from app.services.parser.prompts import (
    CHANGCHE_SYSTEM_PROMPT,
    HAENGBAL_SYSTEM_PROMPT,
    SETEUK_SYSTEM_PROMPT,
)
from app.services.parser.sections import split_sections
from app.services.parser.tables import (
    parse_awards,
    parse_reading_activities,
    parse_volunteer_records,
)

settings = get_settings()


@dataclass
class _LLMJob:
    block_id: str
    grade: int
    semester: int | None
    subject: str | None
    text: str
    system_prompt: str
    category: ActivityCategory


def _build_llm_jobs(sections: dict[str, str], subjects: list[str], tables: list) -> list[_LLMJob]:
    jobs: list[_LLMJob] = []

    seteuk_blocks = slice_subject_blocks(sections.get("교과학습발달상황", ""), subjects)
    for i, block in enumerate(seteuk_blocks):
        block_id = f"activities_{block.grade}-{block.semester or 0}_과목세부특기사항_{i:02d}"
        jobs.append(
            _LLMJob(
                block_id,
                block.grade,
                block.semester,
                block.subject,
                block.text,
                SETEUK_SYSTEM_PROMPT,
                ActivityCategory.SUBJECT_SPECIALTY,
            )
        )

    changche_blocks: list[ChangcheBlock] = parse_changche_blocks(tables)
    for i, block in enumerate(changche_blocks):
        block_id = f"activities_{block.grade}-0_{block.category.value}_{i:02d}"
        jobs.append(
            _LLMJob(
                block_id,
                block.grade,
                None,
                None,
                block.text,
                CHANGCHE_SYSTEM_PROMPT,
                block.category,
            )
        )

    behavior_blocks: list[BehaviorBlock] = parse_behavior_blocks(tables)
    for i, block in enumerate(behavior_blocks):
        block_id = f"activities_{block.grade}-0_행동특성및종합의견_{i:02d}"
        jobs.append(
            _LLMJob(
                block_id,
                block.grade,
                None,
                None,
                block.text,
                HAENGBAL_SYSTEM_PROMPT,
                ActivityCategory.BEHAVIOR,
            )
        )

    return jobs


async def _run_llm_jobs(jobs: list[_LLMJob]) -> tuple[list[ActivityItem], list[ParseError]]:
    if not jobs:
        return [], []

    client = get_provider()
    semaphore = asyncio.Semaphore(settings.seteuk_llm_concurrency)

    async def _run(job: _LLMJob) -> tuple[_LLMJob, tuple]:
        async with semaphore:
            result = await parse_block(client, job.system_prompt, job.block_id, job.text)
            return job, result

    results = await asyncio.gather(*(_run(job) for job in jobs))

    activities: list[ActivityItem] = []
    errors: list[ParseError] = []
    for job, (draft_list, error_reason) in results:
        if draft_list is None:
            errors.append(ParseError(block_id=job.block_id, reason=error_reason or "unknown error"))
            continue

        for draft in draft_list.items:
            activities.append(
                ActivityItem(
                    grade=job.grade,
                    semester=job.semester,
                    # The table already tells us the category for changche/behavior
                    # blocks — job.category is authoritative there, not a guess the
                    # LLM has to make (see changche.py). Only 세특 leaves it to draft.
                    activity_category=job.category,
                    subject=job.subject,
                    activity_name=draft.activity_name,
                    activity_type=draft.activity_type,
                    role=draft.role,
                    description=draft.description,
                    keywords=draft.keywords,
                    source_block=job.text,
                )
            )

    return activities, errors


async def parse_seteuk_pdf(pdf_bytes: bytes) -> SeteukAnalysisResult:
    text = strip_noise(extract_text(pdf_bytes))
    tables = extract_tables(pdf_bytes)
    sections = split_sections(text)

    attendance = parse_attendance_from_tables(tables) or parse_attendance(
        sections.get("출결상황", "")
    )
    academic_performance = parse_academic_performance_from_text(
        sections.get("교과학습발달상황", "")
    ) or parse_academic_performance(sections.get("교과학습발달상황", ""))
    # 날짜만 있는 기록(수상)에 학년을 붙이려면 기준점이 먼저 있어야 한다.
    freshman_academic_year = parse_freshman_academic_year(sections.get("학적사항", ""))
    awards = parse_awards(tables, freshman_academic_year)
    volunteer_records = parse_volunteer_records(tables)
    reading_activities = parse_reading_activities(tables)
    career_activities = parse_career_aspirations(tables)

    subjects = extract_subject_names_from_text(sections.get("교과학습발달상황", "")) or sorted(
        {item.subject for item in academic_performance}
    )
    jobs = _build_llm_jobs(sections, subjects, tables)
    llm_activities, errors = await _run_llm_jobs(jobs)

    return SeteukAnalysisResult(
        freshman_academic_year=freshman_academic_year,
        attendance=attendance,
        academic_performance=academic_performance,
        reading_activities=reading_activities,
        awards=awards,
        volunteer_records=volunteer_records,
        activities=career_activities + llm_activities,
        errors=errors,
    )
