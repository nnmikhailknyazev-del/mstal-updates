"""Parse 52les supplier PDF into a checked, searchable snapshot."""
from __future__ import annotations
import hashlib,io,re
from datetime import datetime,timezone
from decimal import Decimal
from pypdf import PdfReader
import pdfplumber

SOURCE_URL='https://www.52les.ru/images/price/price-list.pdf'
CATALOG_URL='https://www.52les.ru/'
SPECIES=['Бук','Ясень','Дуб','Сосна','Лиственница','Берёза']
PRICE=re.compile(r'^(?:\d{1,3}(?:[ .]\d{3})+|\d+(?:[.,]\d+)?|[-–—])$')

def normalize(s): return re.sub(r'\s+',' ',s.replace('\u00a0',' ')).strip()
def species_in(s):
    for sp in SPECIES:
        if re.search(r'(?<![А-Яа-яЁё])'+sp+r'(?![А-Яа-яЁё])',s,re.I): return sp
    return None

def extract_lines(data):
    lines=[]
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if not 1<=len(pdf.pages)<=40: raise ValueError('Unexpected page count')
        for page_no,page in enumerate(pdf.pages,1):
            words=page.extract_words(x_tolerance=2,y_tolerance=3,keep_blank_chars=False)
            rows=[]
            for word in sorted(words,key=lambda w:(w['top'],w['x0'])):
                if not rows or abs(rows[-1][0]-word['top'])>2.4: rows.append((word['top'],[]))
                rows[-1][1].append(word)
            for top,ws in rows:
                ws.sort(key=lambda w:w['x0'])
                lines.append((page_no,normalize(' '.join(w['text'] for w in ws)),ws))
    return lines

def parse_pdf(data:bytes,checked_at=None):
    if not data.startswith(b'%PDF-') or len(data)>30*1024*1024: raise ValueError('Not a supported PDF')
    reader=PdfReader(io.BytesIO(data));lines=extract_lines(data)
    items=[];species=None;section='Материалы';column_centers=[];table_active=False
    for page_no,line,words in lines:
        low=line.casefold()
        if 'наименование' in low and all(sp.casefold() in low for sp in ['бук','ясень','дуб','сосна']):
            header=[w for w in words if w['text'].casefold() in ('бук','ясень','дуб','сосна')]
            column_centers=[(w['x0']+w['x1'])/2 for w in header];table_active=True;continue
        if 'наименование' in low and len(re.findall(r'цена\s*/\s*шт',low))>=2:
            table_active=True;continue
        if low.startswith(('компания ','ул. ','52les.ru','розничная цена','спеццена - предоставляется','работающим с древесиной','лестницы/интерьеры','страница ')) or low in ('спеццена','цена/шт','цена / шт','цена/ шт','цена /шт'):
            continue
        # Species / product group headings. Supplier captions often end in "цена/шт".
        sp=species_in(line)
        has_price_token=any(PRICE.fullmatch(w['text'].replace('\u00a0','')) for w in words)
        heading=bool(re.search(r'цена\s*/\s*шт|цена\s*/\s*шт|цена\s*/шт|цена/\s*шт|цена\s*/\s*шт',low))
        group_prefix=re.match(r'^(щит мебельный|ступени|ступень|ограждение|балясины|поручни|поручень|столбы|столб|декоративные решетки|мдф|рейка|уголок)\b',low)
        if sp and (heading or not has_price_token): species=sp
        if group_prefix and ('цена' in low or (re.search(r'\b\d+\s*мм\b',low) and not re.search(r'\d\s*[xх×*]\s*\d',low))):
            section=line
            continue
        if not has_price_token:
            if len(line)>3 and re.search(r'[А-Яа-яЁё]',line) and not low.startswith(('розничная','спеццена','наименование','цена/','цена /')):
                if group_prefix: section=line
            continue
        # Page 19 has species columns. Map by actual text position so blanks are not misassigned.
        if table_active and column_centers and page_no==19:
            data_words=[]
            for w in words:
                if PRICE.fullmatch(w['text'].replace('\u00a0','')):
                    center=(w['x0']+w['x1'])/2
                    if center>220:data_words.append((center,w['text']))
            name=normalize(' '.join(w['text'] for w in words if (w['x0']+w['x1'])/2<220))
            if not name or not data_words: continue
            for x,p in data_words:
                if p in ('-','–','—'): continue
                col=min(range(len(column_centers)),key=lambda i:abs(column_centers[i]-x))
                sp=SPECIES[col]
                add_item(items,name,section,sp,p,page_no)
            continue
        # Ordinary one-price rows; price is the rightmost numeric token on the row.
        price_word=None
        for w in reversed(words):
            if PRICE.fullmatch(w['text'].replace('\u00a0','')):
                price_word=w;break
        if not price_word: continue
        price=price_word['text']; center=(price_word['x0']+price_word['x1'])/2
        name=normalize(' '.join(w['text'] for w in words if w is not price_word))
        if not name or not re.search(r'[А-Яа-яЁёA-Za-z]',name): continue
        # Headings ending in a size are not product rows unless they include an actual price in a separate price column.
        if low.startswith(('розничная цена','спеццена','наименование')): continue
        sp=species_in(name) or species
        add_item(items,name,section,sp,price,page_no)
    if len(items)<100: raise ValueError(f'Unexpected material count: {len(items)}')
    if len({x['category'] for x in items})<7: raise ValueError('Too few categories recognized')
    mod=(reader.metadata or {}).get('/ModDate','');supplier_date=None
    if re.match(r'^D:\d{8}',str(mod)):
        try:supplier_date=datetime.strptime(str(mod)[2:10],'%Y%m%d').strftime('%d.%m.%Y')
        except ValueError:pass
    return {'schemaVersion':1,'supplier':'52ЛЕС / Большая Медведица','sourceUrl':SOURCE_URL,'catalogUrl':CATALOG_URL,'supplierDate':supplier_date,'checkedAt':checked_at or datetime.now(timezone.utc).isoformat(),'sourceSha256':hashlib.sha256(data).hexdigest(),'currency':'RUB','availabilityProvided':False,'priceNote':'Спеццена. Розничная цена — +10% к спеццене; частным лицам спеццену предлагают уточнять у менеджера.','items':items}

