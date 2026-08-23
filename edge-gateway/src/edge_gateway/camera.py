"""Optional USB camera capture with a dependency-free test seam.

OpenCV is imported only when a camera capture is requested.  A laptop without
OpenCV or a connected camera receives a human-readable error and the folder
watcher remains usable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class CameraCaptureError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class CameraFrameSource(Protocol):
    def capture_jpeg(self) -> bytes:
        """Return one JPEG frame or raise ``CameraCaptureError``."""


class OpenCVCameraSource:
    """Lazy OpenCV source; no device is opened during gateway startup."""

    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index

    def capture_jpeg(self) -> bytes:
        try:
            import cv2  # type: ignore[import-not-found]
        except ImportError as exc:
            raise CameraCaptureError(
                "CAMERA_DEPENDENCY_MISSING",
                "USB 相机功能需要 OpenCV；可先使用示例图或监控文件夹。",
            ) from exc
        camera = cv2.VideoCapture(self.camera_index)
        try:
            if not camera.isOpened():
                raise CameraCaptureError(
                    "CAMERA_NOT_FOUND",
                    f"没有找到 USB 相机（设备编号 {self.camera_index}），请检查连接或改用文件夹。",
                )
            ok, frame = camera.read()
            if not ok or frame is None:
                raise CameraCaptureError(
                    "CAMERA_FRAME_FAILED",
                    "USB 相机已连接但没有读到画面，请检查镜头遮挡或权限。",
                    retryable=True,
                )
            encoded, buffer = cv2.imencode(".jpg", frame)
            if not encoded:
                raise CameraCaptureError(
                    "CAMERA_ENCODE_FAILED",
                    "相机画面无法编码为 JPEG，未进入本地队列。",
                )
            return bytes(buffer)
        finally:
            camera.release()


@dataclass(frozen=True)
class CameraCaptureReceipt:
    filename: str
    byte_count: int
    camera_index: int

