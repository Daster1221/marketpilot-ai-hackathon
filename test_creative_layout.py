import copy,unittest
import creative_layout

class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.plan={'concepts':['Предметная сцена с шайбой','Общая поддержка на трибуне','Ожидание матча в раздевалке'],'selected':0,'background':'#FFFFFF','hero_box':[48,300,984,440],'blocks':[{'role':'headline','text':'ХОККЕЙНЫЙ МАТЧ','box':[48,48,984,200],'size':72,'color':'#196C7F','panel':'none'}]}
    def test_collision_rejected_before_image_generation(self):
        self.plan['blocks'][0]['box']=[48,250,984,200]
        with self.assertRaisesRegex(ValueError,'перекрывают'):creative_layout.validate(self.plan,'Хоккейный матч')
    def test_brand_typo_rejected(self):
        self.plan['blocks'][0]['text']='САЛАВАТСТЕКО'
        with self.assertRaisesRegex(ValueError,'написание'):creative_layout.validate(self.plan,'Салаватстекло')
    def test_valid_layout_preserves_spaces_and_records_real_checks(self):
        p=creative_layout.validate(self.plan,'Хоккейный матч')
        self.assertEqual(p['texts'],['ХОККЕЙНЫЙ МАТЧ'])
        self.assertEqual(' '.join(p['blocks'][0]['lines']),'ХОККЕЙНЫЙ МАТЧ')
        self.assertEqual(p['preflight']['geometry'],'passed')
