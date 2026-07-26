# -*- mode: python ; coding: utf-8 -*-


block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets/pet_cropped.png", "assets"),
        ("assets/pet.ico", "assets"),
        ("assets/poses_v2/typing_left.png", "assets/poses_v2"),
        ("assets/poses_v2/typing_right.png", "assets/poses_v2"),
        ("assets/poses_v2/mouse_ready.png", "assets/poses_v2"),
        ("assets/poses_v2/mouse_click.png", "assets/poses_v2"),
        ("assets/poses_v2/idle_yawn.png", "assets/poses_v2"),
        ("assets/poses_v2/idle_stretch.png", "assets/poses_v2"),
        ("assets/poses_v2/idle_look_left.png", "assets/poses_v2"),
        ("assets/poses_v2/idle_look_right.png", "assets/poses_v2"),
        ("assets/poses_v2/idle_wave.png", "assets/poses_v2"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6"],
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
    name="DoudouDesktopPet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/pet.ico"],
    version="version_info.txt",
)
