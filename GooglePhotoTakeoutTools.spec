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
    'sqlite3',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'src.core.models',
    'src.core.utils',
    'src.core.parser',
    'src.core.matcher',
    'src.core.exif_writer',
    'src.core.os_sync',
    'src.services.process_service',
    'src.data.database',
    'src.data.repositories.media_repo',
    'src.ui.theme',
    'src.ui.workers',
    'src.ui.components.sidebar_widget',
    'src.ui.views.dashboard_view',
    'src.ui.views.job_view',
    'src.ui.views.history_view',
    'src.ui.views.library_view',
    'src.ui.views.settings_view',
    'src.ui.main_window',
]

datas = []

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
        icon=None,
        bundle_identifier='com.littleplanet.googlephototakeouttools',
        info_plist={
            'CFBundleShortVersionString': '0.3.0',
            'CFBundleVersion': '0.3.0',
            'NSHighResolutionCapable': 'True',
            'NSRequiresAquaSystemAppearance': 'False',
        },
    )
