"""Exercise the current one-screen flow on a fresh disposable emulator-5580."""
import json
import sqlite3
import time

from android_ui_helpers import ROOT, PACKAGE, adb, click, enter, node, snapshot, tap, text_present, ui


def database():
    data = adb('exec-out', 'run-as', PACKAGE, 'cat', 'databases/ledger.db', binary=True)
    target = ROOT / 'output' / 'current-ui-result.db'
    target.write_bytes(data)
    return target


adb('shell', 'am', 'start', '-n', PACKAGE + '/.MainActivity')
time.sleep(2)
db_path = database()
with sqlite3.connect(db_path) as connection:
    assert connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0, 'AVD must be empty'
    assert connection.execute('SELECT COUNT(*) FROM records').fetchone()[0] == 0, 'AVD must be empty'

tap(node(lambda item: item.attrib.get('text', '').endswith(' の遊技を開始')))
text_present('遊技日 ')
enter('ホール', 'FlowHall')
enter('機種', 'FlowMachine')
enter('台番号', '001')
snapshot('current-ui-start.png')
click('保存')
text_present('遊技中の台を終了・入力')

click('遊技中の台を終了・入力')
tap(node(lambda item: item.attrib.get('content-desc') == '終了時刻（遊技中は空欄）'))
tap(node(lambda item: item.attrib.get('resource-id') == 'android:id/button1', False))
enter('現金投資（円）', '10000')
enter('現金回収（円）', '16000')
snapshot('current-ui-finish.png')
click('保存')
text_present('+6,000円')

db_path = database()
with sqlite3.connect(db_path) as connection:
    session = connection.execute('SELECT id,state,metadata FROM sessions').fetchone()
    operations = connection.execute('SELECT kind,delta FROM operations').fetchall()
assert session and session[1] == 'ended', session
assert json.loads(session[2])['number'] == '001', session
assert sorted((kind, delta) for kind, delta in operations if delta != 0) == [
    ('cash', -10000), ('cash', 16000)
], operations

click('分析')
text_present('経費込みの収支  +6,000円')
snapshot('current-ui-analysis.png')
click('カレンダー')
tap(node(lambda item: 'FlowMachine 001番' in item.attrib.get('text', '')))
click('開いて編集')
enter('現金回収（円）', '15000')
click('保存')
text_present('+5,000円')

tap(node(lambda item: 'FlowMachine 001番' in item.attrib.get('text', '')))
click('削除')
click('削除')
db_path = database()
with sqlite3.connect(db_path) as connection:
    assert connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0
    assert connection.execute('SELECT COUNT(*) FROM operations').fetchone()[0] == 0
text_present('確定収支はありません')
print('CURRENT_UI_PASS: start, finish, cash profit, analysis, edit, delete')
