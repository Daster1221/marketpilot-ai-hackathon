"""Reviewed visual policy, derived from the supplied project regulation v2.0.

This is a draft policy based on the customer's PDF, not proof that the original
2023 brandbook, original logo, licensed fonts or exceptions were supplied.
"""
import re
import post_format

SOURCE = 'salavatsteklo_visual_reglament_v2_0.pdf'
VERSION = '2.0 / 2026-11-14 / project'
SOURCE_SHA256 = '3101e0ff27312565b57406de4a7c4fb03a034b2f014d080524049dc1798a5bd9'
PALETTE = ('#196C7F', '#C1D0D3', '#DDE1E1')
RULES = '''CUSTOMER VISUAL POLICY, version 2.0 (project), based on brandbook 2023.
Treat reference examples as composition guidance, not facts or permission to
override the brandbook. Aim for authentic, professional, realistic photography,
natural skin/material color, clear subject and an interesting camera angle.
Brand graphic colors ONLY: Petrol #196C7F, light gray #C1D0D3 and #DDE1E1,
plus white. Do not recolor natural subjects or photographs into brand colors.
Do not use yellow/orange brush strokes, handwriting, random glass shards,
unapproved icons, colored gradients or a repeated logo pattern. Do not guess
the unresolved Pantone 2216 C HEX/RGB conflict or extra-color approvals.
Work as BACKGROUND LAYER ONLY. No words, numbers, dates, logos, emblems, brands,
fake UI, QR codes, watermarks or invented typefaces. Keep clean negative space
at upper left for a later genuine logo and separate headline, without drawing
either. Official heading font is Intro Black, body font Avenir Next Cyr; these
belong in a separate licensed renderer, never in the generated background.
Do not substitute Segoe or a lookalike logo and do not imply final brand approval.
Keep people, documentary photos and safety equipment intact when supplied;
do not fabricate portraits, employees, identifiable company facilities, match
results or documentary evidence of a past event. A generated image is conceptual.
Glass must have physically credible transparency and reflections: no lens-like
warping, dirt, drips or invented product/coating properties. No unsafe production.
Keep a clean mobile-readable hierarchy: subject, surrounding context, quiet space.
Use the selected composition to vary the visual by topic, not the same backdrop
for every publication. Photo subjects retain believable natural colors.
Square composition, preserve proportions. This file is an illustration draft,
not a fully typeset advertising layout or an approved publication.'''

# References were visually checked on PDF p.1; analysis on pp.5-6, layouts pp.8-9.
SCENARIOS = (
    ('factory_hiring', r'нов\w* завод|откры\w*.*завод|завод.*откры',
     'EVENT_CARD', ('IMG_4758','IMG_4759'),
     'An ambitious industrial-opening and recruitment cover background. A striking glass-manufacturing material detail in the foreground, with depth, natural daylight and a generic modern industrial setting on the right. Do not pretend this is a photograph of the actual new factory; no imaginary staff, signage or machinery claims. Keep the upper-left and center-left quiet for a bold editorial headline, location card and recruitment CTA added by the renderer.'),
    ('portrait', r'истори[яи]\s+(?:нашего\s+)?сотрудника|куратор|интервью|доск\w* поч[её]та|ветеран',
     'PORTRAIT_PROFILE', ('IMG_4761','IMG_4759'),
     'Recognition and personal story. Use a neutral symbolic still life if no genuine portrait is supplied; NEVER invent a person, name badge or award won. Keep one large hero area and a quiet side area for later verified facts.'),
    ('sports', r'футбол|волейбол|баскетбол|турнир|полуфинал|матч',
     'EVENT_CARD', ('IMG_4757','IMG_4760'),
     'A close, believable sports-equipment detail in a relevant playing environment, energetic camera angle, clear foreground/background separation. For a past match use symbolic equipment only, never fabricate the teams or action from that match. Leave structured quiet space; no drawn schedule, scoreboard or emblems.'),
    ('digest', r'дайджест|недел\w*|контент.план',
     'DIGEST_GRID', ('IMG_4756',),
     'Calm editorial desk/calendar atmosphere and clear modular rhythm; one focal object, restrained supporting details. Empty layout space only: no invented dates, handwritten notes, notification widgets or tiny pseudo-text.'),
    ('instruction', r'инструкц|голосован|пошаг|заявк|рейтинг работодател',
     'STEP_BY_STEP', ('IMG_4762',),
     'Minimal calm visual supporting a practical action. A real interface or step sequence must be supplied and typeset separately; never draw fake screens, links, buttons, numbers or QR codes.'),
    ('gaming', r'кибер|гейм|игров\w* клуб',
     'EVENT_CARD', ('IMG_4761',),
     'A tangible gaming-equipment still life in a welcoming shared environment; thoughtful crop and depth, calm light, sense of connection through paired objects. Do not borrow the reference person, name or club facts. No neon sci-fi room, imaginary venue or fake game branding.'),
    ('product', r'\bстекл\w*|\bостеклен|\bархитектур|\bпроизводств|\bпродукц',
     'PRODUCT_ARCHITECTURE', ('IMG_4759',),
     'A clean glass-material or architectural fragment with natural lighting and physically accurate reflections, scale and transparency. Generic conceptual material study, not a photograph of the actual plant or a claim about a particular product.'),
    ('city', r'юбиле\w* город|день город|городск|праздник',
     'PHOTO_HERO', ('IMG_4752',),
     'Atmospheric place-oriented or celebratory still life with a clear hero. Do not invent identifiable landmarks. Take the reference hierarchy and depth, not its yellow highlights or handwriting.'),
)


def brief(topic, body, instruction=''):
    text=(topic+' '+post_format.plain(body)).lower()
    selected=next((s for s in SCENARIOS if re.search(s[1],topic.lower())),None)
    if selected is None:selected=next((s for s in SCENARIOS if re.search(s[1],text)),None)
    name,_,layout,refs,direction=selected or ('announcement','','EVENT_CARD',('IMG_4758',),
        'One meaningful, topic-specific subject, tangible setting and layered photographic depth. Make the human benefit perceptible through objects and composition. No montage or fake documentary event.')
    no_image=bool(re.search(r'без (?:картин\w*|изображени\w*|визуал\w*)|не (?:генерируй|создавай|добавляй|прикрепляй) (?:картин\w*|изображени\w*)',instruction,re.I))
    return {'policy_source':SOURCE,'source_sha256':SOURCE_SHA256,'policy_version':VERSION,'source_pages':[1,3,4,5,6,8,9],
        'media_mode':'NO_VISUAL' if no_image else 'GENERATE_VISUAL',
        'authorization':'user_previously_enabled_automatic_generation',
        'content_type':name,'layout':layout,'references':list(refs),
        'art_direction':direction,'palette':list(PALETTE),
        'synthetic_illustration':True,'status':'NEEDS_REVIEW',
        'original_logo_applied':False,'licensed_typography_applied':False,
        'final_brand_compliance_verified':False}
