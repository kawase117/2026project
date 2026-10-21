"""Compare Android's real-file export with the Python parser and original bytes."""
import base64
import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).parents[1]/'tools'))
from import_pachibo import create_export, RECORD

original=Path(sys.argv[1])
expected=create_export(original)
with zipfile.ZipFile(sys.argv[2]) as archive:
    backup=json.loads(archive.read('backup.json'))
    records={r['id']:r for r in backup['records']}
    reference={r['id']:r for r in expected['portable']['records']}
    assert records==reference, 'Android and Python normalized records differ'
    for table in ('records','tags','sessions','operations','transfers','source_archives'):
        rows=list(csv.DictReader(io.StringIO(archive.read(table+'.csv').decode('utf-8-sig'))))
        assert len(rows)==len(backup[table]),table
        for row,item in zip(rows,backup[table]):
            nulls=json.loads(row.pop('__null_fields'))
            for key,value in item.items():
                if value is None:
                    assert key in nulls and row[key]=='',(table,key)
                elif isinstance(value,(list,dict)):
                    assert json.loads(row[key])==value,(table,key)
                else:
                    assert row[key]==str(value),(table,key)
    source_index=list(csv.DictReader(io.StringIO(archive.read('source_index.csv').decode('utf-8-sig'))))
    assert len(source_index)==1
    folder=source_index[0]['folder']
    payload=json.loads(archive.read(folder+'payload.json'))
    raw=original.read_bytes()
    assert archive.read(folder+'original.pcb')==raw
    assert base64.b64decode(payload['source_pcb_base64'])==raw
    assert hashlib.sha256(raw).hexdigest()==payload['source_sha256']
    decoded=bytes(b^255 for b in raw).decode('utf-8')
    matches=list(RECORD.finditer(decoded))
    assert len(matches)==len(payload['raw_entries'])
    for i,(match,row) in enumerate(zip(matches,payload['raw_entries'])):
        end=matches[i+1].start()-1 if i+1<len(matches) else len(decoded)
        assert row['ordinal']==i and row['key']==match.group(2) and row['type']==match.group(1)
        assert row['declared_length']==int(match.group(3)) and row['value']==decoded[match.end():end]
    relations=list(csv.DictReader(io.StringIO(archive.read('record_tags.csv').decode('utf-8-sig'))))
    expected_relations={(r['id'],tag) for r in records.values() for tag in r['tag_ids']}
    assert {(r['record_id'],r['tag_id']) for r in relations}==expected_relations
    report={'records_equal':len(records),'raw_entries_equal':len(matches),'tag_relationships_equal':len(relations),
            'original_sha256':hashlib.sha256(raw).hexdigest(),'all_csv_tables_equal':True}
    print(json.dumps(report,ensure_ascii=False,indent=2))
