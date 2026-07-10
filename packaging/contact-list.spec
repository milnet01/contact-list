# PyInstaller recipe shared by all three OS builds.
# Run from the repo root: pyinstaller packaging/contact-list.spec
# onefile on Windows (single .exe); onedir elsewhere (wrapped by AppImage/.app).
import os
import sys

from PyInstaller.utils.hooks import collect_all

# PyInstaller exposes the .spec file's directory as the SPECPATH global but does
# NOT auto-resolve Analysis' relative source paths against it — bare relative
# paths resolve against the invoking CWD. So we anchor EVERY source path
# (entry script, datas, icons) on the repo root explicitly, making them resolve
# regardless of the CWD PyInstaller was invoked from.
ROOT = os.path.dirname(os.path.abspath(SPECPATH))  # noqa: F821 (injected by PyInstaller)

datas = [
    (os.path.join(ROOT, 'templates'), 'templates'),
    (os.path.join(ROOT, 'static'), 'static'),
    (os.path.join(ROOT, 'migrations'), 'migrations'),
]
binaries = []
hiddenimports = []

# These load submodules dynamically and/or ship package data the import scan
# misses; collect_all gathers modules + data + dylibs. Finalise empirically:
# if a frozen run raises ModuleNotFoundError / missing-data, add the package here.
for _pkg in ('googleapiclient', 'google_auth_oauthlib', 'google.auth',
             'google_auth_httplib2', 'phonenumbers'):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

a = Analysis(
    [os.path.join(ROOT, 'launcher.py')],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['pytest'],
)
pyz = PYZ(a.pure)

if sys.platform.startswith('win'):
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name='Contact-List', console=False,
        icon=os.path.join(ROOT, 'packaging', 'icon.ico'),
    )
else:
    _icon_name = 'icon.icns' if sys.platform == 'darwin' else 'contact-list.png'
    _icon = os.path.join(ROOT, 'packaging', _icon_name)
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True,
        name='Contact-List', console=False, icon=_icon,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name='Contact-List')
    if sys.platform == 'darwin':
        app = BUNDLE(
            coll, name='Contact List.app',
            icon=os.path.join(ROOT, 'packaging', 'icon.icns'),
            bundle_identifier='com.contactlist.app',
        )
