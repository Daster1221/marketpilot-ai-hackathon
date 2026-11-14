import unittest
from io import BytesIO
from PIL import Image
from unittest.mock import patch
import post_cover


class CoverTests(unittest.TestCase):
    def test_generated_poster_does_not_get_an_extra_script_headline(self):
        raw=BytesIO();Image.new('RGB',(1080,1080),'#9ABAC2').save(raw,format='PNG')
        decision={'director':{'render_mode':'generated_poster','texts':['КОМАНДА'],'tone':'light'}}
        from PIL import ImageDraw
        with patch.object(ImageDraw.ImageDraw,'text') as draw:
            post_cover.render(raw.getvalue(),'Тема','<b>Наш старый заголовок</b>',decision)
        draw.assert_not_called()
        self.assertEqual(decision['cover']['texts'],['КОМАНДА'])
    def test_legacy_minimal_cover_has_headline_and_no_ai_footer(self):
        raw=BytesIO();Image.new('RGB',(1080,1080),'#9ABAC2').save(raw,format='PNG')
        decision={'director':{'overlay':'minimal'}}
        from PIL import ImageDraw
        original=ImageDraw.ImageDraw.text;drawn=[]
        def capture(draw,xy,text,*args,**kwargs):
            drawn.append(text);return original(draw,xy,text,*args,**kwargs)
        with patch.object(ImageDraw.ImageDraw,'text',capture):
            post_cover.render(raw.getvalue(),'Тема','<b>Новый завод в Уфе ищет команду</b>',decision)
        self.assertEqual(decision['cover']['overlay'],'headline')
        self.assertTrue(decision['cover']['headline'])
        self.assertIn('Новый завод',' '.join(drawn))
        self.assertFalse(any('ИИ-иллюстрация' in text for text in drawn))
    def test_extracts_address_not_generic_factory_description(self):
        body='<b>Новый завод ищет команду</b>\n\n15 октября открылся завод. Теперь у компании появилась новая площадка в Уфе.\n\nАдрес: <b>Уфа, Владивостокская, 13</b>\n\nТребуются работники. Оставьте заявку на сайте.'
        brief=post_cover.brief('Открытие завода',body)
        self.assertEqual(brief['facts'],['Уфа, Владивостокская, 13','Открытие: 15 октября'])
        self.assertEqual(brief['cta'],'ОСТАВЬТЕ ЗАЯВКУ НА САЙТЕ')

    def test_renderer_produces_a_readable_cover_and_keeps_review_status(self):
        raw=BytesIO();Image.new('RGB',(1400,800),'#9ABAC2').save(raw,format='JPEG')
        decision={};result=post_cover.render(raw.getvalue(),'Матч','<b>Футбольный полуфинал</b>\n\n20 ноября в 17:00.',decision)
        self.assertEqual(Image.open(BytesIO(result)).size,(1080,1080))
        self.assertTrue(decision['cover_rendered'])
        self.assertFalse(decision['final_brand_compliance_verified'])
        self.assertEqual(decision['cover']['facts'],['20 ноября в 17:00'])
