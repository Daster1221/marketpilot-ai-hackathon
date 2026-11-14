import unittest
import brand_visual
import premium_emoji


class BrandPolicyTests(unittest.TestCase):
    def test_topics_use_distinct_reference_compositions(self):
        sport=brand_visual.brief('Футбольный турнир','Коллеги САЛАВАТСТЕКЛО приглашают на матч.')
        gaming=brand_visual.brief('Открываем киберклуб','Коллеги САЛАВАТСТЕКЛО играют вместе.')
        self.assertEqual(sport['content_type'],'sports')
        self.assertEqual(gaming['content_type'],'gaming')
        self.assertNotEqual(sport['references'],gaming['references'])
        self.assertEqual(sport['palette'],['#196C7F','#C1D0D3','#DDE1E1'])
        self.assertFalse(sport['final_brand_compliance_verified'])

    def test_all_three_verified_packs_are_accessible_with_company_priority(self):
        mapping=premium_emoji.palette(42)
        self.assertEqual(mapping['🏭'],'5458869292520990870')
        self.assertEqual(mapping['👍'],'5456202474312462007')
        self.assertIn('5972282179776940830',mapping.values())  # IconsInTg plane
        self.assertIn('5264880433102857925',mapping.values())  # nowemoji goat
