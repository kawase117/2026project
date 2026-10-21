"""Create synthetic ledger in output only. Never connects to an existing ledger."""
import json
import sqlite3
from pathlib import Path
from test_session_schema import ddl

target = Path(__file__).parents[1] / 'output' / 'android-analysis-fixture.db'
target.parent.mkdir(exist_ok=True)
if target.exists():
    raise SystemExit('Fixture already exists; choose a fresh fixture path before regenerating')
db = sqlite3.connect(target)
for sql in ddl('LedgerDb.java') + ddl('SessionStore.java') + ddl('AccountStore.java') + ddl('Catalog.java'):
    db.execute(sql)
for identifier, date, machine, state in [
    ('A','2026-10-17','Machine A','ended'),
    ('B','2026-10-17','Machine B','ended'),
    ('C','2026-10-18','Machine A','ended'),
    ('D','2026-10-18','Machine C','active')]:
    db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?)',
        (identifier,date,'sample-medals',state,json.dumps({'hall':'Sample Hall','machine':machine,'number':identifier}),1,None if state=='active' else 2))
for row in [('a','A','cash',-10000,None,None,1),('b','B','cash',16000,None,None,1),
            ('c1','C','quantity',-100,20,1,1),('c2','C','quantity',300,20,1,1),
            ('d','D','cash',-5000,None,None,1)]:
    db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?)',row)
db.execute("INSERT INTO transfers VALUES ('t','A','B',600,20,1)")
db.execute('PRAGMA user_version=6')
db.commit()
db.close()
print(target)
