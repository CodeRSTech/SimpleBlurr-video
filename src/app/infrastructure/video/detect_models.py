from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from types import ModuleType

import numpy as np
import torch
from torchvision.transforms import functional

from app.shared.logging_cfg import get_logger

logger = get_logger("Infrastructure->Video")


TORCH_MODELS: dict[str, tuple[str, str]] = {
    "Torch FCOS_ResNet50_FPN": (
        "fcos_resnet50_fpn",
        "FCOS_ResNet50_FPN_Weights",
    ),
    "Torch FasterRCNN_MobileNet_V3_Large_320_FPN": (
        "fasterrcnn_mobilenet_v3_large_320_fpn",
        "FasterRCNN_MobileNet_V3_Large_320_FPN_Weights",
    ),
    "Torch FasterRCNN_MobileNet_V3_Large_FPN": (
        "fasterrcnn_mobilenet_v3_large_fpn",
        "FasterRCNN_MobileNet_V3_Large_FPN_Weights",
    ),
    "Torch FasterRCNN_ResNet50_FPN_V2": (
        "fasterrcnn_resnet50_fpn_v2",
        "FasterRCNN_ResNet50_FPN_V2_Weights",
    ),
    "Torch FasterRCNN_ResNet50_FPN": (
        "fasterrcnn_resnet50_fpn",
        "FasterRCNN_ResNet50_FPN_Weights",
    ),
    "Torch RetinaNet_ResNet50_FPN_V2": (
        "retinanet_resnet50_fpn_v2",
        "RetinaNet_ResNet50_FPN_V2_Weights",
    ),
    "Torch RetinaNet_ResNet50_FPN": (
        "retinanet_resnet50_fpn",
        "RetinaNet_ResNet50_FPN_Weights",
    ),
    "Torch SSD300_VGG16": (
        "ssd300_vgg16",
        "SSD300_VGG16_Weights",
    ),
    "Torch SSDLite320_MobileNet_V3_Large": (
        "ssdlite320_mobilenet_v3_large",
        "SSDLite320_MobileNet_V3_Large_Weights",
    ),
}


ULTRALYTICS_MODELS: dict[str, str] = {
    "YOLOv8n": "yolov8n.pt",
    "YOLOv8s": "yolov8s.pt",
    "YOLOv8m": "yolov8m.pt",
    "YOLOv8l": "yolov8l.pt",
    "YOLOv8x": "yolov8x.pt",
}


DEFAULT_TORCH_CONFIDENCE_THRESHOLD = 0.50
DEFAULT_YOLO_CONFIDENCE_THRESHOLD = 0.25


class DetectionModelError(Exception):
    pass


class BaseDetectionModel(ABC):
    @abstractmethod
    def detect(
            self,
            frame: np.ndarray,
            chosen_labels: list[str] | None = None,
    ) -> list[dict]:
        raise NotImplementedError


class DummyDetectionModel(BaseDetectionModel):
    def detect(
            self,
            frame: np.ndarray,
            chosen_labels: list[str] | None = None,
    ) -> list[dict]:
        return []


