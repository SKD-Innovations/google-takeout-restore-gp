# Run from the repository root: pyinstaller packaging/TakeoutRestore.spec
import os
import sys
import subprocess
import shutil
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
resources = root / 'photorestore' / 'resources'
if not (resources / 'browser.json').exists() or not (resources / 'exiftool.json').exists():
    raise RuntimeError('Prepare verified browser manifest and bundled ExifTool before building.')
shutil.copyfile(root / 'USAGE.md', resources / 'USAGE.md')
subprocess.run([sys.executable, str(root / 'scripts/build_identity.py')], check=True)
datas = [(str(root / 'photorestore' / 'ui'), 'photorestore/ui'),
         (str(resources), 'photorestore/resources'),
         (str(root / 'LICENSE'), 'licenses'), (str(root / 'NOTICE'), 'licenses')]
binaries, hiddenimports = [], []
if sys.platform == 'darwin':
    helper = resources / 'native/AuthorizeReset'
    helper.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['xcrun', 'swiftc', '-O', '-target', os.uname().machine + '-apple-macos13.0',
                    str(root / 'packaging/AuthorizeReset.swift'), '-o', str(helper)], check=True, env={**os.environ, 'CLANG_MODULE_CACHE_PATH': str(root / 'build/swift-module-cache')})
    binaries += [(str(helper), 'photorestore/resources/native')]
for package in ('webview', 'playwright', 'argon2', '_argon2_cffi_bindings'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
if sys.platform.startswith('linux'):
    hiddenimports += ['gi.repository.Gtk', 'gi.repository.WebKit2', 'gi.repository.JavaScriptCore', 'gi.repository.Soup']
# ExifTool is executable, not a data file. This allows PyInstaller's macOS signer to sign it.
exif = resources / 'exiftool' / ('exiftool.exe' if sys.platform == 'win32' else 'exiftool')
if sys.platform == 'win32':
    binaries += [(str(exif), 'photorestore/resources/exiftool')]
else:
    binaries += [(str(resources / 'exiftool/perl/bin/perl'), 'photorestore/resources/exiftool/perl/bin')]
a = Analysis([str(root / 'pipeline.py')], pathex=[str(root)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[str(root / 'packaging/hooks')],
             hooksconfig={'gi': {'versions': {'Gtk': '3.0', 'WebKit2': '4.1', 'JavaScriptCore': '4.1', 'Soup': '3.0'}}}, excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'tkinter'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TakeoutRestore', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=str(root / 'packaging/icon.ico') if sys.platform == 'win32' else None,
          codesign_identity=os.environ.get('MAC_SIGN_IDENTITY') or None,
          entitlements_file=str(root / 'packaging/entitlements.plist') if sys.platform == 'darwin' else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='TakeoutRestore')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='Takeout Restore.app', icon=str(root / 'packaging/icon.icns'), bundle_identifier='org.takeoutrestore.desktop',
                 info_plist={'CFBundleName':'Takeout Restore', 'CFBundleDisplayName':'Takeout Restore',
                             'CFBundleInfoDictionaryVersion':'6.0',
                             'LSApplicationCategoryType':'public.app-category.photography',
                             'CFBundleSupportedPlatforms':['MacOSX'],
                             'NSHumanReadableCopyright':'Copyright 2026 Takeout Restore contributors',
                             'CFBundleShortVersionString':'0.2.0', 'CFBundleVersion':'0.2.0', 'LSMinimumSystemVersion':'13.0',
                             'NSHighResolutionCapable':True,
                             'NSDocumentsFolderUsageDescription':'Choose extracted Takeout folders for restoration.',
                             'NSRemovableVolumesUsageDescription':'Read Takeout exports on external drives.'})
