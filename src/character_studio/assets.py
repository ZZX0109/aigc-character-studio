"""Route immutable character assets without changing the existing scan model."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from . import geometry as scan


DOWNLOAD_URL = "https://download.is.tue.mpg.de/download.php?domain=flame&sfile=FLAME2023Open.zip"


class AssetLibrary:
    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.inbox = self.root / "inbox"
        self.inbox.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _flame():
        from . import flame
        return flame

    @staticmethod
    def public(metadata: dict) -> dict:
        result = deepcopy({k: v for k, v in metadata.items() if k not in {"calibration", "source_path"}})
        result["available"] = True
        if result.get("asset_kind") == "static_head_scan":
            result.update(calibration_status="ready", can_edit_nose=True)
        else:
            result["can_edit_nose"] = result.get("calibration_status") == "ready"
        return result

    def list(self) -> list[dict]:
        result = [self.public(scan.get_asset_info())]
        imported = self._flame().list_assets(self.root)
        # Keep the imported neutral template available, but present reviewed assets first.
        imported.sort(key=lambda a: (a.get("calibration_status") != "ready", a["asset_id"]))
        return result + [self.public(item) for item in imported]

    def info(self, asset_id: str) -> dict:
        if asset_id == scan.BASE_ASSET_ID:
            return self.public(scan.get_asset_info())
        metadata = self._flame().get_asset_info(asset_id, self.root)
        if metadata.get("is_test_fixture"):
            raise ValueError("测试夹具不能作为工作台角色资产")
        return self.public(metadata)

    def build(self, asset_id: str, nose_width: float = 0.0,
              identity_params: list[float] | None = None,
              expression_params: list[float] | None = None) -> dict:
        if asset_id == scan.BASE_ASSET_ID:
            if any(identity_params or []) or any(expression_params or []):
                raise ValueError("扫描示例不支持 FLAME 身份或表情参数")
            result = scan.build_geometry(nose_width)
            result["parameters"].update(identity_params=identity_params or [], expression_params=expression_params or [])
            result["metadata"] = self.info(asset_id)
            return result
        self.info(asset_id)  # Reject missing or synthetic assets on the live interface.
        result = self._flame().build_geometry(asset_id, nose_width, identity_params, expression_params, root=self.root)
        result["metadata"] = self.public(result["metadata"])
        return result

    def status(self) -> dict:
        imported = [a for a in self.list() if a.get("asset_kind") == "flame_parametric_head"]
        ready = [a for a in imported if a["can_edit_nose"]]
        return {
            "available": bool(imported), "can_edit_nose": bool(ready),
            "download_url": DOWNLOAD_URL, "inbox_directory": str(self.inbox),
            "message": "FLAME 已导入且鼻翼范围已校准" if ready else
                       "FLAME 已导入，可查看中性网格；鼻翼范围仍需校准" if imported else
                       "从官网 Open 专用链接下载模型，将 ZIP 或模型文件放入下载目录后导入。若官网提示登录，请在官网完成。",
        }

    def discover(self) -> list[dict]:
        result = []
        for path in sorted(self.inbox.rglob("*")):
            if (path.is_symlink() or not path.is_file() or path.suffix.lower() not in {".zip", ".pkl", ".pickle", ".npz"}
                    or not path.resolve().is_relative_to(self.inbox)):
                continue
            result.append({"path": str(path.resolve()), "name": path.name, "size": path.stat().st_size})
        return result[:100]

    def import_path(self, source: str) -> dict:
        candidate = Path(source).expanduser()
        if not candidate.is_absolute():
            candidate = self.inbox / candidate
        if candidate.is_symlink():
            raise ValueError("请导入下载目录内的真实模型文件")
        candidate = candidate.resolve()
        if not candidate.is_relative_to(self.inbox) or not candidate.is_file():
            raise ValueError(f"请将模型文件放入 {self.inbox} 后再导入")
        metadata = self._flame().import_model(candidate, self.root)
        reviewed = [a for a in self._flame().list_assets(self.root)
                    if a.get("parent_asset_id") == metadata["asset_id"] and a.get("calibration_status") == "ready"]
        return self.public(reviewed[-1] if reviewed else metadata)
