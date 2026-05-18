#!/usr/bin/env python3
"""Standalone vision debug tool. Tests camera + all modules, saves annotated images."""

import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("vision_debug")

OUT_DIR = Path(__file__).resolve().parent / "vision_debug_output"
OUT_DIR.mkdir(exist_ok=True)

FRAMES_TO_CAPTURE = 50
SAVE_EVERY_N = 10


def draw_boxes(frame, results, color, label_prefix):
    for r in results:
        x1, y1, x2, y2 = r.get("bbox", [0, 0, 0, 0])
        conf = r.get("confidence", 0)
        label = r.get("label", r.get("status", ""))
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        text = f"{label_prefix}{label} {conf:.2f}"
        cv2.putText(frame, text, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return frame


def main():
    logger.info("=== VISION DEBUG TOOL ===")
    logger.info("Output dir: %s", OUT_DIR)

    # 1. Camera
    logger.info("[1/7] Opening camera...")
    from vision.camera import CameraManager
    cam = CameraManager()
    if not cam.open():
        logger.error("Camera failed to open!")
        return
    logger.info("Camera opened: %dx%d", cam._camera.get(cv2.CAP_PROP_FRAME_WIDTH),
                 cam._camera.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # 2. Face tracker
    logger.info("[2/7] Initializing face tracker...")
    from vision.modules.face_tracker import FaceIdentityTracker
    face_tracker = FaceIdentityTracker(frame_skip=1)

    # 3. Gesture detector
    logger.info("[3/7] Initializing gesture detector...")
    from vision.modules.gesture import GestureDetector
    gesture = GestureDetector()

    # 4. Emotion detector
    logger.info("[4/7] Initializing emotion detector...")
    from vision.modules.emotion import EmotionDetector
    try:
        emotion = EmotionDetector()
        logger.info("Emotion detector ready")
    except Exception as e:
        logger.warning("Emotion detector failed (non-critical): %s", e)
        emotion = None

    # 5. Object recognition (YOLO) - LAZY LOAD
    logger.info("[5/7] Initializing object recognition (lazy)...")
    from vision.modules.objects import ObjectRecognitionModule
    objects_mod = ObjectRecognitionModule(frame_skip=1)
    objects_mod.enabled = True

    # 6. Scene segmentation (YOLO) - LAZY LOAD
    logger.info("[6/7] Initializing scene segmentation (lazy)...")
    from vision.modules.scene import SceneSegmentationModule
    scene_mod = SceneSegmentationModule(frame_skip=1)
    scene_mod.enabled = True

    # 7. Obstacle detector
    logger.info("[7/7] Initializing obstacle detector...")
    from vision.modules.obstacle import ObstacleDetector
    obstacle = ObstacleDetector()
    obstacle.enabled = True

    logger.info("All modules ready. Capturing %d frames...", FRAMES_TO_CAPTURE)

    face_detected_count = 0
    objects_detected_count = 0
    gesture_detected_count = 0

    for i in range(FRAMES_TO_CAPTURE):
        frame = cam.get_frame()
        if frame is None:
            logger.warning("Frame %d: None frame", i)
            continue

        h, w = frame.shape[:2]
        display = frame.copy()

        # Face tracker
        t0 = time.monotonic()
        faces = face_tracker.process_frame(frame)
        ft = time.monotonic() - t0

        # Gesture
        t0 = time.monotonic()
        gesture_result = gesture.process_frame(frame)
        gt = time.monotonic() - t0

        # Emotion
        et = 0
        emotion_result = {}
        if emotion:
            t0 = time.monotonic()
            emotion_result = emotion.process_frame(frame)
            et = time.monotonic() - t0

        # Objects
        t0 = time.monotonic()
        objects_result = objects_mod.process_frame(frame)
        ot = time.monotonic() - t0

        # Scene
        t0 = time.monotonic()
        scene_result = scene_mod.process_frame(frame)
        st = time.monotonic() - t0

        # Obstacle
        t0 = time.monotonic()
        obstacle_result = obstacle.process_frame(frame)
        obt = time.monotonic() - t0

        if faces:
            face_detected_count += 1
        if objects_result.get("objects"):
            objects_detected_count += 1
        if gesture_result.get("hand_found"):
            gesture_detected_count += 1

        frame_face_status = f"FACES={len(faces)}" if faces else "no face"
        frame_obj_status = f"OBJ={objects_result['count']}" if objects_result.get("objects") else "no obj"
        frame_gesture_status = f"GESTURE={gesture_result['gesture']}" if gesture_result.get("hand_found") else "no gesture"

        logger.info(
            "Frame %3d/%d | %s | %s | %s | "
            "Face:%4.0fms Gesture:%4.0fms Emotion:%4.0fms Object:%4.0fms Scene:%4.0fms Obstacle:%4.0fms",
            i + 1, FRAMES_TO_CAPTURE,
            frame_face_status, frame_obj_status, frame_gesture_status,
            ft * 1000, gt * 1000, et * 1000, ot * 1000, st * 1000, obt * 1000,
        )

        if (i + 1) % SAVE_EVERY_N == 0 or i == 0 or (faces and not hasattr(locals(), '_last_face_save')):
            # Draw face boxes
            for face in faces:
                bbox = face.get("bbox")
                if bbox and len(bbox) == 4:
                    top, right, bottom, left = bbox
                    cv2.rectangle(display, (left, top), (right, bottom), (0, 255, 0), 2)
                    status = face.get("status", "")
                    cv2.putText(display, status, (left, top - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            # Draw object boxes
            for obj in objects_result.get("objects", []):
                bbox = obj.get("bbox")
                if bbox and len(bbox) == 4:
                    x1, y1, x2, y2 = bbox
                    cv2.rectangle(display, (x1, y1), (x2, y2), (255, 0, 0), 2)
                    label = obj.get("label", "")
                    conf = obj.get("confidence", 0)
                    cv2.putText(display, f"{label} {conf:.2f}", (x1, y1 - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)

            # Info overlay
            info_lines = [
                f"Frame {i+1}/{FRAMES_TO_CAPTURE}",
                f"Faces: {len(faces)} | Gesture: {gesture_result['gesture']} | Emotion: {emotion_result.get('emotion', 'N/A')}",
                f"Objects: {objects_result['count']} | Obstacle: {obstacle_result['direction']}",
                f"Times(ms) F:{ft*1000:.0f} G:{gt*1000:.0f} E:{et*1000:.0f} O:{ot*1000:.0f} S:{st*1000:.0f}",
            ]
            for li, line in enumerate(info_lines):
                cv2.putText(display, line, (8, 20 + li * 18),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)

            out_path = OUT_DIR / f"frame_{i+1:04d}.jpg"
            cv2.imwrite(str(out_path), display)
            logger.info("Saved: %s", out_path.name)

    # Summary
    logger.info("=" * 50)
    logger.info("SUMMARY")
    logger.info("  Total frames: %d", FRAMES_TO_CAPTURE)
    logger.info("  Frames with face detected: %d/%d", face_detected_count, FRAMES_TO_CAPTURE)
    logger.info("  Frames with objects detected: %d/%d", objects_detected_count, FRAMES_TO_CAPTURE)
    logger.info("  Frames with gesture detected: %d/%d", gesture_detected_count, FRAMES_TO_CAPTURE)

    if face_detected_count == 0:
        logger.warning("  >> NO FACES DETECTED. Check lighting, distance from camera, face angle.")
    if objects_detected_count == 0:
        logger.warning("  >> NO OBJECTS DETECTED. YOLO model may not be loaded yet.")

    cam.close()
    face_tracker.close()
    gesture.close()
    if emotion:
        emotion.close()
    objects_mod.close()
    scene_mod.close()
    obstacle.close()

    logger.info("Annotated frames saved to: %s", OUT_DIR)
    logger.info("Done.")


if __name__ == "__main__":
    main()
