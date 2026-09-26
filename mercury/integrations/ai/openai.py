from __future__ import annotations

from openai import OpenAI

from mercury.integrations.types import AnalysisResult
from mercury.intelligence.prompts import SUMMARY_INSTRUCTIONS
from mercury.intelligence.schemas import SummaryOutput


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        summary_model: str,
        embedding_model: str,
        dimensions: int,
        timeout: int,
    ):
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=1)
        self.summary_model = summary_model
        self.embedding_model = embedding_model
        self.dimensions = dimensions

    def summarize(self, *, text: str, message_ids: tuple[str, ...]) -> AnalysisResult:
        response_input = (
            f"Allowed message IDs: {list(message_ids)!r}\n<email_data>\n{text}\n</email_data>"
        )
        response = self.client.responses.parse(
            model=self.summary_model,
            instructions=SUMMARY_INSTRUCTIONS,
            input=response_input,
            text_format=SummaryOutput,
            store=False,
        )
        parsed = response.output_parsed
        if parsed is None or parsed.source_message_id not in {*message_ids, None}:
            raise ValueError("invalid_structured_output")
        usage = response.usage
        return AnalysisResult(
            **parsed.model_dump(mode="json"),
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
        )

    def embed(self, text: str) -> tuple[list[float], int]:
        response = self.client.embeddings.create(
            model=self.embedding_model,
            input=text,
            dimensions=self.dimensions,
            encoding_format="float",
        )
        vector = response.data[0].embedding
        if len(vector) != self.dimensions:
            raise ValueError("invalid_embedding_dimensions")
        return vector, response.usage.total_tokens
