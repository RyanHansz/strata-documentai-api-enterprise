"""Image format conversion for mobile file types (HEIC, WebP, GIF)."""

import io

from PIL import Image

from documentai_api.logging import get_logger

logger = get_logger(__name__)


def convert_to_png(file_bytes: bytes, content_type: str) -> bytes:
    """Convert HEIC/WebP/GIF image bytes to PNG.

    For animated GIFs, extracts the first frame only.

    Args:
        file_bytes: Raw image bytes.
        content_type: MIME type of the source image.

    Returns:
        PNG image bytes.

    Raises:
        ValueError: If conversion fails.
    """
    try:
        if content_type in ("image/heic", "image/heif"):
            from pillow_heif import register_heif_opener  # type: ignore[import-untyped]

            register_heif_opener()

        img = Image.open(io.BytesIO(file_bytes))

        # animated GIF — take first frame
        if content_type == "image/gif" and getattr(img, "is_animated", False):
            img.seek(0)

        # convert to RGB if needed (e.g. RGBA, palette mode)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        output = io.BytesIO()
        img.save(output, format="PNG")
        result = output.getvalue()

        logger.info(
            f"Converted {content_type} to PNG",
            extra={"original_size": len(file_bytes), "converted_size": len(result)},
        )

        return result

    except Exception as e:
        raise ValueError(f"Image conversion failed for {content_type}: {e}") from e
