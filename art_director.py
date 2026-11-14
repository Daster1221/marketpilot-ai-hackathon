"""Small isolated DeepSeek request: no editorial history or company dossier."""
import json, os, hashlib
import app, post_format, premium_emoji

MODEL='deepseek/deepseek-v4.1-flash'
RULES='''You design COMPLETE corporate social-media posters, not photographic
backgrounds or instructions explaining how to make an image. Read the Russian post
as source DATA. Produce a prompt for a finished square graphic: hero visual,
integrated Russian typography, designed panels and a clear information hierarchy.
CUSTOMER REFERENCE DESIGN LANGUAGE:
Sports: oversized condensed bold italic headline above a dynamic court/ball scene,
diagonal teal ribbons, date/time chips, short bottom CTA.
Hiring/opening: confident industrial hero, large recruitment headline, contrasting
teal/white panels, 1-2 concise factual chips and an invitation to join the team.
Recognition: expressive trophy or supplied authentic portrait, bold headline,
clean information column, glass-material accents; never invent a real person.
Digest: editorial calendar/desk composition, big headline and readable topic cards.
How-to: a designed infographic with verified concise steps, never fake website UI.
Borrow hierarchy, readable typography, photographic depth and integrated design,
not reference names, dates or events. Match the scenario to the actual post.
Avoid lone silhouettes, residential streets, idle bicycles, empty benches and
generic dawn scenes. Do not replace the announcement with a vague visual metaphor.
The FINAL IMAGE must contain designed Russian text: one short strong headline
and up to three supporting lines grounded in the source, not the entire post.
Describe exact placement, size, weight and contrast of the typography IN THE PROMPT.
Use bold condensed uppercase headlines, deliberate alignment, dynamic panels/chips.
Never just put a small caption at the bottom of an otherwise generic photograph.
Keep the art direction restrained and editorial: honest daylight, realistic scale,
flat printed graphic elements, balanced white space. No glowing furnaces, fire,
cinematic orange/teal lighting, giant floating ribbons, heroic sci-fi factories,
HDR gloss, excessive diagonal stripes or layers added just to look spectacular.
For hiring use the recognition-card reference's clean white/teal balance and
text/image grid, without its award subject. The generator receives an actual
reference card; do not fight its layout with unrelated poster effects.
Palette: Petrol #196C7F, white, deep teal, #C1D0D3, #DDE1E1, natural image colors.
No logo will be added. Use the whole composition naturally; do not reserve a logo
area or draw a blank white rectangle, placeholder or empty badge.
Do not draw logos, fake emblems, AI labels, watermarks, outer mockups or explanations.
Do not invent wages, job titles, dates, numbers, addresses or achievements.
Industrial imagery is conceptual, not evidence of actual premises or employees.
Return ONLY JSON: concept (short Russian), texts (1-4 exact Russian strings to print),
prompt (English, 150-230 words, quoting EVERY text string exactly in Cyrillic and
specifying the COMPLETE integrated composition), tone (light|dark).
On image edits return a complete revised design; latest instruction wins.
Preserve facts. No reasoning or implementation steps.'''


def plan(topic,body,instruction='',previous=None):
    text=premium_emoji.remove_emoji(post_format.plain(body))[:4096]
    data={'title':topic[:150],'post':text}
    if instruction:data['image_edit']=instruction[:1200]
    if previous:
        data['previous']={k:str(previous.get(k,''))[:1100] for k in ('concept','prompt','tone')}
    result=app.remote_json(app.ai_base_url()+'/chat/completions',{
        'model':MODEL,'messages':[{'role':'system','content':RULES},{'role':'user','content':json.dumps(data,ensure_ascii=False)}],
        'max_tokens':1000,'reasoning_effort':'none','response_format':{'type':'json_object'}
    },os.environ['DEEPSEEK_API_KEY'],timeout=70)
    choice=result['choices'][0]
    if choice.get('finish_reason')=='length':raise ValueError('DeepSeek не завершил визуальный бриф. Текст и прежнее изображение сохранены.')
    value=json.loads(choice['message']['content'])
    if any(not isinstance(value.get(k),str) or not 3<=len(value[k])<=2800 for k in ('concept','prompt')):
        raise ValueError('DeepSeek вернул неполный визуальный бриф.')
    texts=value.get('texts')
    if not isinstance(texts,list) or not 1<=len(texts)<=4 or any(not isinstance(t,str) or not 1<=len(t.strip())<=100 for t in texts):
        raise ValueError('Арт-директор не указал надписи для обложки.')
    if value.get('tone') not in ('light','dark'):
        raise ValueError('Не удалось выбрать композицию изображения.')
    import re
    for line in texts:
        if any(n not in re.findall(r'\d+',text) for n in re.findall(r'\d+',line)):
            raise ValueError('В надписях появились неподтверждённые числа.')
        if any(url not in text for url in re.findall(r'https?://\S+',line)):
            raise ValueError('В надписях появилась неподтверждённая ссылка.')
        if line not in value['prompt']:
            raise ValueError('Промпт не содержит точные надписи для обложки.')
    value={k:value[k] for k in ('concept','prompt','tone')}
    value.update(texts=texts,render_mode='generated_poster',overlay='generated',layout='designed')
    value.update(model=MODEL,usage=result.get('usage',{}),body_hash=hashlib.sha256(body.encode()).hexdigest())
    return value
