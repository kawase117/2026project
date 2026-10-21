"""Run after verify_session_flow on its disposable emulator; exercise legacy editor and filters."""
from android_ui_helpers import *


def choose_list(label, name):
    click(label+'を一覧から選択')
    click(name)


def choose_spinner(label, value):
    tap(node(lambda n:n.attrib.get('content-desc')==label))
    click(value)


def picker(label):
    tap(node(lambda n:n.attrib.get('content-desc')==label))
    # The system picker language follows the emulator locale, not the app labels.
    tap(node(lambda n:n.attrib.get('resource-id')=='android:id/button1', False))


adb('shell','am','force-stop',PACKAGE)
adb('shell','am','start','-n',PACKAGE+'/.MainActivity')
click('ぱち簿から移行した記録・従来の記録')
click('＋ 記録を追加')
choose_list('ホール','Flow Hall Fixed')
choose_list('機種','Machine B2')
enter('台番号','99')
enter('現金投資（円）','0')
enter('玉・メダル投資（玉・枚数）','100')
enter('現金回収（円）','0')
enter('玉・メダル回収（玉・枚数）','200')
enter('交換率：円','100')
enter('上記の円に交換できる枚数・玉数','5')
text_present('収支 +2,000円')
snapshot('usability-quantity-android.png')
picker('開始時刻')
picker('終了時刻')
enter('メモ（立ち回り・気づいたことなど）','legacy quantity note')
click('保存')
print('LEGACY_QUANTITY_TIME_PASS',flush=True)
tap(node(lambda n:'Machine B2 99番' in n.attrib.get('text','')))
assert node(lambda n:n.attrib.get('content-desc')=='玉・メダル投資（玉・枚数）').attrib['text']=='100'
click('戻る')
click('分析')
picker('開始日')
picker('終了日')
choose_list('ホール','Flow Hall Fixed')
choose_list('機種','Machine B2')
click('集計する')
text_present('対象：1件')
print('REPORT_PICKERS_PASS',flush=True)
adb('shell','am','force-stop',PACKAGE)
db_path=ROOT/'output/usability-result.db'
db_path.write_bytes(adb('exec-out','run-as',PACKAGE,'cat','databases/ledger.db',binary=True))
with sqlite3.connect(db_path) as db:
    row=db.execute('SELECT r.investment_yen,r.recovery_yen,r.profit_yen,d.payload,r.date FROM records r JOIN record_details d ON r.id=d.id').fetchone()
    assert row[:3]==(2000,4000,2000),row
    payload=json.loads(row[3]); assert payload['investment_quantity_input']=='100' and payload['recovery_quantity_input']=='200'
    assert payload['started_at'] is not None and payload['ended_at']>=payload['started_at']
    month=row[4][:7]
    # Add isolated, clearly synthetic days to inspect both signs in the calendar.
    for identifier,day,profit in [('ui-positive','01',12345),('ui-negative','02',-5432)]:
        db.execute('INSERT INTO records (id,date,hall,kind,machine,investment_yen,recovery_yen,profit_yen,tag_ids) VALUES (?,?,?,?,?,?,?,?,?)',
                   (identifier,month+'-'+day,'UI Fixture','スロット','UI Fixture',max(-profit,0),max(profit,0),profit,'[]'))
adb('push',str(db_path),'/data/local/tmp/usability-fixture.db')
adb('shell','run-as',PACKAGE,'cp','/data/local/tmp/usability-fixture.db','databases/ledger.db')
adb('shell','am','start','-n',PACKAGE+'/.MainActivity')
click('カレンダー')
text_present('+12,345')
text_present('-5,432')
snapshot('usability-calendar-android.png')
print('USABILITY_PASS: list selection, coin conversion, dates/times, persisted input units, report pickers and signed calendar',flush=True)
