# -*- mode: python ; coding: utf-8 -*-
"""
GooglePhotoTakeoutTools.spec
PyInstaller 크로스플랫폼 패키징 빌드 사양서
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None
PROJECT_ROOT = Path('.').resolve()

# 숨은 참조 및 서브모듈 수집
hidden_imports = [
    'piexif',
    'PIL',
    'PIL.Image',
    'mutagen',
    'mutagen.mp4',
    'mutagen.id3',
    'sqlite3',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
] + collect_submodules('src')

# 플랫폼별 아이콘 파일 경로
icon_win = str(PROJECT_ROOT / 'assets' / 'icons' / 'app_icon.ico')
icon_mac = str(PROJECT_ROOT / 'assets' / 'icons' / 'app_icon.icns')

datas = [
    ('assets', 'assets'),
    ('src/locales', 'src/locales'),
    ('src/locales', 'locales'),
]

a = Analysis(
    ['src/main.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'pandas',
        'unittest',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GooglePhotoTakeoutTools',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI 창만 표시 (콘솔창 숨김)
    disable_windowed_traceback=False,
    argv_emulation=True if sys.platform == 'darwin' else False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_win if sys.platform.startswith('win') else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GooglePhotoTakeoutTools',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='GooglePhotoTakeoutTools.app',
        icon=icon_mac,
        bundle_identifier='com.littleplanet.googlephototakeouttools',
        info_plist={
            'CFBundleName': 'Smile Crab',
            'CFBundleDisplayName': 'Smile Crab',
            'CFBundleShortVersionString': '0.9.1',
            'CFBundleVersion': '0.9.1',
            'NSHighResolutionCapable': 'True',
            'NSRequiresAquaSystemAppearance': 'False',
        },
    )
