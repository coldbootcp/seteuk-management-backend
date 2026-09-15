"""거래성 이메일 발송(이메일 인증, 비밀번호 재설정).

Resend REST API를 httpx로 직접 호출한다 — 카카오 로그인이 SDK 없이 httpx로
공개 API를 부르는 것과 같은 방식이라 별도 의존성을 늘리지 않는다.

RESEND_API_KEY가 없으면(로컬 개발 등) 실제로 보내지 않고 로그로만 남긴다 —
프론트엔드가 카카오 키 없을 때 버튼을 '준비 중'으로 비활성화하는 것과 같은
자세: 설정이 없다고 예외를 던져 흐름을 막지 않는다.
"""

import httpx
import structlog

from app.core.config import get_settings

logger = structlog.get_logger()

RESEND_API_URL = "https://api.resend.com/emails"
RESEND_TIMEOUT_SECONDS = 10

# 프론트엔드(app/globals.css)의 --color-brand-* 토큰과 동일 — 화면과 메일의
# 브랜드 색이 어긋나지 않게 값을 그대로 옮긴다.
_BRAND_600 = "#1B64DA"
_BRAND_50 = "#F0F7FF"
_INK = "#0B0F19"
_MUTED = "#6B7280"
_BORDER = "#E5E7EB"
_PAGE_BG = "#F8F9FA"

# base64 데이터 URI로 인라인 삽입해봤지만 지메일 웹(앱은 됨)이 인라인
# 이미지를 막아 실제로 깨지는 것을 확인해 되돌렸다. 프론트엔드가 아직 실제
# 도메인에 배포되지 않아 `{frontend_base_url}/logo.png`도 못 쓰는 지금은,
# 이미 공개 저장소에 커밋된 파일을 GitHub raw로 직접 가리킨다 — 배포되면
# 이 상수를 `{settings.frontend_base_url}/logo.png`로 바꾸는 게 더 낫다
# (raw.githubusercontent.com은 이런 용도로 장기간 의존할 CDN은 아니다).
_LOGO_URL = (
    "https://raw.githubusercontent.com/coldbootcp/seteuk-management-frontend/main/public/logo.png"
)


async def _send(to: str, subject: str, html: str) -> None:
    settings = get_settings()
    if not settings.resend_api_key:
        logger.info("email not sent (no RESEND_API_KEY configured)", to=to, subject=subject)
        return

    async with httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS) as client:
        response = await client.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.email_from, "to": [to], "subject": subject, "html": html},
        )
    if response.status_code >= 400:
        # 이메일 발송 실패로 가입·재설정 흐름 전체를 막지 않는다 — 사용자는
        # 재전송을 요청할 수 있어야 하므로 로그만 남기고 조용히 넘어간다.
        logger.error(
            "email send failed",
            to=to,
            subject=subject,
            status=response.status_code,
            body=response.text,
        )
    else:
        logger.info("email sent", to=to, subject=subject, resend_id=response.json().get("id"))


