"""Run against the disposable emulator-5580 only, after installing the debug APK.

Uses synthetic fixture data; never selects a physical device.
"""
import subprocess
import time
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ADB = str(Path.home() / 'AppData/Local/Android/Sdk/platform-tools/adb.exe')
SERIAL = 'emulator-5580'
PACKAGE = 'jp.local.pachiboledger'
ROOT = Path(__file__).parents[1]


def adb(*args):
    return subprocess.check_output([ADB, '-s', SERIAL, *args], text=True, encoding='utf-8', errors='replace')


def ui():
    adb('shell','uiautomator','dump','/sdcard/tag-test.xml')
    return ET.fromstring(adb('shell','cat','/sdcard/tag-test.xml'))


def node(predicate, scroll=False):
    for _ in range(6 if scroll else 1):
        for item in ui().iter('node'):
            if predicate(item):
                return item
        if scroll:
            adb('shell','input','swipe','540','1900','540','700','400')
    raise AssertionError('UI element not found')


def tap(item):
    x1,y1,x2,y2 = map(int,re.findall(r'\d+',item.attrib['bounds']))
    adb('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2))


def click(text, scroll=False):
    tap(node(lambda n:n.attrib.get('text')==text,scroll))


def texts():
    return '\n'.join(n.attrib.get('text','') for n in ui().iter('node'))


for _ in range(60):
    if adb('shell','getprop','sys.boot_completed').strip()=='1':
        break
    time.sleep(1)
else:
    raise AssertionError('Emulator did not boot')
adb('install','-r',str(ROOT/'android/app/build/outputs/apk/debug/app-debug.apk'))
adb('shell','am','start','-n',PACKAGE+'/.MainActivity')
node(lambda n:n.attrib.get('text')=='記録')
adb('shell','am','force-stop',PACKAGE)
adb('push',str(ROOT/'output/android-analysis-fixture.db'),'/data/local/tmp/tag-fixture.db')
adb('shell','run-as',PACKAGE,'cp','/data/local/tmp/tag-fixture.db','databases/ledger.db')
adb('shell','am','start','-n',PACKAGE+'/.MainActivity')
click('タグを編集')
tap(node(lambda n:n.attrib.get('class')=='android.widget.EditText'))
adb('shell','input','text','alpha,beta')
adb('shell','input','keyevent','4')
click('タグを作成して選択')
click('適用')
assert 'タグ：「alpha,beta」' in texts(), 'Comma tag was split or not saved'
adb('shell','am','force-stop',PACKAGE)
adb('shell','am','start','-n',PACKAGE+'/.MainActivity')
assert 'タグ：「alpha,beta」' in texts(), 'Tag did not survive restart'
tap(node(lambda n:'2026-10-17 MACHINE A A番' in n.attrib.get('text','').upper(),True))
click('タグを編集')
click('alpha,beta')
click('適用')
click('分析')
click('絞り込むタグを選択',True)
click('alpha,beta')
click('適用')
click('集計する',True)
result=texts()
if '評価収支 2000円' not in result:
    adb('shell','input','swipe','540','1800','540','900','400')
    result=texts()
assert '評価収支 2000円' in result and '現金収支 -10000円' in result, result
assert '対象：1件 ／ 遊技中 1件を除外' in result, result
print('PASS: comma tag creation, persistence across restart, ended-session edit, exact filter and active exclusion')
