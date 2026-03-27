from pathlib import Path
p=Path('app/data/runtime/rag/_tmp_write_test.txt')
p.write_text('ok',encoding='utf-8')
print('done')
