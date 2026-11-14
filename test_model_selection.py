import tempfile,json,threading,unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import app,telegram_bot as bot,bot_features as features,miniapp_api as api,model_selection as models


class ModelSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=patch.object(app,'ROOT',Path(self.temp.name));self.root.start()
        (app.ROOT/'data').mkdir();self.env=patch.dict(app.os.environ,{'DEEPSEEK_MODEL':'openai/gpt-4.1','DEEPSEEK_API_KEY':'fixture-not-real'});self.env.start()
        bot.init_db();api.init_db()
    def tearDown(self):self.env.stop();self.root.stop();self.temp.cleanup()
    def test_choice_persists_and_is_shared_with_app_but_isolated_per_user(self):
        models.choose(42,models.MODELS[0]['id'])
        self.assertEqual(api.data(42)['profile']['model'],models.MODELS[0]['id'])
        self.assertEqual(api.data(99)['profile']['model'],'openai/gpt-4.1')
        self.assertEqual(len(api.data(42)['profile']['model_options']),4)
        for value in ('unknown','openai/gpt-4.1/other',{},None):
            with self.assertRaises(ValueError):models.choose(42,value)
    def test_parallel_users_do_not_change_each_others_model(self):
        models.choose(42,models.MODELS[0]['id']);models.choose(99,models.MODELS[2]['id'])
        barrier=threading.Barrier(2)
        def task(chat):
            with models.for_chat(chat):
                barrier.wait(timeout=5)
                return models.current()
        with ThreadPoolExecutor(max_workers=2) as pool:
            one=pool.submit(task,42);two=pool.submit(task,99)
            self.assertEqual(one.result(),models.MODELS[0]['id']);self.assertEqual(two.result(),models.MODELS[2]['id'])
        self.assertEqual(models.current(),'openai/gpt-4.1')
    def test_running_request_keeps_model_after_setting_changes(self):
        models.choose(42,models.MODELS[2]['id'])
        response={'choices':[{'message':{'content':'{"ok":true}'}}]}
        with models.for_chat(42),patch.object(app,'deepseek_request',return_value=response) as provider:
            models.choose(42,models.MODELS[0]['id'])
            app.ai_json('System',{'task':'Synthetic test'})
        self.assertEqual(provider.call_args.args[0]['model'],models.MODELS[2]['id'])
        self.assertEqual(models.model_for(42),models.MODELS[0]['id'])

    def test_sol_uses_supported_reasoning_options_without_affecting_other_models(self):
        models.choose(42,'openai/gpt-6.1-sol')
        response={'choices':[{'message':{'content':'{"ok":true}'}}]}
        with models.for_chat(42),patch.object(app,'deepseek_request',return_value=response) as provider:
            app.ai_json('System',{'task':'Synthetic test'})
        payload=provider.call_args.args[0]
        self.assertEqual(payload['model'],'openai/gpt-6.1-sol')
        self.assertEqual(payload['reasoning_effort'],'medium')
        self.assertEqual(payload['max_completion_tokens'],12000)
        self.assertEqual(models.request_options(),{})
    def test_bot_and_miniapp_entry_points_apply_selected_model(self):
        models.choose(42,models.MODELS[2]['id'])
        update={'message':{'chat':{'id':42,'type':'private'},'from':{'id':42},'text':'synthetic'}}
        with patch.dict(app.os.environ,{'TELEGRAM_OWNER_ID':'42'}),patch.object(bot,'_handle',side_effect=lambda update:models.current()):
            self.assertEqual(bot.handle(update),models.MODELS[2]['id'])
        with patch.object(api,'_workflow',side_effect=lambda chat,request:models.current()):
            self.assertEqual(api.workflow(42,{}),models.MODELS[2]['id'])
    def test_bot_model_button_changes_preference_without_model_request(self):
        with patch.object(bot,'say'),patch.object(app,'deepseek_request') as provider:
            features.callback(42,'feat_model:sonnet')
        provider.assert_not_called();self.assertEqual(models.model_for(42),models.MODELS[2]['id'])

    def test_miniapp_settings_endpoint_updates_shared_model(self):
        import io,miniapp_server
        from unittest.mock import Mock
        handler=miniapp_server.Handler.__new__(miniapp_server.Handler)
        handler.path='/data';handler.api_response=Mock()
        body=json.dumps({'model':models.MODELS[2]['id']}).encode()
        handler.headers={'Host':'fixture.example','Origin':'https://fixture.example','Content-Type':'application/json','Content-Length':str(len(body))}
        handler.rfile=io.BytesIO(body)
        with patch.object(api,'authenticate',return_value=42),patch.object(app,'deepseek_request') as provider:
            handler.do_PATCH()
        self.assertEqual(handler.api_response.call_args.args[0],200)
        self.assertEqual(models.model_for(42),models.MODELS[2]['id']);provider.assert_not_called()
