from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.profile import (
    CareerGoal,
    CareerSpecificity,
    FieldKey,
    ProfileRequest,
    ProfileResponse,
)
from app.services.student_interest_service import get_current_interests, upsert_interest


async def set_profile(db: AsyncSession, user: User, data: ProfileRequest) -> None:
    user.name = data.name
    user.current_grade = data.grade
    user.current_semester = data.semester

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
