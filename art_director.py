"""Small isolated DeepSeek request: no editorial history or company dossier."""
import json, os, hashlib
import app, post_format, premium_emoji

MODEL='deepseek/deepseek-v4.1-flash'
RULES='''Create a concise art brief for ONE finished Russian social-media advertisement.
The image model sees a real design reference. Your job is editorial selection, not
pixel coordinates. Understand what the post invites people to do, choose a relevant
visual story and select ONLY useful short copy. Design the entire poster together:
photography, expressive large Cyrillic typography, brush strokes, handwritten accents,
teal/white foundation and selective yellow accents. Match the supplied reference's
visual richness. Avoid a generic stock photo with a bottom caption, empty teal cards,
lonely silhouettes, excessive gradients and decorative glass on unrelated topics.
Sports: dynamic sports campaign, close foreground equipment, layered arena action,
large condensed headline and readable date/venue chips. Recognition: crafted glass
award/editorial still life and bold asymmetric type. Digest: lively real desktop,
calendar and useful short content cards. City/culture: editorial collage and lettering.
Use a scene as a visual illustration, not evidence of actual people or event photos.
No logos or brand monograms, no AI label, no watermark, no fake employee faces.
Do not invent dates, times, names, locations, benefits or a call to unavailable media.
Retain only source-confirmed facts. Do not copy facts or text from the reference.
Return JSON: concept (short Russian description), reference (sports|football|digest|
city|recognition), prompt (English complete-poster art brief 100-180 words), texts
(array of 1-5 exact Russian strings to print, headline and optional useful factual
lines/CTA). All typography is generated inside the artwork, no external overlay.
Keep names exactly, especially Салаватстекло. Avoid repeating the entire post.
On edits obey the latest instruction and preserve applicable source facts.'''



def plan(topic,body,instruction='',previous=None):
    text=premium_emoji.remove_emoji(post_format.plain(body))[:4096]
    data={'title':topic[:150],'post':text}
    if instruction:data['image_edit']=instruction[:1200]
    if previous:
        data['previous']={k:str(previous.get(k,''))[:1100] for k in ('concept','prompt','tone')}
    result=app.remote_json(app.ai_base_url()+'/chat/completions',{
        'model':MODEL,'messages':[{'role':'system','content':RULES},{'role':'user','content':json.dumps(data,ensure_ascii=False)}],
        'max_tokens':1500,'reasoning_effort':'none','response_format':{'type':'json_object'}
    },os.environ['DEEPSEEK_API_KEY'],timeout=70)
    choice=result['choices'][0]
    if choice.get('finish_reason')=='length':raise ValueError('DeepSeek не завершил визуальный бриф. Текст и прежнее изображение сохранены.')
    value=json.loads(choice['message']['content'])
    if not isinstance(value.get('prompt'),str) or not 30<=len(value['prompt'])<=2000:
        raise ValueError('Арт-директор не завершил описание сцены.')
    texts=value.get('texts')
    if not isinstance(texts,list) or not 1<=len(texts)<=5 or any(not isinstance(t,str) or not t.strip() or len(t)>140 for t in texts):
        raise ValueError('Арт-директор не подготовил короткие надписи.')
    import re
    source_numbers=set(re.findall(r'\d+',text))
    if set(re.findall(r'\d+',' '.join(texts)))-source_numbers:
        raise ValueError('В надписях появились неподтверждённые числа.')
    if value.get('reference') not in ('sports','football','digest','city','recognition'):
        value['reference']='recognition'
    value.update(render_mode='generated_poster',overlay='none',layout='image_native')
    value.update(model=MODEL,usage=result.get('usage',{}),body_hash=hashlib.sha256(body.encode()).hexdigest())
    return value
