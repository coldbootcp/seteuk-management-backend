import json
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.profile import (
    CareerGoal,
    CareerSpecificity,
    ClarifyQuestion,
    ClarifyRequest,
    ClarifyResponse,
    FieldKey,
    ProfileRequest,
    ProfileResponse,
    SuggestResponse,
)
from app.services.education_policy_service import get_policy_for_freshman_year
from app.services.llm import call_structured
from app.services.onboarding_prompts import CLARIFY_SYSTEM_PROMPT, SUGGEST_SYSTEM_PROMPT
from app.services.student_interest_service import get_current_interests, upsert_interest

# 이만큼 답을 받았으면 로드맵을 세우기에 충분하다고 보고 더 묻지 않는다.
MAX_CLARIFY_ANSWERS = 6

# LLM이 "성적을 알면 도움이 된다"고 일반론을 되풀이해도 온보딩의 역할을 넘지
# 못하게 한다. 이 값들은 실제 성적·수강 과목·활동 기록으로 진단할 내용이다.
_SUBJECT_PERFORMANCE_QUESTION = re.compile(
    r"(?:현재\s*)?성적\s*수준|현재\s*이수\s*중인.*과목|"
    r"(?:잘하는|어려운|약한|강점|약점).*과목|과목.*(?:강점|약점)|"
    r"기초\s*학습\s*수준|학습\s*수준",
    re.IGNORECASE,
)
_NONESSENTIAL_ONBOARDING_QUESTION = re.compile(
    r"동아리|캠프|대회|학교.*프로그램|외부.*프로그램|참여.*의향|"
    r"학습.*(?:선호|방식)|공부.*(?:선호|방식)|선호.*학습",
    re.IGNORECASE,
)
_RANK_MENTION = re.compile(r"(?<!\d)([1-9])\s*(?:~|∼|\-|–|—|부터|에서)\s*([1-9])\s*등급")


def _question_text(question: ClarifyQuestion) -> str:
    """모델 응답 전체를 한 문장으로 합쳐 코드 필터가 보는 재료를 만든다."""
    # ClarifyQuestion만 받지만, 호출 경계에서 타입이 흐트러져도 프롬프트 규칙을
    # 우회하지 않도록 방어적으로 읽는다.
    key = getattr(question, "key", "")
    label = getattr(question, "label", "")
    prompt = getattr(question, "question", "")
    options = getattr(question, "options", [])
    return " ".join([str(key), str(label), str(prompt), *[str(option) for option in options]])


def filter_clarification_questions(
    questions: list[ClarifyQuestion],
    *,
    rank_grade_scale: int | None,
) -> list[ClarifyQuestion]:
    """온보딩 역할 밖이거나 학생의 등급제와 맞지 않는 AI 질문을 버린다.

    프롬프트만으로는 실제 호출에서 9등급제 선택지가 새어 나왔기 때문에, 학생에게
    보이기 직전 서버에서 다시 막는다. 애매한 경우 선택지를 고쳐 내기보다 질문 전체를
    제거한다. 성적은 이미 성적 탭·학생부에서 정본으로 관리하기 때문이다.
    """
    accepted = []
    seen_prompts: set[str] = set()
    for question in questions:
        text = _question_text(question)
        normalized_prompt = re.sub(r"\s+", "", str(getattr(question, "question", "")))
        mentions_out_of_scale_rank = False
        if rank_grade_scale is not None:
            mentions_out_of_scale_rank = any(
                max(int(match.group(1)), int(match.group(2))) > rank_grade_scale
                for match in _RANK_MENTION.finditer(text)
            )
            # '6등급', '7등급'처럼 범위를 쓰지 않은 선택지도 막는다.
            mentions_out_of_scale_rank = mentions_out_of_scale_rank or any(
                int(value) > rank_grade_scale
                for value in re.findall(r"(?<!\d)([1-9])\s*등급", text)
            )

        if (
            _SUBJECT_PERFORMANCE_QUESTION.search(text)
            or _NONESSENTIAL_ONBOARDING_QUESTION.search(text)
            or mentions_out_of_scale_rank
            or not normalized_prompt
            or normalized_prompt in seen_prompts
        ):
            continue
        seen_prompts.add(normalized_prompt)
        accepted.append(question)
    return accepted


