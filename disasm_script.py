import dis
import marshal

with open('GPI.exe_extracted/app.pyc', 'rb') as f:
    f.read(16) # Skip the 16-byte magic and timestamp header in Python 3.12
    code = marshal.load(f)

with open('app_dis.txt', 'w', encoding='utf-8') as f:
    dis.dis(code, file=f)
    print("Disassembly complete", file=f)
