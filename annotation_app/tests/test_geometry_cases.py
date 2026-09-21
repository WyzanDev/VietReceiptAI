from io import BytesIO

import pytest
from PIL import Image

from annotation_app.geometry import crop_png


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_colored_corners_follow_requested_rotation(tmp_path, angle):
    image = Image.new("RGB", (120, 80), "white")
    for x in range(120):
        for y in range(80):
            image.putpixel(
                (x, y),
                (
                    (255, 0, 0)
                    if x < 60 and y < 40
                    else (
                        (0, 255, 0)
                        if x >= 60 and y < 40
                        else (0, 0, 255) if x >= 60 else (255, 255, 0)
                    )
                ),
            )
    source = tmp_path / "corners.png"
    image.save(source)
    crop = Image.open(
        BytesIO(crop_png(source, [[0, 0], [120, 0], [120, 80], [0, 80]], angle))
    )
    expected = {0: (255, 0, 0), 90: (255, 255, 0), 180: (0, 0, 255), 270: (0, 255, 0)}[
        angle
    ]
    assert crop.getpixel((10, 10)) == expected
    assert crop.size == ((120, 80) if angle in (0, 180) else (80, 120))
