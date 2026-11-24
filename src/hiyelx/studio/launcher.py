"""Installed-asset launcher for the local read-only Studio Host."""

from __future__ import annotations

import asyncio
import os
import stat
import tempfile
import webbrowser
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Protocol

from hiyelx.studio.host import StudioHost

STUDIO_ASSET_NAMES = (
    "index.html",
    "studio.css",
    "fixtures.js",
    "app.js",
    "host-client.js",
    "live.html",
    "live-app.js",
)

BrowserOpener = Callable[[str], bool]
ReadyCallback = Callable[[], None]
ShutdownWaiter = Callable[[], Awaitable[None]]


class StudioLauncherError(Exception):
    """Base class for fixed, non-sensitive Studio launcher failures."""


class StudioAssetError(StudioLauncherError):
    """Raised when the installed Studio assets cannot be staged safely."""

    def __init__(self) -> None:
        super().__init__("Studio assets are unavailable.")


class StudioBrowserOpenError(StudioLauncherError):
    """Raised when the default browser cannot be opened."""

    def __init__(self) -> None:
        super().__init__("Studio browser could not be opened.")


class StudioLauncherLifecycleError(StudioLauncherError):
    """Raised when launcher-owned Host lifecycle work fails."""

    def __init__(self) -> None:
        super().__init__("Studio launcher lifecycle failed.")


class StudioHostHandle(Protocol):
    """Minimum Host lifecycle surface owned by the launcher."""

    @property
    def launch_url(self) -> str: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...


StudioHostFactory = Callable[[Path], StudioHostHandle]


async def launch_studio(
    *,
    browser_opener: BrowserOpener | None = None,
    host_factory: StudioHostFactory | None = None,
    ready_callback: ReadyCallback | None = None,
    shutdown_waiter: ShutdownWaiter | None = None,
) -> None:
    """Run one foreground Studio Host from private installed-asset copies."""
    opener = _open_default_browser if browser_opener is None else browser_opener
    factory = StudioHost if host_factory is None else host_factory
    waiter = _wait_forever if shutdown_waiter is None else shutdown_waiter

    with _materialized_asset_root() as asset_root:
        try:
            host = factory(asset_root)
        except Exception:
            raise StudioLauncherLifecycleError from None

        try:
            try:
                await host.start()
            except asyncio.CancelledError:
                raise
            except Exception:
                raise StudioLauncherLifecycleError from None

            try:
                launch_url = host.launch_url
            except Exception:
                raise StudioLauncherLifecycleError from None
            try:
                opened = opener(launch_url)
            except Exception:
                raise StudioBrowserOpenError from None
            if not opened:
                raise StudioBrowserOpenError

            if ready_callback is not None:
                try:
                    ready_callback()
                except Exception:
                    raise StudioLauncherLifecycleError from None
            await waiter()
        finally:
            try:
                await host.close()
            except asyncio.CancelledError:
                raise StudioLauncherLifecycleError from None
            except Exception:
                raise StudioLauncherLifecycleError from None


def _open_default_browser(url: str) -> bool:
    return webbrowser.open(url, new=2, autoraise=True)


async def _wait_forever() -> None:
    await asyncio.Event().wait()


def _installed_asset_root() -> Traversable:
    try:
        return files("hiyelx.studio").joinpath("assets")
    except Exception:
        raise StudioAssetError from None


@contextmanager
def _materialized_asset_root(
    source_root: Traversable | None = None,
) -> Generator[Path]:
    source = _installed_asset_root() if source_root is None else source_root
    try:
        temporary = tempfile.TemporaryDirectory(prefix="hiyelx-studio-")
    except OSError:
        raise StudioAssetError from None

    try:
        destination = Path(temporary.name)
        try:
            destination.chmod(0o700)
            _copy_assets(source, destination)
        except StudioAssetError:
            raise
        except (OSError, TypeError, ValueError):
            raise StudioAssetError from None
        yield destination
    finally:
        try:
            temporary.cleanup()
        except OSError:
            raise StudioAssetError from None


def _copy_assets(source_root: Traversable, destination: Path) -> None:
    try:
        if not source_root.is_dir() or _is_filesystem_symlink(source_root):
            raise StudioAssetError
        entries = tuple(source_root.iterdir())
    except (OSError, TypeError):
        raise StudioAssetError from None
    names = tuple(entry.name for entry in entries)
    if len(entries) != len(STUDIO_ASSET_NAMES) or set(names) != set(STUDIO_ASSET_NAMES):
        raise StudioAssetError

    sources = {entry.name: entry for entry in entries}
    for name in STUDIO_ASSET_NAMES:
        source = sources[name]
        if not source.is_file() or _is_filesystem_symlink(source):
            raise StudioAssetError
        _copy_private_file(source, destination / name)


def _is_filesystem_symlink(source: Traversable) -> bool:
    if not isinstance(source, os.PathLike):
        return False
    try:
        return stat.S_ISLNK(os.lstat(source).st_mode)
    except OSError:
        raise StudioAssetError from None


def _copy_private_file(source: Traversable, destination: Path) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(destination, flags, 0o600)
    except OSError:
        raise StudioAssetError from None
    try:
        os.fchmod(descriptor, 0o600)
        with source.open("rb") as source_file:
            while chunk := source_file.read(64 * 1024):
                view = memoryview(chunk)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise StudioAssetError
                    view = view[written:]
    except StudioAssetError:
        raise
    except (OSError, TypeError, ValueError):
        raise StudioAssetError from None
    finally:
        os.close(descriptor)

    try:
        result = os.lstat(destination)
    except OSError:
        raise StudioAssetError from None
    if (
        not stat.S_ISREG(result.st_mode)
        or stat.S_ISLNK(result.st_mode)
        or result.st_uid != os.geteuid()
        or stat.S_IMODE(result.st_mode) != 0o600
    ):
        raise StudioAssetError
