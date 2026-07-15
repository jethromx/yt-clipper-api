from __future__ import annotations

from typing import Any

from yt_clipper.domain.exceptions import (
    CaptionGenerationError,
    CaptionGeneratorUnavailableError,
)
from yt_clipper.domain.video import TikTokCaption, VideoMetadata

_TOOL_NAME = "emit_tiktok_caption"
_MAX_CAPTION_CHARS = 150
_MAX_HASHTAGS = 8
_MAX_DESCRIPTION_CHARS = 1000

_SYSTEM_PROMPT = (
    "Eres un experto en marketing de TikTok. Escribes descripciones cortas, "
    "con gancho, en espanol neutro, y hashtags relevantes. Responde SIEMPRE "
    "usando la herramienta emit_tiktok_caption."
)

_TOOL = {
    "name": _TOOL_NAME,
    "description": "Devuelve la descripcion corta y los hashtags para TikTok.",
    "input_schema": {
        "type": "object",
        "properties": {
            "caption": {
                "type": "string",
                "description": "Descripcion corta en espanol, maximo 150 caracteres.",
            },
            "hashtags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Entre 6 y 8 hashtags en espanol.",
            },
        },
        "required": ["caption", "hashtags"],
    },
}


class UnavailableCaptionGenerator:
    def generate(self, metadata: VideoMetadata) -> TikTokCaption:
        raise CaptionGeneratorUnavailableError(
            "Configura ANTHROPIC_API_KEY para generar captions de TikTok"
        )


class AnthropicCaptionGenerator:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model
        if client is not None:
            self._client = client
        else:
            import anthropic

            self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, metadata: VideoMetadata) -> TikTokCaption:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=512,
                system=_SYSTEM_PROMPT,
                tools=[_TOOL],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[{"role": "user", "content": self._build_prompt(metadata)}],
            )
        except Exception as exc:  # SDK/network failures
            raise CaptionGenerationError(str(exc)) from exc

        payload = self._extract_tool_input(response)
        caption = str(payload.get("caption") or "").strip()[:_MAX_CAPTION_CHARS]
        hashtags = self._normalize_hashtags(payload.get("hashtags") or [])
        if not caption:
            raise CaptionGenerationError("El proveedor no devolvio caption")
        return TikTokCaption(caption=caption, hashtags=hashtags)

    @staticmethod
    def _build_prompt(metadata: VideoMetadata) -> str:
        description = (metadata.description or "")[:_MAX_DESCRIPTION_CHARS]
        tags = ", ".join(metadata.tags[:20])
        return (
            "Genera una descripcion corta y hashtags para TikTok a partir de este "
            f"video de YouTube.\nTitulo: {metadata.title}\n"
            f"Descripcion: {description}\nTags: {tags}"
        )

    @staticmethod
    def _extract_tool_input(response: Any) -> dict[str, Any]:
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
                return dict(block.input)
        raise CaptionGenerationError("El proveedor no uso la herramienta esperada")

    @staticmethod
    def _normalize_hashtags(raw: list[Any]) -> list[str]:
        seen: list[str] = []
        for item in raw:
            tag = str(item).strip().replace(" ", "")
            if not tag:
                continue
            if not tag.startswith("#"):
                tag = f"#{tag}"
            if tag.lower() not in {existing.lower() for existing in seen}:
                seen.append(tag)
            if len(seen) >= _MAX_HASHTAGS:
                break
        return seen
