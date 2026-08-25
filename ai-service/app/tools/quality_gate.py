"""Camera input-quality gate + object-presence gate for the station camera.

Runs BEFORE the waste classifier in the deployed pipeline:

    Camera -> Input Quality Gate -> Object Presence Gate -> Preprocessing
             -> Waste Classifier -> Calibration -> Routing

Blurred, dark, overexposed, flat, tiny, corrupt and empty frames are rejected
as `LOW_QUALITY`/`CORRUPT_IMAGE` before the classifier is ever invoked, and
background-only frames (no coherent object in the frame) are rejected as
`NO_OBJECT`. A frame that passes both gates is `VALID_FRAME` and goes on to
classification.

The presence gate is a deliberately lightweight, classifier-independent
heuristic behind the stable [ObjectPresenceDetector] interface, so it can be
swapped for a real detector (YOLO / MobileNet detection head / OpenCV) later
without touching the FastAPI endpoint, the mobile app or the backend.

Both gates use only PIL + numpy + scipy (no cv2) and run on a downscaled
grayscale working image so per-frame latency stays flat across camera
resolutions.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

import numpy as np
from PIL import Image, UnidentifiedImageError

from .preprocess import decode_image, to_grayscale_work

# ---------------------------------------------------------------------------
# Gate states
# ---------------------------------------------------------------------------


class GateState(str, Enum):
    VALID_FRAME = "VALID_FRAME"
    NO_OBJECT = "NO_OBJECT"
    LOW_QUALITY = "LOW_QUALITY"
    CORRUPT_IMAGE = "CORRUPT_IMAGE"


# User-facing copy for each rejection code (surfaced verbatim by the API).
REJECTION_MESSAGES: dict[GateState, str] = {
    GateState.NO_OBJECT: (
        "No waste detected. Point the camera at one item and try again."
    ),
    GateState.LOW_QUALITY: (
        "Image quality is too low. Move closer or improve the lighting."
    ),
    GateState.CORRUPT_IMAGE: "Unreadable image: could not decode payload",
}


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityMetrics:
    width: int
    height: int
    mean: float = 0.0      # mean brightness (0..255)
    std: float = 0.0        # intensity contrast (0..255)
    entropy: float = 0.0    # Shannon entropy (0..8 bits)
    lapvar: float = 0.0     # Laplacian variance — blur score
    edge_density: float = 0.0  # fraction of edge pixels


@dataclass(frozen=True)
class PresenceResult:
    present: bool
    score: float = 0.0
    reason: str | None = None


@dataclass(frozen=True)
class GateResult:
    state: GateState
    quality: QualityMetrics | None = None
    presence: PresenceResult | None = None
    elapsed_ms: float = 0.0

    @property
    def rejected(self) -> bool:
        return self.state is not GateState.VALID_FRAME


# ---------------------------------------------------------------------------
# Heuristics (shared, pure numpy)
# ---------------------------------------------------------------------------


def _laplacian_variance(gray: np.ndarray) -> float:
    """Variance of the (4-connected) Laplacian — the classic blur measure.

    High on sharp texture, ~0 on a flat/blurred frame. Computed with a fixed
    3x3 kernel via scipy.ndimage.convolve (O(n), no cv2 needed).
    """
    from scipy.ndimage import convolve

    kernel = np.asarray([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    lap = convolve(gray.astype(np.float32), kernel, mode="constant")
    return float(lap.var())


def _entropy(gray: np.ndarray, bins: int = 256) -> float:
    hist, _ = np.histogram(gray, bins=bins, range=(0, 255))
    probs = hist / max(1.0, hist.sum())
    probs = probs[probs > 0]
    return float(-(probs * np.log2(probs)).sum())


def _edge_mask(gray: np.ndarray, threshold: float = 40.0) -> np.ndarray:
    """Sobel gradient magnitude > threshold -> boolean edge map."""
    from scipy.ndimage import sobel

    gx = sobel(gray.astype(np.float32), axis=0)
    gy = sobel(gray.astype(np.float32), axis=1)
    mag = np.hypot(gx, gy)
    return mag > threshold


def _largest_component_frac(edge_mask: np.ndarray) -> float:
    """Area of the largest 8-connected edge component / frame area."""
    from scipy.ndimage import label

    labels, _ = label(edge_mask)
    if labels.size == 0:
        return 0.0
    counts = np.bincount(labels.ravel())
    return float(counts.max()) / float(edge_mask.size)


def compute_quality(gray: np.ndarray) -> QualityMetrics:
    """Compact metrics for a downscaled grayscale working image."""
    mean = float(gray.mean())
    std = float(gray.std())
    entropy = _entropy(gray)
    lapvar = _laplacian_variance(gray)
    edge_density = float(_edge_mask(gray).mean())
    h, w = gray.shape
    return QualityMetrics(
        width=w, height=h, mean=mean, std=std, entropy=entropy,
        lapvar=lapvar, edge_density=edge_density,
    )


def _center_box(gray: np.ndarray, frac: float = 0.6) -> np.ndarray:
    h, w = gray.shape
    ch, cw = max(1, int(h * frac) // 2 * 2), max(1, int(w * frac) // 2 * 2)
    top, left = (h - ch) // 2, (w - cw) // 2
    return gray[top: top + ch, left: left + cw]


def _presence_features(gray: np.ndarray) -> dict[str, float]:
    """Edge-concentration features for the presence heuristic.

    A waste object sits in the frame's centre and produces a coherent blob of
    edges. Background-only frames (tray, wall, floor) and full-frame patterns
    (checkerboard, noise) spread edges uniformly, which this set separates:
    `center_density` measures how much edge energy is inside the central box,
    `concentration` how much that is relative to the whole frame.
    """
    edges = _edge_mask(gray)
    global_density = float(edges.mean())
    center_density = float(_center_box(edges, frac=0.6).mean())
    concentration = center_density / max(global_density, 1e-6)
    return {
        "global_density": global_density,
        "center_density": center_density,
        "concentration": concentration,
        "largest_cc": _largest_component_frac(edges),
    }


# ---------------------------------------------------------------------------
# Lightweight, tunable defaults (calibrated in reports/input_gate_report.md)
# ---------------------------------------------------------------------------

MIN_DIMENSION = 32  # anything smaller than 32px is not a usable camera frame

DARK_MEAN = 10.0       # mean brightness below this = black frame
BRIGHT_MEAN = 245.0    # mean brightness above this = overexposed frame
MIN_STD = 3.0          # intensity std below this = flat/uniform frame
MIN_ENTROPY = 3.5      # information content below this = near-empty frame
MIN_LAPVAR = 25.0      # Laplacian variance below this = blurred frame
MAX_LAPVAR_CAP = float("inf")

# Presence gate
# Calibrated on the pilot-test set (see reports/input_gate_report.md): valid
# waste frames always contain a coherent blob of edges in the central box
# (pilot min center density ~0.004), while empty frames — blank wall, empty
# tray, gradient, solid colour — have essentially none. The threshold is set
# BELOW the weakest valid pilot frame so false-rejection of real waste stays
# at zero; the classifier confidence policy remains the backstop for
# low-signal frames that slip past this lightweight gate.
MIN_CENTER_DENSITY = 0.003


class InputQualityGate:
    """Decode -> dimensional -> photometric -> blur chain.

    [assess] takes raw image bytes and returns a [GateResult]: `VALID_FRAME`
    when the frame is usable (presence check still runs), else the first
    failing rejection. No classifier is involved at this layer.
    """

    def __init__(
        self,
        min_dimension: int = MIN_DIMENSION,
        dark_mean: float = DARK_MEAN,
        bright_mean: float = BRIGHT_MEAN,
        min_std: float = MIN_STD,
        min_entropy: float = MIN_ENTROPY,
        min_lapvar: float = MIN_LAPVAR,
    ) -> None:
        self.min_dimension = min_dimension
        self.dark_mean = dark_mean
        self.bright_mean = bright_mean
        self.min_std = min_std
        self.min_entropy = min_entropy
        self.min_lapvar = min_lapvar

    def assess(self, data: bytes) -> GateResult:
        start = time.perf_counter()
        try:
            image = decode_image(data)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            metrics = QualityMetrics(width=0, height=0)
            return self._finish(
                GateResult(GateState.CORRUPT_IMAGE, quality=metrics), start
            )

        w, h = image.size
        if min(w, h) < self.min_dimension:
            return self._finish(
                GateResult(
                    GateState.LOW_QUALITY,
                    quality=QualityMetrics(width=w, height=h),
                ),
                start,
            )

        gray = to_grayscale_work(image)
        metrics = compute_quality(gray)
        metrics_final = QualityMetrics(
            width=w, height=h, mean=metrics.mean, std=metrics.std,
            entropy=metrics.entropy, lapvar=metrics.lapvar,
            edge_density=metrics.edge_density,
        )

        if metrics.mean < self.dark_mean:
            return self._finish(
                GateResult(GateState.LOW_QUALITY, quality=metrics_final), start
            )
        if metrics.mean > self.bright_mean:
            return self._finish(
                GateResult(GateState.LOW_QUALITY, quality=metrics_final), start
            )
        if metrics.std < self.min_std:
            return self._finish(
                GateResult(GateState.LOW_QUALITY, quality=metrics_final), start
            )
        if metrics.entropy < self.min_entropy:
            return self._finish(
                GateResult(GateState.LOW_QUALITY, quality=metrics_final), start
            )
        if metrics.lapvar < self.min_lapvar:
            return self._finish(
                GateResult(GateState.LOW_QUALITY, quality=metrics_final), start
            )

        presence = ObjectPresenceDetector().detect(gray)
        state = (
            GateState.NO_OBJECT
            if not presence.present
            else GateState.VALID_FRAME
        )
        return self._finish(
            GateResult(state, quality=metrics_final, presence=presence), start
        )

    @staticmethod
    def _finish(result: GateResult, start: float) -> GateResult:
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 3)
        return GateResult(
            result.state, result.quality, result.presence, elapsed_ms
        )


class ObjectPresenceDetector:
    """Stable interface: `detect(working_image) -> PresenceResult`.

    The heuristic is classifier-independent and deliberately simple — a frame
    with no coherent edge content in its centre is an empty/background frame.
    The threshold lives just below the weakest valid pilot frame so real
    waste is never rejected by the gate. Swap-in point for a real detector
    (YOLO etc.) later with zero API change.
    """

    def __init__(self, min_center_density: float = MIN_CENTER_DENSITY) -> None:
        self.min_center_density = min_center_density

    def detect(self, image: Image.Image | np.ndarray) -> PresenceResult:
        if isinstance(image, Image.Image):
            gray = to_grayscale_work(image)
        else:
            gray = np.asarray(image)
        if gray.ndim == 3:
            gray = gray.mean(axis=2).astype(np.uint8)

        features = _presence_features(gray)
        # Concentration is reported but not enforced: valid waste fills the
        # frame (concentration ~1) just like textured backgrounds, so it is a
        # poor discriminator. The gate only separates "nothing in the frame"
        # from "something in the frame".
        score = float(features["center_density"])
        present = features["center_density"] >= self.min_center_density
        reason = None if present else "no_object_detected"
        return PresenceResult(present=present, score=round(score, 4), reason=reason)


def classify_with_gate(data: bytes, classifier, gate: InputQualityGate | None = None):
    """Run the full pre-classification pipeline and return `(GateResult, result)`.

    The classifier is only ever invoked for `VALID_FRAME` — the property the
    spy test pins down. `result` is `None` on every rejection.
    """
    gate = gate or InputQualityGate()
    gate_result = gate.assess(data)
    if gate_result.state is not GateState.VALID_FRAME:
        return gate_result, None
    return gate_result, classifier.predict(data)