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
    (os.path.join(ROOT, 'packaging', 'icon.png'), 'packaging'),
]
binaries = []
# pystray's Linux appindicator backend loads these GObject-Introspection
# namespaces dynamically at runtime, so PyInstaller's static scan misses them and
# doesn't collect their typelibs. DBus is the critical one: pystray/_util/
# notify_dbus.py does `gi.require_version('DBus', '1.0')`, and without the bundled
# DBus-1.0.typelib the tray dies with "Namespace DBus not available" and falls
# back to headless (CL-0052). Listing them makes PyInstaller's built-in gi hooks
# collect each namespace's typelib (+ libs). Harmless on Windows/macOS (no gi).
hiddenimports = [
    'gi.repository.DBus',
    # Both indicator namespaces, because build-linux.sh's pre-flight accepts
    # EITHER: it probes classic AppIndicator3 first and falls back to Ayatana.
    # Listing only Ayatana meant that on a host carrying the classic typelib the
    # probe passed, PyInstaller then could not resolve the hidden import, logged
    # a warning and exited 0 -- shipping a tray-less AppImage, which is the CL-0057
    # failure that pre-flight exists to prevent.
    'gi.repository.AppIndicator3',
    'gi.repository.AyatanaAppIndicator3',
]

# These load submodules dynamically and/or ship package data the import scan
# misses; collect_all gathers modules + data + dylibs. Finalise empirically:
# if a frozen run raises ModuleNotFoundError / missing-data, add the package here.
# `google.oauth2` is listed for the same reason as `google.auth`, and its
# absence was a SHIPPED defect, not a build-log annoyance: the frozen /sync page
# raised ModuleNotFoundError: No module named 'google.oauth2' and returned 500,
# so Google sync did not work in a locally built AppImage at all.
#
# Cause (measured 2026-09-07). `google` is a namespace package. run.sh builds
# its venv with --system-site-packages, which CL-0057 requires so the tray can
# import the system PyGObject -- and the distro ships
# /usr/lib64/.../site-packages/google as a REGULAR package, an __init__.py
# calling pkgutil.extend_path. Under PEP 420 a regular package anywhere on
# sys.path wins outright over the namespace portions on earlier entries, so
# `google` resolves to the distro copy, which has no `auth` or `oauth2`
# subpackage. PyInstaller's scan then cannot see either, and google_sync.py
# imports google.oauth2.credentials INSIDE its functions, so nothing else
# dragged it in.
#
# It is a path-RESOLUTION problem, not a path-ORDER one: `pathex` does not fix
# it (measured -- still sixty errors). Dropping --system-site-packages would fix
# it and reintroduce CL-0057, shipping a tray-less AppImage. Naming the
# subpackages explicitly is what works.
#
# CL-0061 tracks the sixty "Hidden import not found" lines this still logs. Do
# not silence them by removing these entries: that produces a bundle with no
# _internal/google/ directory at all.
for _pkg in ('googleapiclient', 'google_auth_oauthlib', 'google.auth',
             'google.oauth2', 'google_auth_httplib2', 'phonenumbers'):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# Windows has no system tz database, so CPython's zoneinfo falls back to the
# `tzdata` package. Without it `available_timezones()` returns an empty set on
# the shipped .exe: the Settings timezone control renders with no options, every
# timezone save fails, and ZoneInfo() raises -- which app.py swallows, so every
# timestamp in the app degrades to a raw ISO string. Build-time only (§3 keeps
# build deps out of the 8-package runtime budget), and only where it is needed;
# Linux and macOS take their zone data from the OS.
if sys.platform == 'win32':
    _d, _b, _h = collect_all('tzdata')
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
