"""Interactive image collection + human labeling for the station-camera dataset.

The labeler is always a HUMAN. The AI model is never consulted; auto-labeling
is deliberately unsupported so ground truth stays honest.

Usage:
    python -m app.tools.collect                        # webcam (if available)
    python -m app.tools.collect --input ./photos       # label existing photos
    python -m app.tools.collect --input ./photos --assume-folders
                        # folder names are already the human labels (plastic/...)

Keys while previewing: 1 plastic, 2 metal, 3 paper, 4 other, s skip, q quit.
Optional metadata flags are recorded when given: --camera --session --lighting
--background --occlusion --object-count.

Images are saved under `<data-root>/<class>/<image_id>.<ext>` and appended to
`<data-root>/metadata.csv`. Unique ids + existing-id checks prevent overwrite.
Opens the current image in the system viewer for preview (`PIL.Image.show`).
A webcam is never required — without one, use `--input`.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .common import (
    CLASSES,
    DEFAULT_SOURCE,
    append_metadata,
    load_metadata,
    new_image_id,
    validate_class,
)

VALID_LABEL_KEYS = {str(i + 1): cls for i, cls in enumerate(CLASSES)}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", help="folder of unlabeled photos to import")
    p.add_argument("--assume-folders", action="store_true",
                   help="class folders (plastic/metal/paper/other) are already human labels")
    p.add_argument("--data-root", default="data/station_capture")
    p.add_argument("--camera", default="", help="camera id (e.g. station-001-phone)")
    p.add_argument("--session", default="", help="capture session id (groups objects)")
    p.add_argument("--lighting", default="", help="e.g. day, led, fluorescent")
    p.add_argument("--background", default="", help="e.g. tray, counter, hand")
    p.add_argument("--occlusion", default="", help="e.g. none, partial, hand")
    p.add_argument("--object-count", default="", help="number of objects in frame")
    p.add_argument("--source", default=DEFAULT_SOURCE, help="provenance tag")
    return p.parse_args(argv)


class CameraCapture:
    """Webcam capture with graceful fallbacks (cv2 -> `imagesnap` -> None)."""

    def __init__(self) -> None:
        self._cv2 = None
        try:
            import cv2  # type: ignore

            cap = cv2.VideoCapture(0)
            if cap.isOpened():
                ok, _frame = cap.read()
                if ok:
                    self._cv2 = cap
        except Exception:
            self._cv2 = None
        self._imagesnap = shutil.which("imagesnap")

    def available(self) -> bool:
        return self._cv2 is not None or self._imagesnap is not None

    def grab(self, out_path: Path) -> bool:
        if self._cv2 is not None:
            ok, frame = self._cv2.read()
            if not ok:
                return False
            import cv2  # type: ignore

            cv2.imwrite(str(out_path), frame)
            return True
        if self._imagesnap:
            r = subprocess.run([self._imagesnap, "-w", "1", "-q", str(out_path)],
                               capture_output=True)
            return r.returncode == 0 and out_path.exists()
        return False

    def close(self) -> None:
        if self._cv2 is not None:
            self._cv2.release()


def _preview(image_path: Path) -> None:
    """Show the image in the system viewer (non-blocking best effort)."""
    try:
        Image.open(image_path).show()
    except Exception:
        pass


def _collect_file(
    src: Path,
    *,
    data_root: Path,
    fields: dict,
    interactive: bool,
    forced_class: str,
    used_ids: set[str],
) -> int:
    """Label + save a single image. Returns 1 when saved, else 0."""
    try:
        image = Image.open(src)
        image.load()
    except Exception as exc:
        print(f"  ! corrupt/unreadable, skipped: {src} ({exc})")
        return 0

    label = ""
    if forced_class:
        label = forced_class
    elif interactive:
        _preview(src)
        print(f"  ? {src.name}")
        while label not in VALID_LABEL_KEYS:
            choice = input("    1 plastic | 2 metal | 3 paper | 4 other | s skip | q quit > ").strip().lower()
            if choice == "q":
                raise KeyboardInterrupt
            if choice == "s":
                return 0
            label = choice
        label = VALID_LABEL_KEYS[label]
    else:
        print(f"  ! no label given for {src.name} — run with --assume-folders or interactively")
        return 0

    image_id = new_image_id()
    while image_id in used_ids:
        image_id = new_image_id()
    used_ids.add(image_id)

    # PNG keeps fidelity of scans; JPEG is the station-camera reality.
    extension = ".jpg"
    target = data_root / label / f"{image_id}{extension}"
    target.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(target, quality=92)
    # path in the metadata is <class>/<id>.jpg (relative to the data root).
    append_metadata(data_root, {
        "image_id": image_id,
        "path": str(target.relative_to(data_root)),
        "class": label,
        "source": fields["source"],
        "camera": fields["camera"],
        "lighting": fields["lighting"],
        "background": fields["background"],
        "occlusion": fields["occlusion"],
        "object_count": fields["object_count"],
        "session_id": fields["session"],
        "object_id": fields["session"],  # one object per capture by default
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    print(f"  -> saved {target.relative_to(data_root)}")
    return 1


def _import_folder(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    used_ids = {r.get("image_id", "") for r in load_metadata(data_root)}
    fields = {
        "camera": args.camera, "lighting": args.lighting,
        "background": args.background, "occlusion": args.occlusion,
        "object_count": args.object_count, "session": args.session,
        "source": args.source,
    }
    src = Path(args.input)
    saved = 0
    try:
        if args.assume_folders:
            for cls in CLASSES:
                folder = src / cls
                if not folder.is_dir():
                    continue
                for image_path in sorted(folder.iterdir()):
                    if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
                        continue
                    saved += _collect_file(image_path, data_root=data_root, fields=fields,
                                           interactive=False, forced_class=cls, used_ids=used_ids)
        else:
            images = sorted(
                p for p in (src.iterdir() if src.is_dir() else [src])
                if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
            )
            for image_path in images:
                saved += _collect_file(image_path, data_root=data_root, fields=fields,
                                       interactive=True, forced_class="", used_ids=used_ids)
    except KeyboardInterrupt:
        print("\n  interrupted — stopping")
    return saved


def _webcam_loop(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    used_ids = {r.get("image_id", "") for r in load_metadata(data_root)}
    cam = CameraCapture()
    if not cam.available():
        print("No webcam available (tried cv2 and `imagesnap`).")
        print("Use:  python -m app.tools.collect --input ./photos")
        return 0
    fields = {
        "camera": args.camera or "webcam", "lighting": args.lighting,
        "background": args.background, "occlusion": args.occlusion,
        "object_count": args.object_count, "session": args.session,
        "source": args.source,
    }
    saved = 0
    try:
        while True:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as fh:
                tmp = Path(fh.name)
            if not cam.grab(tmp):
                print("capture failed — stopping")
                tmp.unlink(missing_ok=True)
                break
            print("  snapshot taken — press 1-4 to label, r to retake, q to quit")
            label = ""
            while label not in VALID_LABEL_KEYS:
                choice = input("    1 plastic | 2 metal | 3 paper | 4 other | r retake | q quit > ").strip().lower()
                if choice == "q":
                    tmp.unlink(missing_ok=True)
                    cam.close()
                    return saved
                if choice == "r":
                    break
                label = choice
            if label not in VALID_LABEL_KEYS:
                tmp.unlink(missing_ok=True)
                continue
            saved += _collect_file(tmp, data_root=data_root, fields=fields,
                                   interactive=False, forced_class=VALID_LABEL_KEYS[label],
                                   used_ids=used_ids)
            tmp.unlink(missing_ok=True)
    except KeyboardInterrupt:
        print("\n  interrupted")
    finally:
        cam.close()
    return saved


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.input:
        count = _import_folder(args)
        print(f"DONE — {count} image(s) collected and labeled.")
        return 0
    count = _webcam_loop(args)
    print(f"DONE — {count} image(s) captured and labeled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())