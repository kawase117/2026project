import re, glob
from collections import defaultdict
import os

files = sorted(glob.glob('document/instincts/*.yaml'))
instincts = []

for fpath in files:
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = re.split(r'\n---\n', content)
    for block in blocks:
        block = block.strip().lstrip('-').strip()
        if not block:
            continue
        meta = {}
        for line in block.split('\n')[:15]:
            if ':' in line and not line.startswith('#'):
                key, _, val = line.partition(':')
                meta[key.strip()] = val.strip().strip('"')

        inst_id = meta.get('id', '')
        if inst_id:
            fname = os.path.basename(fpath)
            instincts.append({
                'file': fname,
                'id': inst_id,
                'trigger': meta.get('trigger', ''),
                'domain': meta.get('domain', 'unknown'),
                'confidence': meta.get('confidence', '0')
            })

print(f'Total instincts: {len(instincts)}')
print()
by_domain = defaultdict(list)
for i in instincts:
    by_domain[i['domain']].append(i)

for domain, items in sorted(by_domain.items(), key=lambda x: -len(x[1])):
    print(f'[{len(items)}] {domain}')
    for item in items[:5]:
        try:
            conf = float(item['confidence'])
        except Exception:
            conf = 0
        pct = int(conf * 100)
        print(f'    {pct:3d}% | {item["id"]}')
        if item['trigger']:
            print(f'         trigger: {item["trigger"][:90]}')
    if len(items) > 5:
        print(f'    ... +{len(items)-5} more')
    print()