def add_item(items,name,section,species,price,page):
    if price in ('-','–','—'): return
    clean=price.replace(' ','').replace(',','.')
    if not re.fullmatch(r'\d+(?:\.\d+)?',clean): raise ValueError('Invalid price: '+price)
    amount=Decimal(clean)
    if amount<=0 or amount>Decimal('100000000'): raise ValueError('Price out of range')
    unit='пог. м' if re.search(r'п\.?\s*м\.?|пог\.?\s*м',name,re.I) else 'шт.'
    full_name=name
    if species and not species_in(full_name): full_name=f'{full_name} · {species}'
    category=category_for(full_name,section)
    items.append({'name':full_name,'category':category,'species':species or '','priceSpecial':str(amount),'priceRetail':str((amount*Decimal('1.10')).quantize(Decimal('0.01'))),'unit':unit,'sourcePage':page})

def category_for(name,section):
    n=name.casefold()
    if 'мдф' in n or 'кромка' in n:return 'МДФ и кромка'
    if 'щит' in n:return 'Щиты мебельные'
    if 'ступен' in n:return 'Ступени'
    if 'поручен' in n or 'пфп' in n:return 'Поручни и поворотные элементы'
    if 'балясин' in n:return 'Балясины'
    if 'столб' in n or 'стоб ' in n:return 'Столбы'
    if any(x in n for x in ('заглушк','рейка','уголок','экран')):return 'Погонаж и комплектующие'
    return section

if __name__=='__main__':
 import json,sys
 from pathlib import Path
 result=parse_pdf(Path(sys.argv[1]).read_bytes())
 Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print('Parsed',len(result['items']),'prices in',len({x['category'] for x in result['items']}),'categories; date',result['supplierDate'])
