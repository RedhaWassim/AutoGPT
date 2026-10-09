"""Normalized Eden AI expert model outputs used by the blocks (``output_format=compact``)."""

from typing import Any

from pydantic import BaseModel


class TextOutput(BaseModel):
    """OCR, translation and transcription results."""

    text: str


class ModerationOutput(BaseModel):
    nsfw_likelihood: int = 0
    items: list[dict[str, Any]] = []


class AudioOutput(BaseModel):
    audio_resource_url: str


class _Image(BaseModel):
    image_resource_url: str


class ImageOutput(BaseModel):
    image_resource_url: str | None = None
    items: list[_Image] = []

    def url(self) -> str:
        if self.image_resource_url:
            return self.image_resource_url
        if self.items:
            return self.items[0].image_resource_url
        raise ValueError("Eden AI returned no image")


class _Diarization(BaseModel):
    entries: list[dict[str, Any]] = []


class TranscriptionOutput(BaseModel):
    text: str
    diarization: _Diarization = _Diarization()
