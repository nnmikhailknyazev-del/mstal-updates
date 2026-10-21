"""Extract visible Shery spreadsheet rows; respect clipped-out hidden spreadsheet rows."""
from __future__ import annotations
import hashlib,io,re
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pypdf import PdfReader

SOURCE_URL='https://shery.ru/upload/medialibrary/b7b/76qni8a3gvvw4pfrq5h1pys4twuc4we4.pdf'
CATALOG_URL='https://shery.ru/catalog/'
BOUNDS=[0,118.73,170.01,201.83,237.89,277.48,357.02-31.46,357.02,375.05,415.01,448.59,483.7,596]
KEYS=['name','gost','weightPerMeter','length','weightPerPiece','pricePerMeter','pricePerPiece','cutPrice','pricePerTon','priceFromHalfTon','priceFromOneTon','extra']
NUMERIC={'pricePerMeter','pricePerPiece','cutPrice','pricePerTon','priceFromHalfTon','priceFromOneTon','weightPerMeter','weightPerPiece'}

def number(value):
    s=value.strip().replace('\u00a0','').replace(' ','').replace(',','.')
    if not s:return ''
    if not re.fullmatch(r'\d+(?:\.\d+)?',s):raise ValueError('Unexpected numeric cell: '+repr(value))
    v=Decimal(s)
    if not v.is_finite() or v<0 or v>Decimal('100000000'):raise ValueError('Numeric cell out of range')
    return str(v)

def visible_runs(page):
    stack=[];clip=None;pending=None;runs=[]
    def point(x,y,cm):return (cm[0]*x+cm[2]*y+cm[4],cm[1]*x+cm[3]*y+cm[5])
    def before(op,args,cm,tm):
        nonlocal clip,pending
        if op==b'q':stack.append(clip)
        elif op==b'Q':clip=stack.pop() if stack else None
        elif op==b're':
            x,y,w,h=map(float,args);pts=[point(x,y,cm),point(x+w,y+h,cm)]
            pending=(min(p[0] for p in pts),min(p[1] for p in pts),max(p[0] for p in pts),max(p[1] for p in pts))
        elif op in (b'W',b'W*') and pending:
            clip=pending if clip is None else (max(clip[0],pending[0]),max(clip[1],pending[1]),min(clip[2],pending[2]),min(clip[3],pending[3]))
        elif op in (b'n',b'f',b'f*',b'S',b's'):pending=None
    def text(value,cm,tm,font,size):
        value=' '.join(value.split())
        if not value:return
        x,y=point(tm[4],tm[5],cm)
        if clip and not (clip[0]-1.0<=x<=clip[2]+.5 and clip[1]-.05<=y<=clip[3]+.05):return
        runs.append({'x':float(x),'y':float(y),'text':value,'size':float(size)})
    page.extract_text(visitor_operand_before=before,visitor_text=text)
    return runs

def group_name(text):
    t=text.lower().replace('ё','е')
    if t.startswith('труба вгп') and 'гост' in t:return 'Труба ВГП'
    if 'электросварная' in t:return 'Труба электросварная'
    if t.startswith('труба оцинкованная'):return 'Труба оцинкованная'
    if t.strip() in ('труба б\\ш','труба б/ш'):return 'Труба бесшовная'
    if t.startswith('труба профильная'):return 'Труба профильная'
    if t.startswith('балка ('):return 'Балка'
    if t.strip()=='швеллер':return 'Швеллер'
    if t.strip()=='уголок':return 'Уголок'
    return None

def parse_pdf(data:bytes,checked_at=None):
    if not data.startswith(b'%PDF-') or len(data)>30*1024*1024:raise ValueError('Not a supported PDF')
    reader=PdfReader(io.BytesIO(data));items=[];category=None;dates=[]
    if not 1<=len(reader.pages)<=20:raise ValueError('Unexpected page count')
    for page_number,page in enumerate(reader.pages,1):
        if abs(float(page.mediabox.width)-595.3)>3:raise ValueError('Supplier layout changed: page width')
        runs=visible_runs(page)
        all_text=' '.join(r['text'] for r in runs)
        if page_number==1 and not ('Наименование' in all_text and 'цена' in all_text.lower()):raise ValueError('Price header not recognised')
        dates.extend(re.findall(r'\b\d{2}\.\d{2}\.\d{4}\b',all_text))
        lines=[]
        for run in sorted(runs,key=lambda r:(-r['y'],r['x'])):
            if not lines or abs(lines[-1][0]-run['y'])>.8:lines.append((run['y'],[]))
            lines[-1][1].append(run)
        for baseline,line in lines:
            full=' '.join(r['text'] for r in sorted(line,key=lambda r:r['x']))
            group=group_name(full)
            if group:category=group;continue
            cells=['']*len(KEYS)
            for run in line:
                for i in range(len(KEYS)):
                    if BOUNDS[i]<=run['x']+.25<BOUNDS[i+1]:
                        cells[i]=(cells[i]+' '+run['text']).strip();break
            name=cells[0]
            if not name or not re.match(r'(?i)^(труб|балк|швеллер|угол)',name) or not re.search(r'\d',name):continue
            if not category:raise ValueError('Material row without group: '+name)
            record=dict(zip(KEYS,cells));record.pop('extra',None)
            for key in NUMERIC:record[key]=number(record[key])
            if not (record['pricePerMeter'] or record['pricePerPiece']):raise ValueError('Material has no retail price: '+name)
            record.update(category=category,sourcePage=page_number,availability='not_provided')
            identity='|'.join(record[k] for k in ('category','name','gost','length'))
            record['id']=hashlib.sha256(identity.encode()).hexdigest()[:20]
            items.append(record)
    if len(items)<30 or len(items)>3000:raise ValueError('Unexpected material count')
    if len({r['category'] for r in items})<5:raise ValueError('Too few material groups')
    if len({r['id'] for r in items})!=len(items):raise ValueError('Duplicate material identities')
    supplier_date=dates[0] if dates else None
    if supplier_date:datetime.strptime(supplier_date,'%d.%m.%Y')
    return {'schemaVersion':1,'supplier':'Шери','sourceUrl':SOURCE_URL,'catalogUrl':CATALOG_URL,
        'supplierDate':supplier_date,'checkedAt':checked_at or datetime.now(timezone.utc).isoformat(),
        'sourceSha256':hashlib.sha256(data).hexdigest(),'currency':'RUB','availabilityProvided':False,
        'retailCondition':'до 1 тонны','items':items}

if __name__=='__main__':
    import json,sys
    from pathlib import Path
    result=parse_pdf(Path(sys.argv[1]).read_bytes())
    Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('Parsed',len(result['items']),'visible materials in',len({x['category'] for x in result['items']}),'groups')
