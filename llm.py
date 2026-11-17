"""Gemini client used by CUE."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


class GeminiClient:
	"""Small stateful wrapper around the Google GenAI streaming API."""

	def __init__(
		self,
		api_key: str | None = None,
		model: str | None = None,
		memory_size: int = 10,
		client: Any | None = None,
	) -> None:
		if memory_size < 1:
			raise ValueError("memory_size must be at least 1")

		settings = None
		if api_key is None:
			from .config import load_settings

			settings = load_settings()
			api_key = settings.gemini_api_key
		if model is None:
			model = settings.gemini_model if settings is not None else "gemini-2.5-flash"

		self.model = model
		self.memory_size = memory_size
		self.memory: list[dict[str, str]] = []

		if client is None:
			from google import genai

			client = genai.Client(api_key=api_key)
		self.client = client

	def clear_memory(self) -> None:
		"""Remove all remembered conversation turns."""
		self.memory.clear()

	def ask(
		self,
		text: str | None = None,
		image_bytes: bytes | None = None,
		language: str = "python",
	) -> Iterator[str]:
		"""Stream Gemini's answer and remember the completed turn.

		``image_bytes`` is sent as an image/jpeg part. The caller can consume
		the returned generator directly, for example ``for chunk in ask(...)``.
		"""
		if not text and image_bytes is None:
			raise ValueError("text or image_bytes is required")

		prompt = text or "Describe this image."
		if language:
			prompt = f"{prompt}\n\nRespond using {language} where relevant."

		try:
			from google.genai import types

			contents = self._build_contents(types, prompt, image_bytes)
			response = self.client.models.generate_content_stream(
				model=self.model,
				contents=contents,
			)
			answer_parts: list[str] = []
			for chunk in response:
				chunk_text = getattr(chunk, "text", None)
				if chunk_text:
					answer_parts.append(chunk_text)
					yield chunk_text
		except Exception as error:
			message = self._friendly_error(error)
			yield message
			return

		answer = "".join(answer_parts).strip()
		self.memory.extend(
			[
				{"role": "user", "content": prompt},
				{"role": "model", "content": answer},
			]
		)
		del self.memory[:-self.memory_size * 2]

	def _build_contents(self, types: Any, prompt: str, image_bytes: bytes | None) -> list[Any]:
		"""Convert remembered turns and the current prompt to SDK contents."""
		contents = [
			types.Content(role=turn["role"], parts=[types.Part.from_text(text=turn["content"])])
			for turn in self.memory
		]
		parts = [types.Part.from_text(text=prompt)]
		if image_bytes is not None:
			parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
		contents.append(types.Content(role="user", parts=parts))
		return contents

	@staticmethod
	def _friendly_error(error: Exception) -> str:
		"""Return a useful message without exposing SDK internals."""
		status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
		error_text = str(error).lower()
		if status_code == 429 or "429" in error_text or "rate limit" in error_text:
			return "Gemini rate limit reached. Please wait a moment and try again."
		if isinstance(error, (TimeoutError, ConnectionError, OSError)) or any(
			word in error_text for word in ("network", "connection", "timeout", "timed out")
		):
			return "Could not reach Gemini. Check your internet connection and try again."
		return "Gemini could not process the request. Please try again."
