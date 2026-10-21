"""Daily wood price snapshot; never replace a good snapshot with invalid input."""
import json,time,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from wood_parser import SOURCE_URL,parse_pdf

folder=Path('prices');folder.mkdir(exist_ok=True)
checked=datetime.now(timezone.utc).isoformat()
try:
    data=None
    for attempt in range(3):
        try:
            req=urllib.request.Request(SOURCE_URL,headers={'User-Agent':'Mozilla/5.0','Accept':'application/pdf','Cache-Control':'no-cache'})
            with urllib.request.urlopen(req,timeout=45) as response:data=response.read(30*1024*1024+1)
            break
        except Exception:
            if attempt==2:raise
            time.sleep(3)
    result=parse_pdf(data,checked)
    old=folder/'wood.json'
    if old.exists():
        previous=json.loads(old.read_text())
        if len(result['items'])<len(previous['items'])*.65:
            raise ValueError('Too many wood price rows disappeared; manual review needed')
        if previous.get('supplierDate') and result.get('supplierDate'):
            before=datetime.strptime(previous['supplierDate'],'%d.%m.%Y')
            after=datetime.strptime(result['supplierDate'],'%d.%m.%Y')
            if after<before:raise ValueError('Supplier document date went backwards')
    (folder/'wood.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
    status={'success':True,'attemptedAt':checked,'sourceUrl':SOURCE_URL,'materialCount':len(result['items']),'supplierDate':result['supplierDate']}
    print('52les price verified:',len(result['items']),'items; document',result['supplierDate'])
except Exception as error:
    print(type(error).__name__+': '+str(error))
    status={'success':False,'attemptedAt':checked,'sourceUrl':SOURCE_URL,'error':'Не удалось получить или проверить прайс 52ЛЕС. Сохранена последняя успешная версия.'}
(folder/'wood-status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
