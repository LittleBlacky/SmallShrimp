from __future__ import annotations
"""配置热重载模块。"""
import time
from pathlib import Path
from typing import Any, Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

class ConfigReloader:
    """配置文件热重载器。"""

    def __init__(
        self,
        workspace: Path,
        on_reload: Optional[Callable[[], None]] = None
    ) -> None:
        self.workspace = workspace
        self.on_reload = on_reload
        self._observer: Optional[Observer] = None
        self._last_reload_time = 0.0
        self._reload_cooldown = 1.0  # 防止频繁重载的冷却时间（秒）

    def start(self) -> None:
        """启动文件监听。"""
        if self._observer is not None:
            return

        event_handler = ConfigFileHandler(self)
        self._observer = Observer()
        config_dir = self.workspace
        if not config_dir.exists():
            config_dir.mkdir(parents=True, exist_ok=True)
        self._observer.schedule(event_handler, str(config_dir), recursive=False)
        self._observer.start()

    def stop(self) -> None:
        """停止文件监听。"""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    def notify_reload(self) -> None:
        """通知配置已重载。"""
        current_time = time.time()
        if current_time - self._last_reload_time < self._reload_cooldown:
            return  # 跳过冷却期内的重复触发

        self._last_reload_time = current_time
        if self.on_reload:
            self.on_reload()


class ConfigFileHandler(FileSystemEventHandler):
    """配置文件变更事件处理器。"""

    def __init__(self, reloader: ConfigReloader) -> None:
        self._reloader = reloader

    def on_modified(self, event: FileModifiedEvent) -> None:
        """配置文件被修改时触发重载。"""
        if event.is_directory:
            return

        src_path = Path(event.src_path)
        if src_path.name in ("config.user.yaml", "config.runtime.yaml"):
            self._reloader.notify_reload()