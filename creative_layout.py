"""Validate the director's geometry and typography before paying the image API."""
import re
from PIL import Image,ImageDraw
import post_cover

COLORS={'#196C7F','#C1D0D3','#DDE1E1','#FFFFFF','#103E49'}

def intersects(a,b):
    return a[0]<b[0]+b[2] and b[0]<a[0]+a[2] and a[1]<b[1]+b[3] and b[1]<a[1]+a[3]

def box(value):
    if not isinstance(value,list) or len(value)!=4 or any(type(n)!=int for n in value):raise ValueError('Некорректные координаты макета.')
    x,y,w,h=value
    if min(x,y)<40 or min(w,h)<40 or x+w>1040 or y+h>1040:raise ValueError('Элемент обложки выходит за безопасные поля.')
    return value

def validate(plan,source):
    concepts=plan.get('concepts');selected=plan.get('selected')
    if not isinstance(concepts,list) or len(concepts)!=3 or any(not isinstance(c,str) or not 5<=len(c)<=260 for c in concepts) or type(selected)!=int or not 0<=selected<3:
        raise ValueError('Арт-директор не выбрал одну из трёх концепций.')
    if len({c.casefold().strip() for c in concepts})!=3:raise ValueError('Визуальные концепции повторяются.')
    hero=box(plan.get('hero_box'));blocks=plan.get('blocks')
    if not isinstance(blocks,list) or not 1<=len(blocks)<=4:raise ValueError('Не задан план надписей.')
    if plan.get('background') not in COLORS:raise ValueError('Не задан фирменный фон.')
    draw=ImageDraw.Draw(Image.new('RGB',(10,10)))
    used=[];roles=[]
    for b in blocks:
        role=b.get('role');text=b.get('text');rect=box(b.get('box'))
        if role not in ('headline','detail','cta') or not isinstance(text,str) or not 1<=len(text.strip())<=100:raise ValueError('Некорректная надпись в макете.')
        if b.get('color') not in COLORS or b.get('panel') not in COLORS|{'none'}:raise ValueError('Некорректный цвет надписи.')
        if b['color']==b['panel'] or (b['panel']=='none' and b['color']==plan['background']):raise ValueError('Надпись сливается с фоном.')
        if intersects(rect,hero) or any(intersects(rect,r) for r in used):raise ValueError('Блоки обложки перекрывают друг друга.')
        if any(n not in re.findall(r'\d+',source) for n in re.findall(r'\d+',text)):raise ValueError('В надписях появились неподтверждённые числа.')
        # The most damaging observed brand typo must not reach publication.
        if re.search(r'салават',text,re.I) and re.search(r'салават',source,re.I):
            for word in re.findall(r'салават[а-яё]*',text,re.I):
                if word.casefold() not in ('салаватстекло','салаватстекла'):raise ValueError('Проверьте написание САЛАВАТСТЕКЛО в надписи.')
        size=b.get('size',72 if role=='headline' else 34)
        if type(size)!=int or not 26<=size<=100:raise ValueError('Некорректный размер шрифта.')
        minimum=44 if role=='headline' else 28
        while size>=minimum:
            f=post_cover.font(size,True);lines=post_cover.wrap(draw,text,f,rect[2]-32)
            if len(lines)*(size+8)<=rect[3]-24 and all(draw.textlength(line,font=f)<=rect[2]-32 for line in lines):break
            size-=2
        if size<minimum:raise ValueError('Текст слишком длинный для выбранного блока. Обложка не сгенерирована.')
        b.update(size=size,lines=lines);used.append(rect);roles.append(role)
    if roles.count('headline')!=1:raise ValueError('На обложке нужен один главный заголовок.')
    plan['concept']=concepts[selected]
    plan['texts']=[b['text'] for b in blocks]
    plan['preflight']={'geometry':'passed','text_fit':'passed','facts':'numbers_checked','logo':'disabled','pixel_quality':'human_review_required'}
    return plan

def render(raw,plan):
    from io import BytesIO
    from PIL import ImageOps
    image=Image.open(BytesIO(raw));image.load()
    canvas=Image.new('RGB',(1080,1080),plan['background'])
    x,y,w,h=plan['hero_box'];canvas.paste(ImageOps.fit(image.convert('RGB'),(w,h),method=Image.Resampling.LANCZOS),(x,y))
    d=ImageDraw.Draw(canvas)
    for block in plan['blocks']:
        x,y,w,h=block['box']
        if block['panel']!='none':d.rounded_rectangle((x,y,x+w,y+h),radius=10,fill=block['panel'])
        f=post_cover.font(block['size'],True)
        top=y+(h-len(block['lines'])*(block['size']+8))//2
        for line in block['lines']:
            d.text((x+16,top),line,font=f,fill=block['color']);top+=block['size']+8
    out=BytesIO();canvas.save(out,format='PNG',optimize=True);return out.getvalue()
