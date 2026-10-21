"""Exercise the actual input UI on the disposable read-only emulator-5580.

Requires an empty app ledger; refuses to clear existing data. ASCII fixture labels
avoid relying on a particular Android keyboard's Japanese input support.
"""
import json
import re
import sqlite3
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).parents[1]
ADB = str(Path.home() / 'AppData/Local/Android/Sdk/platform-tools/adb.exe')
SERIAL = 'emulator-5580'
PACKAGE = 'jp.local.pachiboledger'


def adb(*args, binary=False):
    return subprocess.check_output([ADB, '-s', SERIAL, *args],
                                   **({} if binary else dict(text=True, encoding='utf-8', errors='replace')))


def ui():
    adb('shell', 'uiautomator', 'dump', '/sdcard/session-flow-test.xml')
    return ET.fromstring(adb('shell', 'cat', '/sdcard/session-flow-test.xml'))


def bounds(node):
    return tuple(map(int, re.findall(r'\d+', node.attrib['bounds'])))


def node(predicate, scroll=True):
    for step in range(18 if scroll else 1):
        tree = ui()
        for item in tree.iter('node'):
            if predicate(item):
                return item
        containers = [n for n in tree.iter('node') if n.attrib.get('scrollable') == 'true']
        if not containers or not scroll:
            break
        x1, y1, x2, y2 = bounds(containers[0])
        x = str((x1+x2)//2)
        center=(y1+y2)//2
        distance=max(80,(y2-y1)//5)
        origin, destination=(center+distance,center-distance) if step<9 else (center-distance,center+distance)
        adb('shell', 'input', 'swipe', x, str(origin), x, str(destination), '300')
    raise AssertionError('UI element missing: ' + '\n'.join(n.attrib.get('text', '') for n in ui().iter('node')))


def tap(item):
    x1, y1, x2, y2 = bounds(item)
    adb('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))


def click(text):
    tap(node(lambda n: n.attrib.get('text') == text))


def enter(label, value):
    item = node(lambda n: n.attrib.get('content-desc') == label and n.attrib.get('class') == 'android.widget.EditText')
    original = item.attrib.get('text', '')
    tap(item)
    adb('shell', 'input', 'keyevent', '123')
    if original:
        adb('shell', 'input', 'keyevent', *(['67'] * len(original)))
    if value:
        adb('shell', 'input', 'text', value.replace(' ', '%s'))
    adb('shell', 'input', 'keyevent', '4')


def text_present(text):
    node(lambda n: text in n.attrib.get('text', ''))


def snapshot(name):
    (ROOT/'output'/name).write_bytes(adb('exec-out', 'screencap', '-p', binary=True))
