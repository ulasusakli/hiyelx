import asyncio
import hashlib
import inspect
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

from hiyelx.studio import launcher
from hiyelx.studio.launcher import (
    STUDIO_ASSET_NAMES,
    StudioAssetError,
    StudioBrowserOpenError,
    StudioHostHandle,
    StudioLauncherLifecycleError,
    launch_studio,
)

ROOT = Path(__file__).resolve().parents[3]
SOURCE_ASSETS = ROOT / "studio"
WHEEL_ASSET_PREFIX = "hiyelx/studio/assets/"
CAPABILITY = "x" * 43
_REAL_TEMPORARY_DIRECTORY = tempfile.TemporaryDirectory


class CleanupFailingTemporaryDirectory:
    def __init__(self, *, prefix: str) -> None:
        self._owned = _REAL_TEMPORARY_DIRECTORY(prefix=prefix)
        self.name = self._owned.name
        self.cleanup_calls = 0
        self.removed = False

    def cleanup(self) -> None:
        self.cleanup_calls += 1
        self._owned.cleanup()
        self.removed = not os.path.exists(self.name)
        raise OSError("private temporary path=/private/tmp capability=secret")


class FakeHost:
    def __init__(
        self,
        asset_root: Path,
        events: list[str],
        *,
        fail_start: bool = False,
        fail_close: bool = False,
    ) -> None:
        self.asset_root = asset_root
        self.events = events
        self.fail_start = fail_start
        self.fail_close = fail_close
        self.launch_url = f"http://127.0.0.1:43210/#capability={CAPABILITY}"

    async def start(self) -> None:
        self.events.append("host-start")
        _assert_private_staged_assets(self.asset_root)
        if self.fail_start:
            raise OSError("/private/path pid=123 secret=value")

    async def close(self) -> None:
        self.events.append("host-close")
        if self.fail_close:
            raise OSError("/private/path pid=123 secret=value")