class TorchDetectionModel(BaseDetectionModel):
    def __init__(self, model_name: str, weights_name: str) -> None:
        self._model_name = model_name
        self._weights_name = weights_name
        self._model_labels: list[str] | None = None
        self._model: torch.nn.Module | None = None
        self._load_model()

    def _load_model(self) -> None:
        try:
            logger.debug("Loading TorchVision model {}", self._model_name)
            detection_module: ModuleType = importlib.import_module("torchvision.models.detection")
            model_fn = getattr(detection_module, self._model_name)
            weights_class = getattr(detection_module, self._weights_name)
            weights = weights_class.DEFAULT

            self._model_labels = list(weights.meta["categories"])
            self._model = model_fn(weights=weights)
            _ = self._model.eval()
        except Exception as exc:
            logger.opt(exception=exc).error(
                "Failed to load TorchVision model {}",
                self._model_name,
            )
            raise DetectionModelError(f"Failed to load TorchVision model: {self._model_name}") from exc

    def detect(
            self,
            frame: np.ndarray,
            chosen_labels: list[str] | None = None,
    ) -> list[dict]:
        if self._model is None or self._model_labels is None:
            return []

        try:
            img_tensor = functional.to_tensor(frame)
        except Exception as exc:
            logger.opt(exception=exc).warning("Failed to convert frame to tensor")
            return []

        with torch.no_grad():
            results = self._model([img_tensor])[0]

        detections: list[dict] = []
        num_boxes = len(results["boxes"])

        for index in range(num_boxes):
            try:
                score = float(results["scores"][index])
                if score < DEFAULT_TORCH_CONFIDENCE_THRESHOLD:
                    continue

                bbox_tensor = results["boxes"][index]
                label_index = int(results["labels"][index])
                label = self._model_labels[label_index]

                if chosen_labels and label not in chosen_labels:
                    continue

                bbox_values = bbox_tensor.tolist()
                detections.append(
                    {
                        "bbox_xyxy": (
                            int(bbox_values[0]),
                            int(bbox_values[1]),
                            int(bbox_values[2]),
                            int(bbox_values[3]),
                        ),
                        "confidence": score,
                        "label": label,
                        "color_hex": "#808080",
                    }
                )
            except Exception:
                logger.opt(exception=True).warning("Failed to map Torch detection result")
                continue

        logger.trace(
            "Torch detection filtered to {} item(s) using confidence threshold {}",
            len(detections),
            DEFAULT_TORCH_CONFIDENCE_THRESHOLD,
        )
        return detections


class YoloDetectionModel(BaseDetectionModel):
    def __init__(self, model_file_name: str) -> None:
        self._model_file_name = model_file_name
        self._model = self._load_model()

    def _load_model(self):
        try:
            logger.debug("Loading Ultralytics model {}", self._model_file_name)
            from ultralytics import YOLO
        except ModuleNotFoundError as exc:
            raise DetectionModelError(
                "Ultralytics is not installed, so YOLO models are unavailable."
            ) from exc


        try:
            return YOLO(self._model_file_name)
        except Exception as exc:
            logger.opt(exception=exc).error(
                "Failed to load Ultralytics model {}",
                self._model_file_name,
            )
            raise DetectionModelError(f"Failed to load YOLO model: {self._model_file_name}") from exc

    def detect(
            self,
            frame: np.ndarray,
            chosen_labels: list[str] | None = None,
    ) -> list[dict]:
        try:
            results = self._model(
                frame,
                verbose=False,
                conf=DEFAULT_YOLO_CONFIDENCE_THRESHOLD,
                iou=0.45,
            )
        except Exception as exc:
            logger.opt(exception=exc).warning("YOLO inference failed")
            return []

        detections: list[dict] = []

        for result in results:
            names = result.names
            for box in result.boxes:
                try:
                    score = float(box.conf[0])
                    if score < DEFAULT_YOLO_CONFIDENCE_THRESHOLD:
                        continue

                    xyxy = box.xyxy[0].tolist()
                    class_index = int(box.cls[0])
                    label = str(names[class_index])

                    if chosen_labels and label not in chosen_labels:
                        continue

                    detections.append(
                        {
                            "bbox_xyxy": (
                                int(xyxy[0]),
                                int(xyxy[1]),
                                int(xyxy[2]),
                                int(xyxy[3]),
                            ),
                            "confidence": score,
                            "label": label,
                            "color_hex": "#808080",
                        }
                    )
                except Exception:
                    logger.opt(exception=True).warning("Failed to map YOLO detection result")
                    continue

        logger.trace(
            "YOLO detection filtered to {} item(s) using confidence threshold {}",
            len(detections),
            DEFAULT_YOLO_CONFIDENCE_THRESHOLD,
        )
        return detections


def get_available_detection_model_names() -> list[str]:
    return ["None", *TORCH_MODELS.keys(), *ULTRALYTICS_MODELS.keys()]


def load_detection_model(model_name: str) -> BaseDetectionModel:
    if model_name == "None":
        return DummyDetectionModel()

    if model_name in TORCH_MODELS:
        torch_model_name, weights_name = TORCH_MODELS[model_name]
        return TorchDetectionModel(torch_model_name, weights_name)

    if model_name in ULTRALYTICS_MODELS:
        return YoloDetectionModel(ULTRALYTICS_MODELS[model_name])

    raise DetectionModelError(f"Unknown detection model: {model_name}")