def _email_shell(
    *, preheader: str, badge: str, heading: str, account_email: str, body_html: str, footer_note: str
) -> str:
    """모든 거래성 메일이 공유하는 틀.

    구글·Vercel의 알림 메일을 참고했다: 로고로 브랜드부터 확인시키고, "이건
    어느 계정 얘기인지"는 문장 속에 억지로 끼워 넣지 않고 계정 이메일을 뱃지로
    따로 떼어 보여준다(긴 이메일 주소가 한국어 문장 중간에 끼면 읽기 어색해서),
    본문은 짧게, 다음 행동(버튼)은 하나만, 아래에 보안 안내와 사업자 정보를
    남긴다. `preheader`는 받은편지함 목록에서 제목 옆에 살짝 보이는 미리보기
    문장 — 화면엔 숨겨 두고 그 용도로만 쓴다.
    """
    return f"""\
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_PAGE_BG};padding:40px 16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;">
  <tr>
    <td align="center">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="width:480px;max-width:100%;background:#ffffff;border:1px solid {_BORDER};border-radius:20px;overflow:hidden;">
        <tr>
          <td style="padding:36px 40px 28px;text-align:center;">
            <img src="{_LOGO_URL}" width="40" height="40" alt="세특연구소"
                 style="display:block;margin:0 auto 10px;border-radius:9px;" />
            <div style="font-size:14px;font-weight:800;color:{_INK};letter-spacing:-0.2px;">세특연구소</div>
          </td>
        </tr>
        <tr>
          <td style="padding:0 40px;">
            <div style="border-top:1px solid {_BORDER};"></div>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 40px 8px;text-align:center;">
            <span style="display:inline-block;background:{_BRAND_50};color:{_BRAND_600};font-size:11px;font-weight:700;padding:4px 10px;border-radius:999px;">{badge}</span>
          </td>
        </tr>
        <tr>
          <td style="padding:10px 40px 0;text-align:center;">
            <h1 style="margin:0;font-size:20px;font-weight:800;color:{_INK};letter-spacing:-0.3px;">{heading}</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:14px 40px 0;text-align:center;">
            <span style="display:inline-block;background:#F3F4F6;color:{_MUTED};font-size:12px;font-weight:600;padding:6px 12px;border-radius:8px;">{account_email}</span>
          </td>
        </tr>
        <tr>
          <td style="padding:18px 40px 8px;">
            {body_html}
          </td>
        </tr>
        <tr>
          <td style="padding:28px 40px 0;">
            <div style="border-top:1px solid {_BORDER};"></div>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 40px 36px;">
            <p style="margin:0 0 12px;font-size:12px;line-height:1.7;color:{_MUTED};">{footer_note}</p>
            <p style="margin:0;font-size:11px;line-height:1.7;color:#9CA3AF;">
              coldboot (세특연구소) · 대표 강필중 · 사업자등록번호 252-09-03289<br>
              서울시 동대문구 왕산로 69-2
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
"""


def _button(url: str, label: str) -> str:
    return f"""\
<div style="text-align:center;margin:24px 0 8px;">
  <a href="{url}" style="display:inline-block;background:{_BRAND_600};color:#ffffff;
     padding:13px 28px;border-radius:12px;text-decoration:none;font-weight:700;
     font-size:14px;">{label}</a>
</div>
<p style="margin:16px 0 0;font-size:11px;line-height:1.6;color:#9CA3AF;text-align:center;
   word-break:break-all;">버튼이 안 열리면 이 링크를 붙여넣으세요<br>{url}</p>
"""


async def send_verification_email(to: str, token: str) -> None:
    settings = get_settings()
    url = f"{settings.frontend_base_url}/verify-email?token={token}"
    body = f"""\
<p style="margin:0;font-size:14px;line-height:1.7;color:{_MUTED};text-align:center;">
  가입해주셔서 감사합니다. 아래 버튼을 눌러 이메일 인증을 마치면 바로 이용하실 수 있습니다.
</p>
{_button(url, "이메일 인증하기")}
"""
    await _send(
        to,
        "[세특연구소] 이메일 인증을 완료해주세요",
        _email_shell(
            preheader="한 번만 누르면 세특연구소를 바로 시작할 수 있어요.",
            badge="이메일 인증",
            heading="가입을 환영합니다",
            account_email=to,
            body_html=body,
            footer_note=(
                "본인이 가입하지 않으셨다면 이 메일을 무시하셔도 됩니다 — "
                f"인증 링크는 {settings.email_verification_token_expire_hours}시간 동안만 유효하며, "
                "누르지 않으면 계정에는 아무 변화도 없습니다."
            ),
        ),
    )


async def send_password_reset_email(to: str, token: str) -> None:
    settings = get_settings()
    url = f"{settings.frontend_base_url}/reset-password?token={token}"
    body = f"""\
<p style="margin:0;font-size:14px;line-height:1.7;color:{_MUTED};text-align:center;">
  이 계정의 비밀번호 재설정을 요청하셨습니다. 아래 버튼을 눌러 새 비밀번호를 설정해주세요.
</p>
{_button(url, "비밀번호 재설정하기")}
"""
    await _send(
        to,
        "[세특연구소] 비밀번호 재설정",
        _email_shell(
            preheader="본인이 요청하지 않았다면 이 메일을 무시하셔도 안전합니다.",
            badge="비밀번호 재설정",
            heading="비밀번호를 재설정해주세요",
            account_email=to,
            body_html=body,
            footer_note=(
                "본인이 요청하지 않으셨다면 이 메일을 무시하세요 — 비밀번호는 바뀌지 않습니다. "
                f"링크는 {settings.password_reset_token_expire_minutes}분 동안만, 한 번만 사용할 수 있습니다."
            ),
        ),
    )
