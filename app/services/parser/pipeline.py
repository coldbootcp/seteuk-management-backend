import asyncio
from dataclasses import dataclass

from app.core.config import get_settings
from app.models.activity import ActivityCategory
from app.schemas.seteuk import ActivityItem, ParseError, SeteukAnalysisResult
from app.services.parser.attendance import parse_attendance, parse_attendance_from_tables
from app.services.parser.behavior import BehaviorBlock, parse_behavior_blocks
from app.services.parser.blocks import (
    infer_semester_from_single_semester_subjects,
    slice_subject_blocks,
)
from app.services.parser.career import parse_career_aspirations
from app.services.parser.changche import ChangcheBlock, parse_changche_blocks
from app.services.parser.enrollment import parse_freshman_academic_year
from app.services.parser.extract import extract_tables, extract_text, strip_noise
from app.services.parser.grades import (
    extract_subject_names_from_text,
    parse_academic_performance,
    parse_academic_performance_from_layout,
    parse_academic_performance_from_text,
)
from app.services.parser.identity import parse_student_name, parse_teacher_names
from app.services.parser.llm import get_provider, parse_block
from app.services.parser.prompts import (
    CHANGCHE_SYSTEM_PROMPT,
    HAENGBAL_SYSTEM_PROMPT,
    SETEUK_SYSTEM_PROMPT,
)
from app.services.parser.redact import sanitize_text
from app.services.parser.sections import split_sections
from app.services.parser.tables import (
    parse_volunteer_from_layout,
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


def _build_llm_jobs(
    sections: dict[str, str],
    subjects: list[str],
    tables: list,
    academic_performance: list,
) -> list[_LLMJob]:
    jobs: list[_LLMJob] = []

    seteuk_blocks = slice_subject_blocks(sections.get("교과학습발달상황", ""), subjects)
    # 세특 본문에 학기 표시가 없어도, 성적표에서 한 학기에만 개설된 것으로 확인된
    # 과목이면 그 학기로 채운다 — 문서 안의 다른 근거이지 추측이 아니다.
    seteuk_blocks = infer_semester_from_single_semester_subjects(
        seteuk_blocks, academic_performance
    )
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


def _volunteer_records(tables: list, pdf_bytes: bytes):
    """표로 읽어 시간이 채워지면 그대로 쓴다. 한 칸에 뭉쳐 오는 새 서식은 좌표로 다시 읽는다."""
    from_table = parse_volunteer_records(tables)
    if any(item.hours is not None for item in from_table):
        return from_table
    return parse_volunteer_from_layout(pdf_bytes) or from_table


def _scrub(value: str | None, student_name: str | None, teachers: list[str]) -> str | None:
    return sanitize_text(value, student_name, teachers) if value else value


async def parse_seteuk_pdf(pdf_bytes: bytes) -> SeteukAnalysisResult:
    text = strip_noise(extract_text(pdf_bytes))
    tables = extract_tables(pdf_bytes)
    sections = split_sections(text)

    attendance = parse_attendance_from_tables(tables) or parse_attendance(
        sections.get("출결상황", "")
    )
    # 셀 좌표로 읽는 쪽이 정본이다 — 학기가 행으로 놓이는 서식에서 텍스트 방식은 2학기 성적을
    # 1학기로 붙였다. 표를 못 읽는 문서일 때만 옛 텍스트 방식으로 돌아간다.
    academic_performance = (
        parse_academic_performance_from_layout(pdf_bytes)
        or parse_academic_performance_from_text(sections.get("교과학습발달상황", ""))
        or parse_academic_performance(sections.get("교과학습발달상황", ""))
    )
    student_name = parse_student_name(sections.get("인적사항", ""))
    teachers = parse_teacher_names(tables)
    freshman_academic_year = parse_freshman_academic_year(sections.get("학적사항", ""))
    volunteer_records = [
        item.model_copy(
            update={
                # 표 셀 원문(raw_date)에도 "(학교)○○고등학교"가 그대로 붙어 온다.
                "place": _scrub(item.place, student_name, teachers),
                "raw_date": _scrub(item.raw_date, student_name, teachers),
            }
        )
        for item in _volunteer_records(tables, pdf_bytes)
    ]
    career_activities = parse_career_aspirations(tables)

    subjects = sorted({item.subject for item in academic_performance}) or (
        extract_subject_names_from_text(sections.get("교과학습발달상황", ""))
    )
    jobs = _build_llm_jobs(sections, subjects, tables, academic_performance)
    # 외부 LLM으로 나가는 텍스트(그리고 source_block으로 저장되는 텍스트)에서 학생 이름과
    # 식별 패턴을 뺀다.
    for job in jobs:
        job.text = sanitize_text(job.text, student_name, teachers)
    llm_activities, errors = await _run_llm_jobs(jobs)

    return SeteukAnalysisResult(
        student_name=student_name,
        freshman_academic_year=freshman_academic_year,
        attendance=attendance,
        academic_performance=academic_performance,
        volunteer_records=volunteer_records,
        activities=career_activities + llm_activities,
        errors=errors,
    )
