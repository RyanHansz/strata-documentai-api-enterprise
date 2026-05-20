"""Tests for image conversion utility."""

import io

import pytest
from PIL import Image

from documentai_api.utils.image_conversion import convert_to_png


def _create_test_image(format: str, mode: str = "RGB", animated: bool = False) -> bytes:
    """Create a test image in the given format."""
    output = io.BytesIO()
    img = Image.new(mode, (100, 100), color="red")

    if animated and format == "GIF":
        frame2 = Image.new(mode, (100, 100), color="blue")
        img.save(output, format=format, save_all=True, append_images=[frame2])
    else:
        img.save(output, format=format)

    return output.getvalue()


def test_convert_webp_to_png():
    """Test WebP to PNG conversion."""
    webp_bytes = _create_test_image("WEBP")
    result = convert_to_png(webp_bytes, "image/webp")

    img = Image.open(io.BytesIO(result))
    assert img.format == "PNG"


def test_convert_gif_to_png():
    """Test static GIF to PNG conversion."""
    gif_bytes = _create_test_image("GIF", mode="P")
    result = convert_to_png(gif_bytes, "image/gif")

    img = Image.open(io.BytesIO(result))
    assert img.format == "PNG"


def test_convert_animated_gif_takes_first_frame():
    """Test animated GIF takes first frame only."""
    gif_bytes = _create_test_image("GIF", mode="P", animated=True)
    result = convert_to_png(gif_bytes, "image/gif")

    img = Image.open(io.BytesIO(result))
    assert img.format == "PNG"
    assert not getattr(img, "is_animated", False)


def test_convert_rgba_to_png():
    """Test RGBA image converts properly."""
    rgba_bytes = _create_test_image("WEBP", mode="RGBA")
    result = convert_to_png(rgba_bytes, "image/webp")

    img = Image.open(io.BytesIO(result))
    assert img.format == "PNG"


def test_convert_invalid_bytes_raises():
    """Test invalid image bytes raises ValueError."""
    with pytest.raises(ValueError, match="Image conversion failed"):
        convert_to_png(b"not an image", "image/webp")
