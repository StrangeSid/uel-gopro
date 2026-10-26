from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional

from uel_gopro.core.exceptions import MediaError, TransportError
from uel_gopro.core.models import CameraInfo, MediaItem, MediaType, TransportType

logger = logging.getLogger(__name__)

# Check if macOS ImageCaptureCore is available via PyObjC
HAS_IMAGECAPTURE = False
if sys.platform == "darwin":
    try:
        import objc
        from Foundation import NSDate, NSObject, NSRunLoop, NSURL
        objc.loadBundle(
            "ImageCaptureCore",
            globals(),
            bundle_path="/System/Library/Frameworks/ImageCaptureCore.framework",
        )
        HAS_IMAGECAPTURE = True
    except Exception as exc:
        logger.debug(f"ImageCaptureCore not available: {exc}")


def is_mtp_available() -> bool:
    """Returns True if MTP backend (ImageCaptureCore on macOS) is functional."""
    return HAS_IMAGECAPTURE


if HAS_IMAGECAPTURE:

    class _BrowserDelegate(NSObject):
        def init(self):
            self = objc.super(_BrowserDelegate, self).init()
            if self is None:
                return None
            self.device = None
            return self

        def didRemoveDevice_(self, device):
            pass

        def deviceBrowser_didAddDevice_moreComing_(self, browser, device, more_coming):
            name = str(device.name() or "")
            if "HERO" in name.upper() or "GOPRO" in name.upper():
                self.device = device


    class _CameraDelegate(NSObject):
        def didRemoveDevice_(self, device):
            pass

        def device_didOpenSessionWithError_(self, device, error):
            pass

        def cameraDevice_didAddItems_(self, camera, items):
            pass

        def cameraDevice_didAddItem_(self, camera, item):
            pass

        def device_didCloseSessionWithError_(self, device, error):
            pass


    class _DownloadDelegate(NSObject):
        def init(self):
            self = objc.super(_DownloadDelegate, self).init()
            if self is None:
                return None
            self.finished = False
            self.error = None
            self.downloaded_file = None
            return self

        def didDownloadFile_error_options_contextInfo_(self, file, error, options, context):
            self.finished = True
            self.error = error
            self.downloaded_file = file


