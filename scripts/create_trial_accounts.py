"""체험용 계정을 만드는 SQL을 출력한다 — 이메일 인증을 건너뛴 상태로(email_verified_at = now()).

가입 API는 이메일 인증 메일을 보내고 비밀번호 강도(영문+숫자 8자 이상)도 검사한다. 소유자가
직접 나눠 주는 체험 계정에는 맞지 않아, DB에 직접 넣을 SQL을 만든다. **이 스크립트는 DB에
연결하지 않는다** — 비밀번호를 bcrypt 해시로 바꾼 INSERT 문만 출력하고, 실행은 사람이
`psql`에서 한다(원문 비밀번호는 출력에도 서버에도 남지 않는다).

    # `이름,이메일,비밀번호` 줄들 또는 `- 이름 / 아이디: … / 비밀번호: …` 묶음을
    # 저장소 밖 파일(.txt/.csv/.rtf)에 둔다. 끝나면 지운다.
    uv run python scripts/create_trial_accounts.py ~/trial_accounts.csv > ~/trial_accounts.sql

이미 있는 이메일은 ON CONFLICT로 건너뛴다.
"""

import csv
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import hash_password  # noqa: E402


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _read_text(path: Path) -> str:
    # TextEdit 기본 저장 형식(.rtf)은 macOS textutil로 일반 글자로 바꾼다.
    if path.suffix.lower() == ".rtf":
        return subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    return path.read_text(encoding="utf-8")


def _parse_rows(text: str) -> list[list[str]]:
    """`이름,이메일,비밀번호` 줄들, 또는 `- 이름 / 아이디: … / 비밀번호: …` 묶음 둘 다 읽는다."""
    if "아이디" in text and "비밀번호" in text:
        rows: list[list[str]] = []
        name = ""
        email = ""
        for line in text.splitlines():
            line = line.strip().lstrip("-*• ").strip()
            if not line:
                continue
            if m := re.match(r"아이디\s*[:：]\s*(\S+)", line):
                email = m.group(1)
            elif m := re.match(r"비밀번호\s*[:：]\s*(\S+)", line):
                rows.append([name, email, m.group(1)])
                name = email = ""
            else:
                name = line
        return rows
    return [row for row in csv.reader(text.splitlines()) if row and any(c.strip() for c in row)]


def main(path: Path) -> None:
    rows = _parse_rows(_read_text(path))

    print("BEGIN;")
    for row in rows:
        if len(row) != 3:
            raise SystemExit(
                f"한 줄은 `이름,이메일,비밀번호`여야 합니다: {len(row)}칸짜리 줄이 있습니다"
            )
        name, email, password = (cell.strip() for cell in row)
        print(
            "INSERT INTO users (id, email, name, password_hash, email_verified_at) "
            f"VALUES (gen_random_uuid(), {_quote(email.lower())}, {_quote(name)}, "
            f"{_quote(hash_password(password))}, now()) ON CONFLICT (email) DO NOTHING;"
        )
    print("COMMIT;")
    print(f"-- {len(rows)}명", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("사용법: create_trial_accounts.py <csv>")
    main(Path(sys.argv[1]))
