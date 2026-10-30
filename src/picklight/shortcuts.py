"""The supported shortcut commands, scopes and portable settings format."""

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence


@dataclass(frozen=True)
class Shortcut:
    id: str
    group: str
    title: str
    default: str
    scope: str = "window"


SHORTCUTS = (
    *(Shortcut(f"rating.{stars}", "评分", f"设置 {stars} 星" if stars else "清除评分", str(stars))
      for stars in range(6)),
    Shortcut("photo.keep", "标记", "标记保留", "P", "loupe"),
    Shortcut("photo.reject", "标记", "标记待删除", "X", "loupe"),
    Shortcut("photo.clear", "标记", "清除状态标记", "U", "loupe"),
    Shortcut("photo.source", "标记", "切换 JPG / RAW", "R", "loupe"),
    Shortcut("photo.previous", "浏览", "上一张", "Left"),
    Shortcut("photo.next", "浏览", "下一张", "Right"),
    Shortcut("photo.select_all", "浏览", "全选当前视图", "Ctrl+A", "gallery"),
    Shortcut("photo.toggle_reject", "浏览", "切换待删除标记／删除选中文件夹", "Del"),
    Shortcut("view.toggle", "显示", "切换网格／选片模式", "Space"),
    Shortcut("view.grid", "显示", "返回网格／取消文件夹拖动", "Esc"),
    Shortcut("view.fullscreen", "显示", "切换全屏", "F11"),
    Shortcut("search.photos", "查找", "搜索照片", "Ctrl+F"),
    Shortcut("folder.new", "文件夹", "新建文件夹", "Ctrl+Shift+N", "folder"),
    Shortcut("folder.child", "文件夹", "新建子文件夹", "Alt+N", "folder"),
    Shortcut("folder.rename", "文件夹", "重命名文件夹", "F2", "folder"),
    Shortcut("folder.expand_all", "文件夹", "展开／收起所有文件夹", "/", "folder"),
)
BY_ID = {item.id: item for item in SHORTCUTS}
DEFAULTS = {item.id: item.default for item in SHORTCUTS}


def canonical(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("请输入有效的快捷键")
    if not value:
        return ""
    sequence = QKeySequence.fromString(value, QKeySequence.SequenceFormat.PortableText)
    if sequence.count() != 1 or sequence[0].key().value in (0, 0x1ffffff):
        raise ValueError("快捷键仅支持一组按键组合")
    if sequence[0].key() == Qt.Key.Key_Backspace:
        raise ValueError("退格键用于清除快捷键，不能作为快捷键")
    return sequence.toString(QKeySequence.SequenceFormat.PortableText)


def shortcut_conflicts(values):
    errors = {}
    for item in SHORTCUTS:
        value = values[item.id]
        if value == "Alt+F4":
            errors[item.id] = "已被“关闭窗口”使用"
            continue
        if not value:
            continue
        for other in SHORTCUTS:
            if (other.id != item.id and values[other.id] == value and
                    (item.scope == other.scope or "window" in (item.scope, other.scope))):
                errors[item.id] = f"已被“{other.title}”使用"
                break
    return errors


def validate(values):
    result = {key: canonical(values.get(key, default)) for key, default in DEFAULTS.items()}
    errors = shortcut_conflicts(result)
    if errors:
        key = next(iter(errors))
        raise ValueError(f"{result[key]} {errors[key]}，快捷键冲突")
    return result


def read_shortcuts(data):
    data = data if isinstance(data, dict) else {}
    values = dict(DEFAULTS)
    for key in DEFAULTS.keys() & data.keys():
        try:
            values[key] = canonical(data[key])
        except ValueError:
            continue
    if "photo.select_all" not in data and "photo.select_all" in shortcut_conflicts(values):
        values["photo.select_all"] = ""
    try:
        return validate(values)
    except ValueError:
        return dict(DEFAULTS)


def display_shortcut(values, key):
    return QKeySequence(values.get(key, DEFAULTS[key])).toString(QKeySequence.SequenceFormat.NativeText)
