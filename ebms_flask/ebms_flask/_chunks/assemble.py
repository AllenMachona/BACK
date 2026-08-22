from pathlib import Path

root = Path(r'c:\Users\User1\Documents\BACK\ebms_flask\ebms_flask')
parts = []
for i in range(1, 8):
    p = root / '_chunks' / f'c{i:02d}.txt'
    parts.append(p.read_text(encoding='utf-8').rstrip('\n'))

# Join with a blank line between chunks so no chunk boundary can merge lines.
target = root / 'app' / 'routes' / 'requests.py'
target.write_text('\n\n'.join(parts) + '\n', encoding='utf-8')
print('written lines:', len(('\n\n'.join(parts) + '\n').splitlines()))