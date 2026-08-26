from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Alembic autogenerate discovers models through this import side effect.
from app.models import academic_performance as _academic_performance  # noqa: E402, F401
from app.models import activity as _activity  # noqa: E402, F401
from app.models import attendance as _attendance  # noqa: E402, F401
from app.models import award as _award  # noqa: E402, F401
from app.models import reading_activity as _reading_activity  # noqa: E402, F401
from app.models import seteuk_upload as _seteuk_upload  # noqa: E402, F401
from app.models import user as _user  # noqa: E402, F401
from app.models import volunteer_record as _volunteer_record  # noqa: E402, F401
