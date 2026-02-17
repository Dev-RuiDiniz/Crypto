# pyinstaller build/windows/tradingbot.spec --noconfirm --clean
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

repo_root = Path.cwd()

datas = []
for src, dest in [
    (repo_root / "frontend" / "src", "frontend/src"),
    (repo_root / "frontend" / "build", "frontend/build"),
    (repo_root / "templates", "templates"),
    (repo_root / "static", "static"),
    (repo_root / "config.txt", "."),
    (repo_root / "bitt.ico", "."),
]:
    if src.exists():
        datas.append((str(src), dest))

hiddenimports = [
    "api.server",
    "api.handlers",
    "bot",
    "app.launcher",
] + collect_submodules("core") + collect_submodules("exchanges") + collect_submodules("flask")

block_cipher = None

a = Analysis(
    [str(repo_root / "app" / "launcher.py")],
    pathex=[str(repo_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TradingBot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(repo_root / "bitt.ico") if (repo_root / "bitt.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="TradingBot",
)
