"""Persistent UI state. Ratings live in photo metadata, not in this file."""

from __future__ import annotations

from datetime import datetime
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4
import json
import os
import re
from picklight.file_access import path_key


@dataclass(frozen=True)
class FolderDeletion:
    project_id: str
    projects: list[tuple[int, dict]]
    collapsed_ids: set[str]


def default_settings_path() -> Path:
    override = os.environ.get("PICKLIGHT_SETTINGS")
    if override:
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return base / "PickLight" / "settings.json"


class SessionStore:
    def __init__(self, path: Path | None = None):
        self.path = path or default_settings_path()
        self.data = self._load()
        self._bootstrap_projects()

    def _load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def session_key(project_folder: Path) -> str:
        return project_folder.resolve().as_posix().casefold()

    def _bootstrap_projects(self) -> None:
        if isinstance(self.data.get("projects"), list):
            return
        folder = self._legacy_recent_project()
        projects = []
        if folder:
            project_id = uuid4().hex
            projects.append({"id": project_id, "name": Path(folder).name or folder,
                             "folder": folder, "parent_id": None, "photo_count": 0})
            self.data["active_project_id"] = project_id
        self.data["projects"] = projects
        if projects:
            self.save()

    def projects(self) -> list[dict]:
        return self.data["projects"]

    def project_by_id(self, project_id: str) -> dict | None:
        return next((project for project in self.projects()
                     if project.get("id") == project_id), None)

    def project_for_folder(self, folder: Path) -> dict | None:
        key = self.session_key(folder)
        return next((project for project in self.projects()
                     if project.get("folder") and self.session_key(Path(project["folder"])) == key), None)

    def add_project(self, folder: Path, parent_id: str | None = None) -> dict:
        existing = self.project_for_folder(folder)
        if existing:
            if parent_id is not None and existing.get("parent_id") != parent_id:
                self.move_project(existing["id"], parent_id)
            return existing
        if parent_id is not None and self.project_by_id(parent_id) is None:
            raise ValueError("目标文件夹不存在")
        resolved = folder.resolve()
        project = {"id": uuid4().hex, "name": resolved.name, "folder": str(resolved),
                   "parent_id": parent_id, "photo_count": 0,
                   "imported_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        self.projects().append(project)
        self.save()
        return project

    def add_folder(self, name: str, parent_id: str | None = None) -> dict:
        name = name.strip()
        if not name:
            raise ValueError("文件夹名称不能为空")
        if parent_id is not None and self.project_by_id(parent_id) is None:
            raise ValueError("上级文件夹不存在")
        project = {"id": uuid4().hex, "name": name, "folder": None,
                   "parent_id": parent_id, "photo_count": 0,
                   "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        self.projects().append(project)
        self.save()
        return project

    def bind_folder(self, project_id: str, folder: Path) -> dict:
        project = self.project_by_id(project_id)
        if project is None:
            raise ValueError("文件夹不存在")
        if project.get("folder"):
            raise ValueError("此文件夹已绑定磁盘目录")
        existing = self.project_for_folder(folder)
        if existing is not None:
            raise ValueError(f"磁盘目录已绑定到“{existing['name']}”")
        resolved = folder.resolve()
        if not resolved.is_dir():
            raise ValueError("磁盘目录不存在")
        project["folder"] = str(resolved)
        project["imported_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.save()
        return project

    def activate_project(self, project_id: str) -> dict:
        project = self.project_by_id(project_id)
        if project is None:
            raise ValueError("项目不存在")
        self.data["active_project_id"] = project_id
        if project.get("folder"):
            self.data["project_folder"] = project["folder"]
        else:
            self.data.pop("project_folder", None)
        self.save()
        return project

    def rename_project(self, project_id: str, name: str) -> None:
        project = self.project_by_id(project_id)
        if project is None:
            raise ValueError("项目不存在")
        name = name.strip()
        if not name:
            raise ValueError("项目名称不能为空")
        project["name"] = name
        self.save()

    def set_folder_description(self, project_id: str, description: str) -> None:
        project = self.project_by_id(project_id)
        if project is None:
            raise ValueError("文件夹不存在")
        project["description"] = description.strip()
        self.save()

    def set_folder_appearance(self, project_id: str, *, icon: str | None = None,
                              color: str | None = None) -> None:
        project = self.project_by_id(project_id)
        if project is None:
            raise ValueError("文件夹不存在")
        if icon is not None and icon and not re.fullmatch(r"[a-zA-Z0-9_-]+", icon):
            raise ValueError("无效的文件夹图标")
        if color is not None and color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("无效的文件夹颜色")
        if icon is not None:
            project["icon"] = icon
        if color is not None:
            project["color"] = color.lower()
        self.save()

    def folder_branch(self, project_id: str) -> list[dict]:
        projects = self.projects()
        children = {}
        for project in projects:
            children.setdefault(project.get("parent_id"), []).append(project["id"])
        ids, pending = set(), [project_id]
        while pending:
            current = pending.pop()
            if current not in ids:
                ids.add(current)
                pending.extend(children.get(current, ()))
        return [project for project in projects if project["id"] in ids]

    photo_path_key = staticmethod(path_key)

    def delete_folder_branch(self, project_id: str) -> set[str]:
        branch = self.folder_branch(project_id)
        ids = {p["id"] for p in branch}
        self.data["projects"] = [p for p in self.projects() if p["id"] not in ids]
        if self.data.get("active_project_id") in ids:
            self.data.pop("active_project_id", None)
            self.data.pop("project_folder", None)
        if not any(p.get("folder") for p in self.projects()):
            # A deliberately emptied catalog must not reopen an old legacy source.
            for key in ("project_folder", "jpg_folder", "raw_folder"):
                self.data.pop(key, None)
        self.save()
        return ids

    def delete_folder_undoable(self, project_id: str) -> FolderDeletion:
        ids = {folder["id"] for folder in self.folder_branch(project_id)}
        projects = [(index, deepcopy(folder)) for index, folder in enumerate(self.projects())
                    if folder["id"] in ids]
        saved_collapsed = self.data.get("collapsed_folder_ids", [])
        collapsed = (set(saved_collapsed) if isinstance(saved_collapsed, list) else set()) & ids
        self.delete_folder_branch(project_id)
        return FolderDeletion(project_id, projects, collapsed)

    def undo_folder_deletion(self, deletion: FolderDeletion) -> None:
        """Restore only this branch, preserving edits made to unrelated settings."""
        projects = self.projects()
        existing = {folder["id"] for folder in projects}
        restoring = {folder["id"] for _, folder in deletion.projects} - existing
        for _, saved in deletion.projects:
            if saved["id"] in restoring and saved.get("folder"):
                conflict = self.project_for_folder(Path(saved["folder"]))
                if conflict is not None:
                    raise ValueError(f'目录已关联到“{conflict["name"]}”，无法重复恢复文件夹。')
        for index, saved in deletion.projects:
            if saved["id"] in existing:
                continue
            folder = deepcopy(saved)
            if folder.get("parent_id") not in existing | restoring:
                folder["parent_id"] = None
            projects.insert(min(index, len(projects)), folder)
        saved_collapsed = self.data.get("collapsed_folder_ids", [])
        collapsed = (set(saved_collapsed) if isinstance(saved_collapsed, list) else set()) - restoring
        self.data["collapsed_folder_ids"] = sorted(collapsed | (deletion.collapsed_ids & restoring))
        self.save()


    def remove_project(self, project_id: str) -> None:
        project = self.project_by_id(project_id)
        if project is None:
            return
        for child in self.projects():
            if child.get("parent_id") == project_id:
                child["parent_id"] = project.get("parent_id")
        self.projects().remove(project)
        if self.data.get("active_project_id") == project_id:
            self.data.pop("active_project_id", None)
            self.data.pop("project_folder", None)
        self.save()

    def move_project(self, project_id: str, parent_id: str | None, *,
                     before_id: str | None = None, after_id: str | None = None) -> None:
        project = self.project_by_id(project_id)
        if project is None:
            raise ValueError("文件夹不存在")
        if parent_id is not None and self.project_by_id(parent_id) is None:
            raise ValueError("目标文件夹不存在")
        ancestor = parent_id
        while ancestor is not None:
            if ancestor == project_id:
                raise ValueError("不能把文件夹移入自身或下级")
            parent = self.project_by_id(ancestor)
            ancestor = parent.get("parent_id") if parent else None
        target_id = before_id or after_id
        if before_id and after_id:
            raise ValueError("只能选择一个插入位置")
        target = self.project_by_id(target_id) if target_id else None
        if target_id and (target is None or target_id == project_id or target.get("parent_id") != parent_id):
            raise ValueError("插入位置无效")
        if project.get("parent_id") == parent_id and not target_id:
            return
        children = {}
        for folder in self.projects():
            if folder["id"] != project_id:
                children.setdefault(folder.get("parent_id"), []).append(folder)
        siblings = children.setdefault(parent_id, [])
        position = next((i for i, folder in enumerate(siblings) if folder["id"] == target_id), len(siblings))
        if after_id:
            position += 1
        siblings.insert(position, project)
        project["parent_id"] = parent_id
        ordered, pending = [], list(reversed(children.get(None, [])))
        while pending:
            folder = pending.pop()
            ordered.append(folder)
            pending.extend(reversed(children.get(folder["id"], [])))
        self.data["projects"] = ordered
        self.save()

    def reorder_projects(self, tree: list[tuple[str, str | None]]) -> None:
        known = {project["id"]: project for project in self.projects()}
        if len(tree) != len(known) or {project_id for project_id, _ in tree} != set(known):
            raise ValueError("文件夹树不完整")
        seen: set[str] = set()
        for project_id, parent_id in tree:
            if parent_id is not None and parent_id not in seen:
                raise ValueError("文件夹不能移入自身或下级")
            seen.add(project_id)
        self.data["projects"] = [known[project_id] for project_id, _ in tree]
        for project_id, parent_id in tree:
            known[project_id]["parent_id"] = parent_id
        self.save()

    def recent_project(self) -> str:
        active = self.project_by_id(self.data.get("active_project_id", ""))
        if active and active.get("folder"):
            return active["folder"]
        bound = next((project["folder"] for project in reversed(self.projects())
                      if project.get("folder")), None)
        if bound:
            return bound
        return self._legacy_recent_project()

    def _legacy_recent_project(self) -> str:
        current = self.data.get("project_folder", "")
        if current:
            return current
        # Existing installations stored a pair of folders. Recover their
        # common parent so the new single-folder workflow keeps opening them.
        jpg, raw = self.data.get("jpg_folder", ""), self.data.get("raw_folder", "")
        if jpg and raw:
            jpg_path, raw_path = Path(jpg), Path(raw)
            if jpg_path == raw_path:
                return str(jpg_path)
            if jpg_path.parent == raw_path.parent:
                return str(jpg_path.parent)
        return ""

    def migrate_legacy_session(self, project_folder: Path) -> None:
        jpg, raw = self.data.get("jpg_folder", ""), self.data.get("raw_folder", "")
        if not (jpg and raw):
            return
        jpg_path, raw_path = Path(jpg).resolve(), Path(raw).resolve()
        legacy_root = jpg_path if jpg_path == raw_path else jpg_path.parent if jpg_path.parent == raw_path.parent else None
        if legacy_root is None or legacy_root != project_folder.resolve():
            return
        old_key = f"{Path(jpg).resolve().as_posix().casefold()}|{Path(raw).resolve().as_posix().casefold()}"
        new_key = self.session_key(project_folder)
        sessions = self.data.setdefault("sessions", {})
        if new_key not in sessions and old_key in sessions:
            sessions[new_key] = sessions[old_key].copy()

    def state_for(self, key: str) -> dict:
        return self.data.setdefault("sessions", {}).setdefault(key, {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                prefix=".picklight-", suffix=".tmp", delete=False) as stream:
            json.dump(self.data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        os.replace(temporary, self.path)