class MtpClient:
    """MTP (Media Transfer Protocol) Client for GoPro on macOS."""

    def __init__(self):
        if not is_mtp_available():
            raise TransportError("MTP transport is only supported on macOS via ImageCaptureCore.")
        self._browser = None
        self._browser_del = None
        self._cam = None
        self._cam_del = None

    def _get_camera(self, timeout_sec: float = 2.0):
        if self._cam is not None:
            return self._cam

        self._browser_del = _BrowserDelegate.alloc().init()
        browser_class = globals().get("ICDeviceBrowser")
        if browser_class is None:
            raise TransportError("ImageCaptureCore ICDeviceBrowser is unavailable")
        self._browser = browser_class.alloc().init()
        self._browser.setDelegate_(self._browser_del)
        self._browser.setBrowsedDeviceTypeMask_(0xFFFFFFFF)
        self._browser.start()

        start_t = time.time()
        while time.time() - start_t < timeout_sec:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))
            if self._browser_del.device is not None:
                self._cam = self._browser_del.device
                break

        return self._cam

    def detect_camera(self, timeout_sec: float = 2.0) -> Optional[CameraInfo]:
        """Detects if a GoPro is connected via USB in MTP mode."""
        cam = self._get_camera(timeout_sec=timeout_sec)
        if cam is None:
            return None

        name = str(cam.name() or "GoPro (MTP)")
        return CameraInfo(
            model_name=name,
            ip_address="usb:mtp",
            port=0,
            transport=TransportType.MTP,
            interface_name="USB-MTP",
        )

    def _open_session(self, timeout_sec: float = 4.0) -> bool:
        cam = self._get_camera()
        if cam is None:
            return False

        if self._cam_del is None:
            self._cam_del = _CameraDelegate.alloc().init()
            cam.setDelegate_(self._cam_del)

        cam.requestOpenSession()
        start_t = time.time()
        while time.time() - start_t < timeout_sec:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))
            # Check if media files are enumerated
            mf = cam.mediaFiles()
            if mf and len(mf) > 0:
                return True

        return True

    def list_media(self, timeout_sec: float = 4.0) -> List[MediaItem]:
        """Lists all media stored on camera SD card via MTP."""
        cam = self._get_camera()
        if cam is None:
            raise TransportError("No GoPro detected over MTP.")

        self._open_session(timeout_sec=timeout_sec)
        raw_files = cam.mediaFiles() or []

        items: List[MediaItem] = []
        for f in raw_files:
            fname = str(f.name() or "")
            fsize = int(f.fileSize() or 0)

            # Filter out utility/system files
            if fname.lower().endswith(".url") or fname.lower().endswith(".sav"):
                continue

            lower = fname.lower()
            if lower.endswith((".mp4", ".mov")):
                mtype = MediaType.VIDEO
            elif lower.endswith((".jpg", ".gpr")):
                mtype = MediaType.PHOTO
            elif lower.endswith(".wav"):
                mtype = MediaType.AUDIO
            elif lower.endswith(".thm"):
                mtype = MediaType.THUMBNAIL
            else:
                mtype = MediaType.SIDECAR

            items.append(
                MediaItem(
                    directory="100GOPRO",
                    filename=fname,
                    size_bytes=fsize,
                    media_type=mtype,
                )
            )

        return items

    def download_file(
        self,
        filename: str,
        dest_dir: Path | str,
        timeout_sec: float = 3600.0,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Path:
        """Downloads a specific file from GoPro via MTP."""
        safe_filename = Path(filename).name
        if safe_filename in ("", ".", ".."):
            raise MediaError(f"Refusing unsafe media filename: {filename!r}")

        cam = self._get_camera()
        if cam is None:
            raise TransportError("No GoPro detected over MTP.")

        self._open_session()
        raw_files = cam.mediaFiles() or []
        target = None
        for f in raw_files:
            if str(f.name() or "").lower() == filename.lower():
                target = f
                break

        if target is None:
            raise MediaError(f"File '{filename}' not found on camera via MTP.")

        dest_path = Path(dest_dir).expanduser().resolve()
        dest_path.mkdir(parents=True, exist_ok=True)
        final_file = dest_path / safe_filename

        dl_delegate = _DownloadDelegate.alloc().init()
        options = {
            "ICDownloadsDirectoryURL": NSURL.fileURLWithPath_(str(dest_path)),
            "ICSaveAsFilename": safe_filename,
            "ICOverwrite": True,
        }

        logger.info(f"Downloading {filename} via MTP...")
        cam.requestDownloadFile_options_downloadDelegate_didDownloadSelector_contextInfo_(
            target,
            options,
            dl_delegate,
            "didDownloadFile:error:options:contextInfo:",
            None,
        )

        start_t = time.time()
        while time.time() - start_t < timeout_sec:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))
            if dl_delegate.finished:
                if dl_delegate.error:
                    raise MediaError(f"MTP download failed for {filename}: {dl_delegate.error}")
                break

        if not dl_delegate.finished:
            raise MediaError(
                f"MTP download timed out after {timeout_sec:.0f}s for {filename}. "
                "The file may still be transferring; retry before removing the camera."
            )

        if not final_file.exists():
            raise MediaError(f"MTP download finished but the file is missing on disk: {final_file}")

        try:
            expected_size = int(target.fileSize() or 0)
        except Exception:
            expected_size = 0
        actual_size = final_file.stat().st_size
        if expected_size > 0 and actual_size != expected_size:
            raise MediaError(
                f"MTP download size mismatch for {filename}: "
                f"expected {expected_size} bytes, got {actual_size}"
            )
        if progress_callback:
            progress_callback(actual_size, expected_size or actual_size)

        return final_file

    def __enter__(self) -> "MtpClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        """Close the session and stop the device browser."""
        if self._cam is not None:
            try:
                self._cam.requestCloseSession()
            except Exception:
                pass
            self._cam = None
        if self._browser is not None:
            try:
                self._browser.stop()
            except Exception:
                pass
            self._browser = None
