# pyinstaller build/pyinstaller.spec
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]

block_cipher = None

added_files = [
    (str(repo_root / "frontend" / "src"), "frontend/src"),
    (str(repo_root / "config.txt"), "."),
]

a = Analysis(
    [str(repo_root / "app" / "launcher.py")],
    pathex=[str(repo_root)],
    binaries=[],
    datas=added_files,
    hiddenimports=["api.server", "bot", "core.monitors", "flask", "jinja2", "werkzeug"],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="TradingBot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
