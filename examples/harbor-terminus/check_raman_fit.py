"""Measure a submitted Lorentzian on the reference solution's two fit windows."""

import argparse
import json
import math
from pathlib import Path


def residuals(spectrum, fit):
    points = []
    for line in spectrum.splitlines():
        wavelength, intensity = map(float, line.replace(",", ".").split())
        points.append((1e7 / wavelength, intensity))

    result = {}
    for peak, (low, high) in {"G": (1500, 1700), "2D": (2500, 2900)}.items():
        params = fit[peak]
        center, width, height, background = (
            params[key] for key in ("x0", "gamma", "amplitude", "offset")
        )
        errors = [
            y - (background + height / (1 + ((x - center) / width) ** 2))
            for x, y in points
            if low < x < high
        ]
        result[peak] = {
            "points": len(errors),
            "rmse": math.sqrt(math.fsum(e * e for e in errors) / len(errors)),
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spectrum", type=Path)
    parser.add_argument("submission", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            residuals(
                args.spectrum.read_text(), json.loads(args.submission.read_bytes())
            ),
            allow_nan=False,
        )
    )
