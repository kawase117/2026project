"""Exercise the revised start/finish flow on disposable emulator-5580 only."""
import sqlite3
import time

from android_ui_helpers import ROOT, PACKAGE, adb, click, enter, node, snapshot, text_present, ui


def main():
    text_present('遊技を開始')
    click('ホール・交換率を登録')
    click('ホールの交換率を登録')
    enter('ホール', 'FlowHall')
    enter('交換率：円（例：100円）', '100')
    enter('上記の円に交換できる玉・枚', '5')
    click('保存')
    text_present('遊技を開始')

    click('遊技を開始')
    picker = ui()
    buttons = [n.attrib.get('text', '') for n in picker.iter('node')
               if n.attrib.get('class') == 'android.widget.Button']
    for label in ('OK', '設定', '確定'):
        if label in buttons:
            click(label)
            break
    else:
        raise AssertionError('Date picker accept button not found: ' + repr(buttons))

    text_present('遊技種別')
    enter('ホール', 'FlowHall')
    enter('機種', 'FlowMachine')
    enter('台番号', '0102')
    text_present('現在時刻を入力')
    snapshot('new-flow-start.png')
    click('保存')
    text_present('遊技完了・収支を入力')

    click('遊技完了・収支を入力')
    text_present('終了時刻')
    text_present('交換率：100円 / 5枚')
    enter('現金投資（円）', '10000')
    enter('玉・メダル投資（再プレイの玉・枚数）', '100')
    enter('現金回収（円）', '5000')
    enter('玉・メダル回収（貯玉の玉・枚数）', '200')
    text_present('保存後の収支：-3,000円')
    enter('メモ（分析に役立つ状況や判断）', 'analysis-note')
    snapshot('new-flow-finish.png')
    click('保存')
    text_present('遊技を開始')

    data = adb('exec-out', 'run-as', PACKAGE, 'cat', 'databases/ledger.db', binary=True)
    output = ROOT / 'output' / 'new-flow.db'
    output.write_bytes(data)
    with sqlite3.connect(output) as connection:
        session = connection.execute('SELECT date, state, metadata FROM sessions').fetchone()
        operations = connection.execute('SELECT kind, delta, rate_yen, rate_units FROM operations ORDER BY id').fetchall()
    assert session and session[1] == 'ended' and '"number":"0102"' in session[2], session
    assert 'analysis-note' in session[2], session
    assert sorted((kind, value) for kind, value, _, _ in operations) == sorted([
        ('cash', -10000), ('quantity', -100), ('cash', 5000), ('quantity', 200)
    ]), operations
    assert all(yen == 100 and units == 5 for kind, _, yen, units in operations if kind == 'quantity'), operations
    print('NEW_FLOW_PASS: calendar date, slot default, hall rate, numeric machine number, mixed cash/medals, finish memo')


if __name__ == '__main__':
    main()
