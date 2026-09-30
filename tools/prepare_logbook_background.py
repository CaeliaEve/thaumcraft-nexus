"""Remove only dynamic UI ink from the supplied artwork.

Developer utility: pip install Pillow opencv-python-headless
The application uses the resulting PNG and does not need OpenCV.
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "image" / "thaumonomicon_bg.jpg"
    output = root / "image" / "thaumonomicon_bg_clean.png"
    rgb = np.array(Image.open(source).convert("RGB"))
    # Restrict removal to UI labels, keeping title, page edges and artwork intact.
    regions = [
        (105, 198, 380, 222), (105, 238, 380, 262),
        (105, 278, 380, 302), (105, 318, 380, 342),
        (105, 358, 380, 382), (105, 398, 248, 423),
        (108, 486, 208, 509), (106, 511, 220, 570),
        (608, 315, 814, 347),
    ]
    repaired = rgb.copy()
    donors = [(548, 170), (558, 205), (540, 238), (557, 265),
              (545, 281), (604, 220), (560, 218), (566, 234), (590, 256)]
    for (x1, y1, x2, y2), (sx, sy) in zip(regions, donors):
        width, height = x2 - x1, y2 - y1
        padding = 8
        # Poisson blending transfers real paper detail and matches edge lighting.
        # Donors are text-free portions of this same image, not generated content.
        patch = rgb[sy:sy + height + padding * 2, sx:sx + width + padding * 2]
        mask = np.zeros(patch.shape[:2], np.uint8)
        mask[padding:-padding, padding:-padding] = 255
        repaired = cv2.seamlessClone(patch, repaired, mask,
                                     ((x1 + x2) // 2, (y1 + y2) // 2), cv2.NORMAL_CLONE)
    Image.fromarray(repaired).save(output)
    print(output)


if __name__ == "__main__":
    main()
