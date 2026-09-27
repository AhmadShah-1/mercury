from __future__ import annotations

from openai import OpenAI
from pydantic import ValidationError

from mercury.integrations.types import AnalysisResult, BucketSuggestion, InvalidProviderOutput
from mercury.intelligence.prompts import BUCKET_NAMING_INSTRUCTIONS, SUMMARY_INSTRUCTIONS
from mercury.intelligence.schemas import BucketSuggestionOutput, SummaryOutput


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
        try:
            response = self.client.responses.parse(
                model=self.summary_model,
                instructions=SUMMARY_INSTRUCTIONS,
                input=response_input,
                text_format=SummaryOutput,
                store=False,
            )
        except ValidationError:
            raise InvalidProviderOutput("invalid_structured_output") from None
        parsed = response.output_parsed
        if parsed is None:
            raise InvalidProviderOutput("invalid_structured_output")
        result = parsed.model_dump(mode="json")
        if parsed.source_message_id not in {*message_ids, None}:
            # A citation outside this thread is never shown; keep the summary, drop the pointer,
            # and flag it as uncertain rather than discarding an otherwise valid analysis.
            result.update(source_message_id=None, uncertain=True)
        usage = response.usage
        return AnalysisResult(
            **result,
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
            raise InvalidProviderOutput("invalid_embedding_dimensions")
        return vector, response.usage.total_tokens

    def suggest_bucket(self, *, descriptions: tuple[str, ...]) -> BucketSuggestion:
        bounded = descriptions[:5]
        response_input = "\n\n".join(
            f'<description index="{index}">\n{description[:900]}\n</description>'
            for index, description in enumerate(bounded, start=1)
        )
        try:
            response = self.client.responses.parse(
                model=self.summary_model,
                instructions=BUCKET_NAMING_INSTRUCTIONS,
                input=response_input,
                text_format=BucketSuggestionOutput,
                store=False,
            )
        except ValidationError:
            # For example a name outside two to four words; the caller skips this one group.
            raise InvalidProviderOutput("invalid_structured_output") from None
        parsed = response.output_parsed
        if parsed is None:
            raise InvalidProviderOutput("invalid_structured_output")
        usage = response.usage
        return BucketSuggestion(
            **parsed.model_dump(mode="json"),
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
        )
