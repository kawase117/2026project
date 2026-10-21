"""Materialize the verified backup in a NEW local fixture DB for disposable AVD UI tests."""
import json
import sqlite3
import zipfile
from pathlib import Path
from test_session_schema import ddl

root=Path(__file__).parents[1]
target=root/'output/real-preview.db'
if target.exists():
    raise SystemExit('Preview fixture exists; do not overwrite it implicitly')
with zipfile.ZipFile(root/'output/verification-real-complete.zip') as archive:
    backup=json.loads(archive.read('backup.json'))
with sqlite3.connect(target) as db:
    for sql in ddl('LedgerDb.java')+ddl('SessionStore.java') + ddl('AccountStore.java') + ddl('Catalog.java'):
        db.execute(sql)
    for table in ('records','tags','sessions','operations','transfers','source_archives','edit_history','accounts','catalog','record_details'):
        for row in backup.get(table, []):
            keys=list(row)
            values=[json.dumps(row[k],ensure_ascii=False,separators=(',',':')) if isinstance(row[k],(dict,list)) else row[k] for k in keys]
            db.execute(f'INSERT INTO {table} ({",".join(keys)}) VALUES ({",".join("?" for _ in keys)})',values)
    db.execute('PRAGMA user_version=6')
month=[r for r in backup['records'] if r['date'].startswith('2026-10') and r['match_status']!='pcb_type_missing']
print(json.dumps({'month':'2026-10','records':len(month),'profit_yen':sum(r['profit_yen'] for r in month)},ensure_ascii=False))