@pytest.fixture
def installed_asset_source(tmp_path: Path) -> Path:
    source = tmp_path / "installed" / "hiyelx" / "studio" / "assets"
    source.mkdir(parents=True, mode=0o700)
    for name in STUDIO_ASSET_NAMES:
        target = source / name
        target.write_bytes((SOURCE_ASSETS / name).read_bytes())
        target.chmod(0o600)
    return source


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    uv = shutil.which("uv")
    assert uv is not None, "uv is required for installed-wheel asset verification"
    output = tmp_path_factory.mktemp("studio-wheel")
    result = subprocess.run(
        (
            uv,
            "build",
            "--wheel",
            "--no-create-gitignore",
            "--out-dir",
            str(output),
            str(ROOT),
        ),
        cwd=output,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    wheels = tuple(output.glob("hiyelx-*.whl"))
    assert result.returncode == 0 and len(wheels) == 1, (
        "wheel build failed; "
        f"returncode={result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    return wheels[0]


def test_built_wheel_contains_exact_asset_manifest_and_source_bytes(
    built_wheel: Path,
) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        packaged = tuple(
            name.removeprefix(WHEEL_ASSET_PREFIX)
            for name in archive.namelist()
            if name.startswith(WHEEL_ASSET_PREFIX) and not name.endswith("/")
        )
        assert set(packaged) == set(STUDIO_ASSET_NAMES)
        assert len(packaged) == len(STUDIO_ASSET_NAMES)
        for name in STUDIO_ASSET_NAMES:
            assert archive.read(f"{WHEEL_ASSET_PREFIX}{name}") == (
                SOURCE_ASSETS / name
            ).read_bytes()


def test_installed_package_resources_resolve_without_checkout_paths(
    built_wheel: Path,
    tmp_path: Path,
) -> None:
    installed = tmp_path / "installed"
    installed.mkdir()
    with zipfile.ZipFile(built_wheel) as archive:
        archive.extractall(installed)
    script = """
import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from hiyelx.studio.launcher import STUDIO_ASSET_NAMES, _installed_asset_root, launch_studio

root = _installed_asset_root()
opened = []
ready = []

def open_browser(url):
    opened.append(url)
    return True

async def stop_immediately():
    return None

asyncio.run(launch_studio(
    browser_opener=open_browser,
    ready_callback=lambda: ready.append(True),
    shutdown_waiter=stop_immediately,
))
result = {
    "checkout_absent": not str(root).startswith(sys.argv[2]),
    "launched": (
        len(opened) == 1
        and opened[0].startswith("http://127.0.0.1:")
        and ready == [True]
    ),
    "names": sorted(item.name for item in root.iterdir()),
    "hashes": {
        name: hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest()
        for name in STUDIO_ASSET_NAMES
    },
}
print(json.dumps(result, sort_keys=True))
"""
    result = subprocess.run(
        (sys.executable, "-I", "-c", script, str(installed), str(ROOT)),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    resolved = json.loads(result.stdout)
    assert resolved == {
        "checkout_absent": True,
        "hashes": {
            name: hashlib.sha256((SOURCE_ASSETS / name).read_bytes()).hexdigest()
            for name in STUDIO_ASSET_NAMES
        },
        "launched": True,
        "names": sorted(STUDIO_ASSET_NAMES),
    }


@pytest.mark.parametrize("unexpected", ("extra.txt", "../escape"))
@pytest.mark.asyncio
async def test_asset_staging_rejects_non_allowlisted_entries(
    installed_asset_source: Path,
    unexpected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if unexpected == "../escape":
        (installed_asset_source / "index.html").unlink()
        unexpected = "INDEX.html"
    (installed_asset_source / unexpected).write_text("unexpected")
    monkeypatch.setattr(launcher, "_installed_asset_root", lambda: installed_asset_source)
    with pytest.raises(StudioAssetError, match="^Studio assets are unavailable\\.$"):
        await launch_studio(host_factory=lambda _root: pytest.fail("Host must not start"))


@pytest.mark.asyncio
async def test_asset_staging_rejects_symlinked_source(
    installed_asset_source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    external = tmp_path / "external.js"
    external.write_text("secret")
    linked = installed_asset_source / "app.js"
    linked.unlink()
    linked.symlink_to(external)
    monkeypatch.setattr(launcher, "_installed_asset_root", lambda: installed_asset_source)
    with pytest.raises(StudioAssetError, match="^Studio assets are unavailable\\.$"):
        await launch_studio(host_factory=lambda _root: pytest.fail("Host must not start"))


@pytest.mark.asyncio
async def test_launcher_starts_before_browser_and_cleans_up_after_normal_shutdown(
    installed_asset_source: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher, "_installed_asset_root", lambda: installed_asset_source)
    events: list[str] = []
    host: FakeHost | None = None

    def host_factory(asset_root: Path) -> StudioHostHandle:
        nonlocal host
        events.append("host-created")
        host = FakeHost(asset_root, events)
        return host

    def browser_opener(url: str) -> bool:
        assert url.endswith(CAPABILITY)
        events.append("browser-open")
        return True

    async def shutdown_waiter() -> None:
        events.append("wait")

    def ready_callback() -> None:
        events.append("ready")

    await launch_studio(
        browser_opener=browser_opener,
        host_factory=host_factory,
        ready_callback=ready_callback,
        shutdown_waiter=shutdown_waiter,
    )

    assert events == [
        "host-created",
        "host-start",
        "browser-open",
        "ready",
        "wait",
        "host-close",
    ]
    assert host is not None
    assert not host.asset_root.exists()


@pytest.mark.asyncio
async def test_failed_host_start_is_sanitized_closed_and_cleans_assets(
    installed_asset_source: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher, "_installed_asset_root", lambda: installed_asset_source)
    events: list[str] = []
    roots: list[Path] = []

    def host_factory(asset_root: Path) -> StudioHostHandle:
        roots.append(asset_root)
        return FakeHost(asset_root, events, fail_start=True)

    with pytest.raises(
        StudioLauncherLifecycleError,
        match="^Studio launcher lifecycle failed\\.$",
    ) as caught:
        await launch_studio(
            browser_opener=lambda _url: pytest.fail("browser must not open"),
            host_factory=host_factory,
            ready_callback=lambda: pytest.fail("readiness must not be reported"),
        )

    assert caught.value.__cause__ is None
    assert events == ["host-start", "host-close"]
    assert len(roots) == 1 and not roots[0].exists()


@pytest.mark.parametrize("raises", (False, True))
@pytest.mark.asyncio
async def test_browser_open_failure_is_sanitized_and_cleans_everything(
    installed_asset_source: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    raises: bool,
) -> None:
    monkeypatch.setattr(launcher, "_installed_asset_root", lambda: installed_asset_source)
    events: list[str] = []
    roots: list[Path] = []

    def host_factory(asset_root: Path) -> StudioHostHandle:
        roots.append(asset_root)
        return FakeHost(asset_root, events)

    def browser_opener(_url: str) -> bool:
        events.append("browser-open")
        if raises:
            raise OSError(f"private capability={CAPABILITY} pid=123")
        return False

    with pytest.raises(
        StudioBrowserOpenError,
        match="^Studio browser could not be opened\\.$",
    ) as caught:
        await launch_studio(
            browser_opener=browser_opener,
            host_factory=host_factory,
            ready_callback=lambda: pytest.fail("readiness must not be reported"),
        )

    captured = capsys.readouterr()
    assert caught.value.__cause__ is None
    assert captured.out == captured.err == ""
    assert CAPABILITY not in caplog.text
    assert events == ["host-start", "browser-open", "host-close"]
    assert len(roots) == 1 and not roots[0].exists()


@pytest.mark.asyncio
async def test_normal_close_failure_is_a_fixed_lifecycle_error(
    installed_asset_source: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher, "_installed_asset_root", lambda: installed_asset_source)
    events: list[str] = []
    roots: list[Path] = []

    def host_factory(asset_root: Path) -> StudioHostHandle:
        roots.append(asset_root)
        return FakeHost(asset_root, events, fail_close=True)

    async def shutdown_waiter() -> None:
        return None

    with pytest.raises(
        StudioLauncherLifecycleError,
        match="^Studio launcher lifecycle failed\\.$",
    ):
        await launch_studio(
            browser_opener=lambda _url: True,
            host_factory=host_factory,
            shutdown_waiter=shutdown_waiter,
        )

    assert events == ["host-start", "host-close"]
    assert len(roots) == 1 and not roots[0].exists()


@pytest.mark.asyncio
async def test_asset_cleanup_failure_overrides_normal_completion(
    installed_asset_source: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher, "_installed_asset_root", lambda: installed_asset_source)
    events: list[str] = []
    temporary_directories: list[CleanupFailingTemporaryDirectory] = []

    def temporary_directory(*, prefix: str) -> CleanupFailingTemporaryDirectory:
        directory = CleanupFailingTemporaryDirectory(prefix=prefix)
        temporary_directories.append(directory)
        return directory

    def host_factory(asset_root: Path) -> StudioHostHandle:
        return FakeHost(asset_root, events)

    async def shutdown_waiter() -> None:
        events.append("wait")

    monkeypatch.setattr(launcher.tempfile, "TemporaryDirectory", temporary_directory)
    with pytest.raises(StudioAssetError, match="^Studio assets are unavailable\\.$") as caught:
        await launch_studio(
            browser_opener=lambda _url: events.append("browser-open") is None,
            host_factory=host_factory,
            shutdown_waiter=shutdown_waiter,
        )

    assert caught.value.__cause__ is None
    assert events == ["host-start", "browser-open", "wait", "host-close"]
    assert len(temporary_directories) == 1
    temporary = temporary_directories[0]
    assert temporary.cleanup_calls == 1
    assert temporary.removed
    assert "private" not in str(caught.value).lower()
    assert "capability" not in str(caught.value).lower()


@pytest.mark.asyncio
async def test_readiness_failure_is_sanitized_and_closes_host(
    installed_asset_source: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher, "_installed_asset_root", lambda: installed_asset_source)
    events: list[str] = []
    roots: list[Path] = []

    def host_factory(asset_root: Path) -> StudioHostHandle:
        roots.append(asset_root)
        return FakeHost(asset_root, events)

    def fail_readiness() -> None:
        events.append("ready")
        raise OSError(f"private capability={CAPABILITY}")

    with pytest.raises(
        StudioLauncherLifecycleError,
        match="^Studio launcher lifecycle failed\\.$",
    ) as caught:
        await launch_studio(
            browser_opener=lambda _url: events.append("browser-open") is None,
            host_factory=host_factory,
            ready_callback=fail_readiness,
        )

    assert caught.value.__cause__ is None
    assert events == ["host-start", "browser-open", "ready", "host-close"]
    assert len(roots) == 1 and not roots[0].exists()


@pytest.mark.asyncio
async def test_cancellation_closes_host_and_removes_assets(
    installed_asset_source: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher, "_installed_asset_root", lambda: installed_asset_source)
    events: list[str] = []
    opened = asyncio.Event()
    roots: list[Path] = []

    def host_factory(asset_root: Path) -> StudioHostHandle:
        roots.append(asset_root)
        return FakeHost(asset_root, events)

    def browser_opener(_url: str) -> bool:
        events.append("browser-open")
        opened.set()
        return True

    async def shutdown_waiter() -> None:
        events.append("wait")
        await asyncio.Event().wait()

    task = asyncio.create_task(
        launch_studio(
            browser_opener=browser_opener,
            host_factory=host_factory,
            shutdown_waiter=shutdown_waiter,
        )
    )
    await asyncio.wait_for(opened.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert events == ["host-start", "browser-open", "wait", "host-close"]
    assert len(roots) == 1 and not roots[0].exists()


@pytest.mark.asyncio
async def test_close_failure_overrides_cancellation_with_lifecycle_error(
    installed_asset_source: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher, "_installed_asset_root", lambda: installed_asset_source)
    events: list[str] = []
    opened = asyncio.Event()
    roots: list[Path] = []

    def host_factory(asset_root: Path) -> StudioHostHandle:
        roots.append(asset_root)
        return FakeHost(asset_root, events, fail_close=True)

    def browser_opener(_url: str) -> bool:
        events.append("browser-open")
        opened.set()
        return True

    async def shutdown_waiter() -> None:
        events.append("wait")
        await asyncio.Event().wait()

    task = asyncio.create_task(
        launch_studio(
            browser_opener=browser_opener,
            host_factory=host_factory,
            shutdown_waiter=shutdown_waiter,
        )
    )
    await asyncio.wait_for(opened.wait(), timeout=1)
    task.cancel()
    with pytest.raises(
        StudioLauncherLifecycleError,
        match="^Studio launcher lifecycle failed\\.$",
    ):
        await task

    assert events == ["host-start", "browser-open", "wait", "host-close"]
    assert len(roots) == 1 and not roots[0].exists()


@pytest.mark.asyncio
async def test_asset_cleanup_failure_overrides_cancellation(
    installed_asset_source: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher, "_installed_asset_root", lambda: installed_asset_source)
    events: list[str] = []
    opened = asyncio.Event()
    temporary_directories: list[CleanupFailingTemporaryDirectory] = []

    def temporary_directory(*, prefix: str) -> CleanupFailingTemporaryDirectory:
        directory = CleanupFailingTemporaryDirectory(prefix=prefix)
        temporary_directories.append(directory)
        return directory

    def host_factory(asset_root: Path) -> StudioHostHandle:
        return FakeHost(asset_root, events)

    def browser_opener(_url: str) -> bool:
        events.append("browser-open")
        opened.set()
        return True

    async def shutdown_waiter() -> None:
        events.append("wait")
        await asyncio.Event().wait()

    monkeypatch.setattr(launcher.tempfile, "TemporaryDirectory", temporary_directory)
    task = asyncio.create_task(
        launch_studio(
            browser_opener=browser_opener,
            host_factory=host_factory,
            shutdown_waiter=shutdown_waiter,
        )
    )
    await asyncio.wait_for(opened.wait(), timeout=1)
    task.cancel()
    with pytest.raises(StudioAssetError, match="^Studio assets are unavailable\\.$") as caught:
        await task

    assert caught.value.__cause__ is None
    assert events == ["host-start", "browser-open", "wait", "host-close"]
    assert len(temporary_directories) == 1
    temporary = temporary_directories[0]
    assert temporary.cleanup_calls == 1
    assert temporary.removed
    assert "private" not in str(caught.value).lower()
    assert "capability" not in str(caught.value).lower()


@pytest.mark.asyncio
async def test_launcher_owns_only_host_lifecycle_and_never_runtime_operations(
    installed_asset_source: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher, "_installed_asset_root", lambda: installed_asset_source)
    events: list[str] = []

    def host_factory(asset_root: Path) -> StudioHostHandle:
        return FakeHost(asset_root, events)

    async def shutdown_waiter() -> None:
        events.append("wait")

    def browser_opener(_url: str) -> bool:
        events.append("browser-open")
        return True

    await launch_studio(
        browser_opener=browser_opener,
        host_factory=host_factory,
        shutdown_waiter=shutdown_waiter,
    )

    source = inspect.getsource(launcher)
    assert "hiyelx.runtime" not in source
    assert "request_stop" not in source
    assert "run_local_runtime" not in source
    assert events == ["host-start", "browser-open", "wait", "host-close"]


def _assert_private_staged_assets(root: Path) -> None:
    root_status = root.lstat()
    assert stat.S_ISDIR(root_status.st_mode)
    assert stat.S_IMODE(root_status.st_mode) == 0o700
    assert root_status.st_uid == os.geteuid()
    assert {path.name for path in root.iterdir()} == set(STUDIO_ASSET_NAMES)
    for name in STUDIO_ASSET_NAMES:
        status = (root / name).lstat()
        assert stat.S_ISREG(status.st_mode)
        assert not stat.S_ISLNK(status.st_mode)
        assert stat.S_IMODE(status.st_mode) == 0o600
        assert status.st_uid == os.geteuid()
        assert (root / name).read_bytes() == (SOURCE_ASSETS / name).read_bytes()
