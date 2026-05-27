import json
import time
from typing import Any

from documentai_api.config.constants import (
    ConfigDefaults,
    PreclassificationCategory,
    PreClassificationDefaults,
)
from documentai_api.config.env import get_aws_config
from documentai_api.logging import get_logger
from documentai_api.services.bedrock import invoke_model
from documentai_api.utils.dto import BedrockClassificationResult
from documentai_api.utils.ssm import get_parameter_value

logger = get_logger(__name__)

DEFAULT_PRECLASSIFICATION_MODEL_ID = PreClassificationDefaults.MODEL_ID
DEFAULT_PRECLASSIFICATION_PROMPT = PreClassificationDefaults.PROMPT
SUPPORTED_CLASSIFICATION_TYPES = PreClassificationDefaults.SUPPORTED_CONTENT_TYPES


def _get_model_id() -> str:
    param_name = get_aws_config().bedrock_classification_model_id_param
    if not param_name:
        return DEFAULT_PRECLASSIFICATION_MODEL_ID
    return get_parameter_value(param_name, default=DEFAULT_PRECLASSIFICATION_MODEL_ID)


def _get_classification_prompt() -> str:
    param_name = get_aws_config().bedrock_classification_prompt_param
    if not param_name:
        return DEFAULT_PRECLASSIFICATION_PROMPT
    return get_parameter_value(param_name, default=DEFAULT_PRECLASSIFICATION_PROMPT)


def _invoke(messages: list[Any], max_tokens: int = 256) -> Any:
    model_id = _get_model_id()
    logger.info(f"Invoking Bedrock model: {model_id}")
    return invoke_model(model_id=model_id, messages=messages, max_tokens=max_tokens)


def preclassify_document(document_bytes: bytes, content_type: str) -> BedrockClassificationResult:
    """Classify document type and count using Bedrock vision model."""
    if content_type not in SUPPORTED_CLASSIFICATION_TYPES:
        logger.info(f"Unsupported content type for classification: {content_type}")
        return BedrockClassificationResult(
            document_type="other_document", confidence=0.0, document_count=1, is_document=True
        )

    if content_type.startswith("image/") and len(document_bytes) > int(
        ConfigDefaults.BDA_MAX_IMAGE_SIZE_BYTES
    ):
        logger.info("Image exceeds 5MB, skipping classification")
        return BedrockClassificationResult(
            document_type="other_document", confidence=0.0, document_count=1, is_document=True
        )

    prompt = _get_classification_prompt()

    if content_type == "application/pdf":
        content_block = {
            "document": {"format": "pdf", "name": "document", "source": {"bytes": document_bytes}}
        }
    else:
        content_block = {
            "image": {"format": content_type.split("/")[1], "source": {"bytes": document_bytes}}
        }

    messages = [
        {
            "role": "user",
            "content": [content_block, {"text": prompt}],
        }
    ]

    try:
        start = time.time()
        result = _invoke(messages=messages)
        elapsed = round(time.time() - start, 2)

        text = result["content"][0]["text"]
        parsed = json.loads(text)

        document_type = parsed.get("document_type", "other_document")
        valid_types = [e.value for e in PreclassificationCategory] + ["other_document"]
        if document_type not in valid_types:
            document_type = "other_document"

        classification = BedrockClassificationResult(
            document_type=document_type,
            confidence=max(0.0, min(1.0, float(parsed.get("confidence", 0.0)))),
            document_count=max(0, int(parsed.get("document_count", 1))),
            is_document=str(parsed.get("is_document", True)).lower() == "true",
            is_blurry=str(parsed.get("is_blurry", False)).lower() == "true",
        )

        logger.info(
            f"Pre-classification complete in {elapsed}s: "
            f"type={classification.document_type}, "
            f"confidence={classification.confidence}, "
            f"document_count={classification.document_count}, "
            f"is_document={classification.is_document}"
        )

        return classification
    except Exception as e:
        logger.warning(f"Document classification failed: {e}")
        return BedrockClassificationResult(
            document_type="other_document", confidence=0.0, document_count=1, is_document=True
        )
