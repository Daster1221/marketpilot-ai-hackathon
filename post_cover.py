"""Deterministic Russian cover typography over a FLUX scene (draft export)."""
from io import BytesIO
from pathlib import Path
import re
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
import app
import post_format
import premium_emoji

PETROL='#196C7F'


def add_logo(canvas,position=(46,34),size=(165,90)):
    """Logo and backplate temporarily disabled at the user's request."""
    return False


def font(size,bold=False):
    # Licensed brand fonts can be supplied privately; substitutes remain draft-only.
    names=['Intro Black.otf','IntroBlack.ttf'] if bold else ['Avenir Next Cyr.ttf','AvenirNextCyr-Regular.ttf']
    candidates=[app.ROOT/'data'/'brand_assets'/'fonts'/n for n in names]
    candidates += [Path('C:/Windows/Fonts/arialbd.ttf' if bold else 'C:/Windows/Fonts/arial.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    for p in candidates:
        if p.is_file():return ImageFont.truetype(str(p),size)
    raise ValueError('Для обложки нужен шрифт с поддержкой кириллицы. Установите Pillow и шрифты.')


def brief(topic,body):
    plain=premium_emoji.remove_emoji(post_format.plain(body))
    lines=[s.strip(' -•\t') for s in plain.splitlines() if s.strip()]
    title=lines[0] if lines else topic
    if len(title)>100:title=premium_emoji.remove_emoji(topic)
    # Every detail is a literal excerpt from the final post, not invented copy.
    address=re.search(r'(?im)^[ \t]*(?:адрес|где|место)[ \t]*:[ \t]*([^\n]{1,110})$',plain)
    if not address:address=re.search(r'(?im)^([^\n]*(?:улица|ул\.|проспект|Владивостокская)[^\n]{0,80})$',plain)
    dates=re.findall(r'\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)(?:\s+20\d{2}(?:\s+года)?)?(?:\s+в\s+\d{1,2}:\d{2})?',plain,re.I)
    facts=[]
    if address and len(address[1])<=110:facts.append(address[1].strip())
    if dates:
        date_text=dates[0]
        match=re.search(re.escape(date_text),plain)
        nearby=plain[max(0,match.start()-50):match.end()+60]
        facts.append(('Открытие: ' if re.search(r'открыл|открытие|начал\w* работу',nearby,re.I) else '')+date_text)
    hiring=bool(re.search(r'требуются|ищем|набор|ваканси|нужны работ|приглашаем.*(?:работ|команд)',plain,re.I))
    cta='ОСТАВЬТЕ ЗАЯВКУ НА САЙТЕ' if hiring and re.search(r'заявк',plain,re.I) else 'ПОДРОБНОСТИ В ПОСТЕ'
    return {'headline':title,'eyebrow':'ПРИГЛАШАЕМ В КОМАНДУ' if hiring else 'СОБЫТИЯ КОМПАНИИ','facts':facts[:2],'cta':cta}


def wrap(draw,text,f,width):
    words=text.split();lines=[];line=''
    for word in words:
        candidate=(line+' '+word).strip()
        if draw.textlength(candidate,font=f)>width and line:lines.append(line);line=word
        else:line=candidate
    if line:lines.append(line)
    return lines


def render(raw,topic,body,decision):
    source=Image.open(BytesIO(raw));source.load()
    scene=ImageOps.fit(source.convert('RGB'),(1080,1080),method=Image.Resampling.LANCZOS)
    canvas=scene.convert('RGBA')
    director=decision.get('director',{})
    if director.get('render_mode')=='generated_poster':
        # FLUX already designed all typography. Add only the existing logo asset.
        logo_used=add_logo(canvas)
        decision.update(cover={'texts':director.get('texts',[]),'render_mode':'generated_poster'},cover_rendered=True,project_logo_applied=logo_used,final_brand_compliance_verified=False)
        out=BytesIO();canvas.convert('RGB').save(out,format='PNG',optimize=True);return out.getvalue()
    mode=director.get('overlay','poster')
    if mode=='minimal':mode='headline'  # Legacy briefs must also show the post title.
    if mode in ('minimal','headline'):
        shade=Image.new('RGBA',canvas.size,(0,0,0,0));sd=ImageDraw.Draw(shade)
        for y in range(1080):
            alpha=int(150*max(0,1-y/340))
            if mode=='headline':alpha=max(alpha,int(200*max(0,(y-680)/400)))
            if alpha:sd.line((0,y,1080,y),fill=(6,29,34,alpha))
        canvas=Image.alpha_composite(canvas,shade);d=ImageDraw.Draw(canvas)
        logo_used=add_logo(canvas,(56,40))
        data=brief(topic,body)
        if mode=='headline':
            size=66
            while size>30:
                f=font(size,True);lines=wrap(d,data['headline'],f,960)
                if len(lines)*(size+7)<=180:break
                size-=2
            y=1000-len(lines)*(size+7)
            for line in lines:d.text((56,y),line,font=f,fill='white');y+=size+7
        decision.update(cover={'headline':data['headline'] if mode=='headline' else '', 'facts':[],'cta':'','overlay':mode},cover_rendered=True,project_logo_applied=logo_used,final_brand_compliance_verified=False)
        out=BytesIO();canvas.convert('RGB').save(out,format='PNG',optimize=True);return out.getvalue()
    dark=director.get('tone')=='dark' if director else decision.get('content_type') in ('sports','gaming')
    # A clean diagonal panel leaves the scene visible on the right and below.
    panel=Image.new('RGBA',canvas.size,(0,0,0,0));d=ImageDraw.Draw(panel)
    d.polygon([(0,0),(785,0),(650,740),(0,915)],fill=(12,62,73,244) if dark else (248,251,251,248))
    canvas=Image.alpha_composite(canvas,panel)
    d=ImageDraw.Draw(canvas)
    # Reuse the existing project asset unchanged; never synthesize a company mark.
    logo_used=add_logo(canvas,(62,42),(170,90))
    data=brief(topic,body)
    d.text((64,161),data['eyebrow'],font=font(22,True),fill='#DDE1E1' if dark else PETROL)
    size=88
    while size>=46:
        heading_font=font(size,True);lines=wrap(d,data['headline'].upper(),heading_font,600)
        if len(lines)*(size+7)<=430 and all(d.textlength(line,font=heading_font)<=600 for line in lines):break
        size-=2
    y=207
    for line in lines:
        d.text((60,y),line,font=heading_font,fill='white' if dark else '#103E49',stroke_width=0);y+=size+7
    d.rectangle((64,min(y+24,665),190,min(y+30,671)),fill='#DDE1E1' if dark else PETROL)
    facts=data['facts']
    if facts:
        rows=[]
        for fact in facts:rows.extend(wrap(d,fact,font(30,True),620))
        height=min(182,36+len(rows)*39)
        d.rounded_rectangle((56,765-height,745,775),radius=18,fill=(255,255,255,239))
        fy=786-height
        for line in rows[:4]:d.text((80,fy),line,font=font(30,True),fill='#103E49');fy+=39
    d.polygon([(0,928),(1080,884),(1080,1080),(0,1080)],fill=PETROL)
    d.text((64,960),data['cta'],font=font(31,True),fill='white')
    out=BytesIO();canvas.convert('RGB').save(out,format='PNG',optimize=True)
    decision.update(cover=data,cover_rendered=True,project_logo_applied=logo_used,final_brand_compliance_verified=False)
    return out.getvalue()
