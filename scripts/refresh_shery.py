"""Daily supplier snapshot. Keep the previous good price if source/format fails."""
import json,sys,time,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from shery_parser import SOURCE_URL,parse_pdf

folder=Path('prices');folder.mkdir(exist_ok=True)
checked=datetime.now(timezone.utc).isoformat()
try:
    data=None
    for attempt in range(3):
        try:
            req=urllib.request.Request(SOURCE_URL,headers={'User-Agent':'Mozilla/5.0','Accept':'application/pdf','Cache-Control':'no-cache'})
            with urllib.request.urlopen(req,timeout=40) as response:data=response.read(30*1024*1024+1)
            break
        except Exception:
            if attempt==2:raise
            time.sleep(3)
    result=parse_pdf(data,checked)
    old=folder/'shery.json'
    if old.exists():
        previous=json.loads(old.read_text())
        if len(result['items'])<len(previous['items'])*.65:raise ValueError('Too many supplier rows disappeared; manual review needed')
        if previous.get('supplierDate') and result.get('supplierDate'):
            if datetime.strptime(result['supplierDate'],'%d.%m.%Y')<datetime.strptime(previous['supplierDate'],'%d.%m.%Y'):
                raise ValueError('Supplier document date went backwards')
    encoded=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    (folder/'shery-source.pdf').write_bytes(data)
    (folder/'shery.json').write_text(encoded)
    status={'success':True,'attemptedAt':checked,'sourceUrl':SOURCE_URL,'materialCount':len(result['items'])}
    print('Supplier price verified:',len(result['items']),'materials; document',result['supplierDate'])
except Exception as error:
    print(type(error).__name__+': '+str(error))
    status={'success':False,'attemptedAt':checked,'sourceUrl':SOURCE_URL,'error':'Не удалось получить или проверить прайс поставщика. Сохранена последняя успешная версия.'}
(folder/'shery-status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
