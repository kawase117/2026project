"""Independently parse the Android-produced archive using Python's CSV/ZIP readers."""
import base64
import csv
import io
import json
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    backup = json.loads(archive.read('backup.json'))
    for table in ('records','tags','sessions','operations','transfers','source_archives','edit_history','accounts','catalog','record_details'):
        parsed = list(csv.DictReader(io.StringIO(archive.read(table+'.csv').decode('utf-8-sig'))))
        expected = backup[table]
        assert len(parsed) == len(expected), table
        for row, original in zip(parsed, expected):
            nulls = json.loads(row.pop('__null_fields'))
            for key, value in original.items():
                if value is None:
                    assert key in nulls and row[key] == '', (table,key)
                elif isinstance(value,(list,dict)):
                    assert json.loads(row[key]) == value, (table,key)
                else:
                    assert key not in nulls and row[key] == str(value), (table,key)
    relations = list(csv.DictReader(io.StringIO(archive.read('record_tags.csv').decode('utf-8-sig'))))
    assert len(relations) == 3, relations
    sources = list(csv.DictReader(io.StringIO(archive.read('source_index.csv').decode('utf-8-sig'))))
    for source in sources:
        folder = source['folder']
        payload = json.loads(archive.read(folder+'payload.json'))
        if 'source_pcb_base64' in payload:
            assert archive.read(folder+'original.pcb') == base64.b64decode(payload['source_pcb_base64'])
    assert next(row for row in backup['records'] if row['id']=='legacy')['memo'] is None
    assert backup['tags'][0]['name'] == '朝一,特日\n🎰"試験"'
print('PASS: independent CSV parse matches all 10 tables, tag relationships, NULL, punctuation, emoji and PCB bytes')
