"""모델 프로바이더 경계.

통합 결정 P-3: **프로바이더를 하네스 경계 뒤에 둔다.** 모델은 문장과 구조화 결과를
생성할 뿐이고, 어떤 학생 정보를 가져올지·어떤 규칙을 적용할지·무엇을 탈락시킬지는
하네스가 정한다. 그래야 프로바이더를 바꿔도 메모리와 평가 로직이 그대로 남는다.

`LLM_PROVIDER`로 고른다: `gemini`(Google Gemini, 운영) 또는 `deepseek`. 둘 다 OpenAI
호환 API라 `OpenAICompatibleProvider` 하나로 돌고, 업체별로 주소·키·모델만 다르다.
다른 프로바이더를 붙이려면 클래스를 하나 더하고 `_PROVIDERS`에 등록하면 되며, 호출부는
바뀌지 않는다.
"""

from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx
from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.llm.usage import record_usage

settings = get_settings()


class LLMProvider(Protocol):
    """하네스가 프로바이더에게 요구하는 전부. 이보다 넓어지면 경계가 새는 것이다."""

    name: str

    async def complete_json(self, system_prompt: str, user_content: str) -> str:
        """구조화 출력 한 번. JSON 문자열을 그대로 돌려주고, 검증은 호출부가 한다."""
        ...

    def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> AsyncIterator[Any]:
        """챗봇용 스트리밍. OpenAI 호환 청크를 흘려보낸다."""
        ...


class OpenAICompatibleProvider:
    """OpenAI 호환 Chat Completions API를 쓰는 프로바이더의 공통 구현.

    `max_retries=0`인 이유는 재시도 정책이 프로바이더가 아니라 하네스의 몫이기
    때문이다 — 파서는 블록 단위로 실패를 흡수하고, 구조화 호출은 3회 재시도하며,
    스트리밍은 아예 재시도하지 않는다(토큰을 일부 내보낸 뒤에는 되돌릴 수 없다).
    """

    name = ""

    def __init__(self, *, api_key: str | None, base_url: str, model: str) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self.model = model
        # 생기부 파싱은 블록을 15개까지 동시에 호출한다. 호출마다 클라이언트를 새로
        # 만들면 커넥션 풀을 공유하지 못하므로 인스턴스마다 하나만 만들어 재사용한다.
        self._cached: AsyncOpenAI | None = None

    def _client(self) -> AsyncOpenAI:
        if self._cached is None:
            self._cached = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                max_retries=0,
                # SDK 기본 connect 타임아웃(5초)은 블록 15개를 동시에 여는 파싱에서
                # 실제로 걸렸다 — 응답이 느린 게 아니라 연결을 맺지 못해 블록이
                # 통째로 버려졌다. 읽기는 넉넉히, 연결은 그보다 짧게 둔다.
                timeout=httpx.Timeout(
                    settings.llm_read_timeout_seconds,
                    connect=settings.llm_connect_timeout_seconds,
                ),
            )
        return self._cached

    async def complete_json(self, system_prompt: str, user_content: str) -> str:
        response = await self._client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
        await record_usage(self.name, self.model, "json", response.usage)
        return response.choices[0].message.content or ""

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> AsyncIterator[Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            # 사용량을 받으려면 켜야 한다. Gemini는 응답 조각에 붙여 주고, DeepSeek은
            # choices가 빈 마지막 조각으로 따로 보낸다 — 그 조각은 호출부에 넘기지 않는다.
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        stream = await self._client().chat.completions.create(**kwargs)
        last_usage = None
        async for chunk in stream:
            if getattr(chunk, "usage", None) is not None:
                last_usage = chunk.usage
            if not chunk.choices:
                continue
            yield chunk
        await record_usage(self.name, self.model, "stream", last_usage)


class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"

    def __init__(self) -> None:
        super().__init__(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
        )


class GeminiProvider(OpenAICompatibleProvider):
    """Google Gemini — OpenAI 호환 엔드포인트로 부른다."""

    name = "gemini"

    def __init__(self) -> None:
        super().__init__(
            api_key=settings.gemini_api_key,
            base_url=settings.gemini_base_url,
            model=settings.gemini_model,
        )


_PROVIDERS: dict[str, type] = {"deepseek": DeepSeekProvider, "gemini": GeminiProvider}


def get_provider() -> LLMProvider:
    name = (settings.llm_provider or "deepseek").strip().lower()
    provider_class = _PROVIDERS.get(name)
    if provider_class is None:
        raise ValueError(
            f"알 수 없는 LLM 프로바이더입니다: {name} (가능: {', '.join(_PROVIDERS)})"
        )
    return provider_class()
