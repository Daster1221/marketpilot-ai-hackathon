import tempfile,unittest,io,json,urllib.error
from pathlib import Path
from unittest.mock import patch
import app,telegram_bot as bot,premium_emoji as premium,post_format,editorial


class PremiumEmojiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=patch.object(app,'ROOT',Path(self.temp.name));self.root.start()
        (app.ROOT/'data').mkdir();self.env=patch.dict(app.os.environ,{'TELEGRAM_OWNER_ID':'42','TELEGRAM_BOT_TOKEN':'fixture-not-real'});self.env.start()
        bot.init_db();premium.store(42,[{'emoji':'👍','id':'5368324170671202286'}])
    def tearDown(self):self.env.stop();self.root.stop();self.temp.cleanup()
    def test_private_palette_is_isolated_and_channel_fallback_preserves_text(self):
        body='<b>👍 Хорошая новость</b>'
        rendered=premium.render_private(body,42)
        self.assertIn('<tg-emoji emoji-id="5456202474312462007">👍</tg-emoji>',rendered)
        self.assertEqual(rendered,premium.render_private(body,99))
        self.assertEqual(premium.plain_emoji(rendered),body)
    def test_saved_square_lists_render_cleanly_with_real_premium_entities(self):
        body='<b>👍 Приложение</b>\n◾️ График\n◾️ Выплаты'
        result=premium.render_private(body,42)
        self.assertIn('• График\n• Выплаты',result)
        self.assertNotIn('◾',result)
        self.assertIn('<tg-emoji emoji-id=',result)

    def test_publication_uses_premium_only_for_verified_group(self):
        with patch.dict(app.os.environ,{'TELEGRAM_PREMIUM_GROUP_ID':'-1004360012354'}):
            self.assertIn('<tg-emoji ',premium.render_publication('<b>👍 Новость</b>',42,'-1004360012354'))
            self.assertNotIn('<tg-emoji ',premium.render_publication('<b>👍 Новость</b>',42,'-100other'))

    def test_formatting_keeps_only_supported_attributes(self):
        text=post_format.normalize('<blockquote expandable onclick="bad()">Факт</blockquote><tg-emoji emoji-id="5368324170671202286" onerror="bad()">👍</tg-emoji>')
        self.assertIn('<blockquote expandable>',text);self.assertIn('emoji-id="5368324170671202286"',text);self.assertNotIn('bad',text)
        self.assertEqual(post_format.normalize('<tg-emoji emoji-id="not-a-number">👍</tg-emoji>'),'👍')
    def test_custom_emoji_is_not_split_across_pages(self):
        body='<b>1234 <tg-emoji emoji-id="5368324170671202286">👍</tg-emoji> abc</b>'
        pages=post_format.split_pages(body,limit=6,formatted=True)
        self.assertEqual(sum(page.count('<tg-emoji ') for page in pages),1)
        self.assertTrue(all(post_format.length(p)<=6 for p in pages))
        self.assertEqual(post_format.plain(''.join(pages)),post_format.plain(body))
    def test_expandable_callout_retains_provenance_and_fake_quote_is_removed(self):
        body,notes,blocks=editorial.clean_body('<b>Результат</b><aside expandable>Курс прошли 24 коллеги.</aside>','Курс прошли 24 коллеги.',return_blocks=True)
        self.assertIn('<blockquote expandable>',body)
        self.assertIn('<aside expandable>',editorial.encode_fact_blocks(body,blocks))
        clean,_=editorial.remove_unconfirmed_quotes('<blockquote expandable>Выдуманные слова</blockquote>','Другие данные')
        self.assertNotIn('Выдуманные слова',clean)
    def test_emoji_import_does_not_swallow_normal_task(self):
        with patch.object(bot,'tg',return_value=[{'emoji':'👋','custom_emoji_id':'123456789','set_name':'nowemoji'}]) as api,patch.object(bot,'say'):
            self.assertFalse(premium.receive(42,{'text':'Напиши пост 👍','entities':[{'type':'custom_emoji','custom_emoji_id':'5368324170671202286','offset':12,'length':2}]}))
            api.assert_not_called()
            self.assertTrue(premium.receive(42,{'text':'👋','entities':[{'type':'custom_emoji','custom_emoji_id':'123456789','offset':0,'length':2}]}))
        self.assertNotIn('123456789',premium.palette(42).values())  # Only the verified bundled catalog renders.

    def test_only_pack_emoji_render_and_sequences_never_leave_fragments(self):
        body='<b>👍 20% 👩‍🔧 1️⃣</b> #Компания'
        rendered=premium.render_private(body,42)
        self.assertIn('emoji-id="5456202474312462007"',rendered)
        self.assertNotIn('👩',rendered);self.assertNotIn('\u200d',rendered)
        self.assertIn('20%',rendered);self.assertIn('#Компания',rendered)
        self.assertNotIn('tg-emoji',premium.remove_emoji(rendered))
        self.assertNotIn('👍',premium.remove_emoji(rendered))
    def test_rejected_custom_emoji_falls_back_only_after_definite_http_error(self):
        error=urllib.error.HTTPError('https://api.telegram.org/hidden',400,'Bad Request',{},io.BytesIO(b'{"description":"Bad Request: custom emoji is not allowed"}'))
        with patch.object(app,'remote_json',side_effect=[error,{'ok':True,'result':{'message_id':1}}]) as api:
            bot.tg('sendMessage',{'chat_id':42,'text':'<tg-emoji emoji-id="123456789">👍</tg-emoji>','parse_mode':'HTML'})
        self.assertEqual(api.call_count,2);self.assertEqual(api.call_args.args[1]['text'],'')
    def test_uncertain_network_error_is_never_retried(self):
        with patch.object(app,'remote_json',side_effect=TimeoutError) as api:
            with self.assertRaises(bot.TelegramConnectionError):bot.tg('sendMessage',{'chat_id':42,'text':'<tg-emoji emoji-id="123456789">👍</tg-emoji>'})
        api.assert_called_once()
    def test_unauthorized_sender_cannot_import_palette(self):
        with patch.object(premium,'receive') as receive:
            bot.handle({'message':{'chat':{'id':99,'type':'private'},'from':{'id':99},'text':'👍'}})
        receive.assert_not_called()