async def set_profile(db: AsyncSession, user: User, data: ProfileRequest) -> None:
    user.name = data.name
    user.current_grade = data.grade
    user.current_semester = data.semester
    # 생기부에서 읽어 둔 학적사항을 빈 온보딩 값으로 지우지 않는다. 학생이 직접
    # 넣은 숫자만 새 기준으로 확정한다.
    if data.freshman_academic_year is not None:
        user.freshman_academic_year = data.freshman_academic_year

    await upsert_interest(db, user.id, FieldKey.CAREER_GOAL, data.career_goal.model_dump())
    await upsert_interest(db, user.id, FieldKey.TARGET_DEPARTMENT, data.target_department)
    await upsert_interest(db, user.id, FieldKey.INTEREST_KEYWORDS, data.interest_keywords)
    await upsert_interest(
        db, user.id, FieldKey.CAREER_SPECIFICITY, data.career_specificity.model_dump()
    )
    await upsert_interest(
        db, user.id, FieldKey.PREFERRED_OUTPUT_TYPES, data.preferred_output_types
    )
    await upsert_interest(db, user.id, FieldKey.ACTIVITY_CHANNELS, data.activity_channels)
    await upsert_interest(db, user.id, FieldKey.ROADMAP_CONSTRAINTS, data.roadmap_constraints)
    await upsert_interest(
        db, user.id, FieldKey.SELF_ASSESSED_STRENGTHS, data.self_assessed_strengths
    )
    await upsert_interest(
        db, user.id, FieldKey.SELF_ASSESSED_WEAKNESSES, data.self_assessed_weaknesses
    )

    await db.commit()


async def get_profile(db: AsyncSession, user: User) -> ProfileResponse:
    interests = await get_current_interests(db, user.id)

    career_goal = interests.get(FieldKey.CAREER_GOAL)
    career_specificity = interests.get(FieldKey.CAREER_SPECIFICITY)

    return ProfileResponse(
        name=user.name,
        grade=user.current_grade,
        semester=user.current_semester,
        freshman_academic_year=user.freshman_academic_year,
        career_goal=CareerGoal.model_validate(career_goal) if career_goal else None,
        target_department=interests.get(FieldKey.TARGET_DEPARTMENT),
        interest_keywords=interests.get(FieldKey.INTEREST_KEYWORDS, []),
        career_specificity=(
            CareerSpecificity.model_validate(career_specificity) if career_specificity else None
        ),
        preferred_output_types=interests.get(FieldKey.PREFERRED_OUTPUT_TYPES, []),
        activity_channels=interests.get(FieldKey.ACTIVITY_CHANNELS, []),
        roadmap_constraints=interests.get(FieldKey.ROADMAP_CONSTRAINTS),
        self_assessed_strengths=interests.get(FieldKey.SELF_ASSESSED_STRENGTHS),
        self_assessed_weaknesses=interests.get(FieldKey.SELF_ASSESSED_WEAKNESSES),
    )


async def suggest_direction(career_goal: str) -> SuggestResponse:
    """진로 희망 문구 하나로 학과 후보와 관심 키워드를 제안한다.

    학생이 "진로 희망"에서 막혀 온보딩을 못 넘기는 경우가 많다. 제안은 제안일 뿐이라
    고르든 무시하든 자유고, 저장되는 것은 학생이 확정한 값이다.
    """
    return await call_structured(
        SUGGEST_SYSTEM_PROMPT,
        json.dumps({"career_goal": career_goal}, ensure_ascii=False),
        SuggestResponse,
    )


async def clarify_onboarding(db: AsyncSession, data: ClarifyRequest) -> ClarifyResponse:
    """아직 비었거나 막연한 항목에 대해 확인 질문을 만든다.

    이미 받은 답(`answers`)을 함께 넘겨야 같은 것을 다시 묻지 않는다 — 이걸 빼면
    학생이 답할 때마다 같은 질문이 되돌아와 온보딩이 끝나지 않는다.
    """
    # 질문을 몇 번이나 더 낼지는 모델에게 맡기지 않는다. 프롬프트로 "충분하면
    # 그만 물어라"라고 부탁해도 계속 새 질문을 만들어 내는 것을 실제로 관측했고,
    # 그러면 학생이 온보딩에서 빠져나오지 못한다.
    if len(data.answers) >= MAX_CLARIFY_ANSWERS:
        return ClarifyResponse(questions=[], complete=True)

    # 진로 축을 이미 적은 학생에게 "동아리 참여 의향", "학습 방식"처럼 다음
    # 상담에서 다뤄도 되는 정보를 캐묻지 않는다. 이 단계는 진로 정보가 비었을 때만
    # 최소 한 번 보완하는 안전장치이고, 개인화 대화의 대체재가 아니다.
    if data.career_goal and (data.target_department or data.interest_keywords):
        return ClarifyResponse(questions=[], complete=True)

    result = await call_structured(
        CLARIFY_SYSTEM_PROMPT,
        json.dumps(data.model_dump(), ensure_ascii=False),
        ClarifyResponse,
    )
    policy = await get_policy_for_freshman_year(db, data.freshman_academic_year)
    result.questions = filter_clarification_questions(
        result.questions,
        rank_grade_scale=policy.rank_grade_scale if policy else None,
    )[:1]
    result.complete = not result.questions
    return result
