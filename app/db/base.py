# ruff: noqa: I001
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Alembic autogenerate discovers models through this import side effect.
from app.models import academic_performance as _academic_performance  # noqa: E402, F401
from app.models import activity as _activity  # noqa: E402, F401
from app.models import activity_attachment as _activity_attachment  # noqa: E402, F401
from app.models import activity_review as _activity_review  # noqa: E402, F401
from app.models import activity_thread as _activity_thread  # noqa: E402, F401
from app.models import admission_catalog as _admission_catalog  # noqa: E402, F401
from app.models import admission_program_reference as _admission_program_reference  # noqa: E402, F401
from app.models import admission_university_snapshot as _admission_university_snapshot  # noqa: E402, F401
from app.models import admission_university_guide as _admission_university_guide  # noqa: E402, F401
from app.models import admission_writing_requirement as _admission_writing_requirement  # noqa: E402, F401
from app.models import admission_writing_requirement_status as _admission_writing_requirement_status  # noqa: E402, F401
from app.models import admission_writing_source_document as _admission_writing_source_document  # noqa: E402, F401
from app.models import application_preparation as _application_preparation  # noqa: E402, F401
from app.models import attendance as _attendance  # noqa: E402, F401
from app.models import award as _award  # noqa: E402, F401
from app.models import consultation as _consultation  # noqa: E402, F401
from app.models import conversation as _conversation  # noqa: E402, F401
from app.models import diagnosis as _diagnosis  # noqa: E402, F401
from app.models import education_policy as _education_policy  # noqa: E402, F401
from app.models import plan_item as _plan_item  # noqa: E402, F401
from app.models import reading_activity as _reading_activity  # noqa: E402, F401
from app.models import recommendation as _recommendation  # noqa: E402, F401
from app.models import recommendation_feedback as _recommendation_feedback  # noqa: E402, F401
from app.models import refresh_token as _refresh_token  # noqa: E402, F401
from app.models import roadmap as _roadmap  # noqa: E402, F401
from app.models import seteuk_upload as _seteuk_upload  # noqa: E402, F401
from app.models import student_interest as _student_interest  # noqa: E402, F401
from app.models import usage_event as _usage_event  # noqa: E402, F401
from app.models import user as _user  # noqa: E402, F401
from app.models import volunteer_record as _volunteer_record  # noqa: E402, F401
