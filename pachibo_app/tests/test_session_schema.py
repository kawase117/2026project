"""Verify the actual Java DDL against SQLite, without touching the user's ledger."""
import re
import sqlite3
import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[1] / 'android/app/src/main/java/jp/local/pachiboledger'


def ddl(name):
    return re.findall(r'db\.execSQL\("(CREATE [^"]+)"\)', (SOURCE / name).read_text(encoding='utf-8'))


class SessionSchemaTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('PRAGMA foreign_keys=ON')
        for sql in ddl('LedgerDb.java'):
            self.db.execute(sql)
        self.db.execute("INSERT INTO records (id,date,hall,kind,machine,investment_yen,recovery_yen,profit_yen,tag_ids,memo) VALUES ('legacy','2026-10-18','店','スロット','台',1000,3000,2000,'[\"tag1\"]','旧記録')")
        self.before = self.db.execute('SELECT * FROM records').fetchall()
        for sql in ddl('SessionStore.java'):
            self.db.execute(sql)
        for sql in ddl('AccountStore.java') + ddl('Catalog.java'):
            self.db.execute(sql)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def start(self, identifier):
        self.db.execute("INSERT INTO sessions VALUES (?, '2026-10-18','account','active','{}',1,NULL)", (identifier,))

    def test_migration_preserves_legacy(self):
        self.assertEqual(self.before, self.db.execute('SELECT * FROM records').fetchall())

    def test_single_active(self):
        self.start('A')
        with self.assertRaises(sqlite3.IntegrityError):
            self.start('B')

    def test_failed_transfer_rolls_back_both_sessions(self):
        self.start('A')
        self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                self.db.execute("UPDATE sessions SET state='ended' WHERE id='A'")
                self.start('B')
                self.db.execute("INSERT INTO transfers VALUES ('t','A','B',-1,20,1)")
        self.assertEqual([('A', 'active')], self.db.execute('SELECT id,state FROM sessions').fetchall())

    def test_rate_and_foreign_key_checks(self):
        self.start('A')
        for session, yen, units in [('missing',20,1), ('A',20,None), ('A',None,1), ('A',0,1)]:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute("INSERT INTO operations VALUES ('o',?,'quantity',-100,?,?,1)", (session,yen,units))

    def test_duplicate_operation_rejected(self):
        self.start('A')
        sql = "INSERT INTO operations VALUES ('o','A','cash',-1000,NULL,NULL,1)"
        self.db.execute(sql)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(sql)
        self.assertEqual(-1000, self.db.execute('SELECT SUM(delta) FROM operations').fetchone()[0])

    def test_account_rate_unit_and_duplicate_constraints(self):
        sql = 'INSERT INTO accounts VALUES (?,?,?,?,?,?)'
        self.db.execute(sql, ('account', '店', '46枚', '枚', 100, 5))
        for row in [('other', '店', '46枚', '枚', 20, 1),
                    ('bad-unit', '店', '別', '円', 20, 1),
                    ('half-rate', '店', '別', '玉', 20, None),
                    ('zero-rate', '店', '別', '玉', 0, 1)]:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql, row)
        self.db.execute(sql, ('unknown', '店', '未設定', '玉', None, None))
        self.assertEqual(2, self.db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0])


if __name__ == '__main__':
    unittest.main()
