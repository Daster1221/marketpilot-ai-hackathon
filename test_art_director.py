import json,unittest
from unittest.mock import patch
import app,art_director,model_selection


class DirectorTests(unittest.TestCase):
    def test_cheap_model_is_pinned_and_only_bounded_post_and_latest_brief_are_sent(self):
        plan={'concept':'Команда на льду','reference':'sports','prompt':'Complete dynamic sports poster with expressive typography and close foreground hockey equipment.','texts':['КОМАНДА']}
        response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(plan)}}],'usage':{'prompt_tokens':528,'completion_tokens':171}}
        with patch.object(app,'remote_json',return_value=response) as request,patch.dict(app.os.environ,{'DEEPSEEK_API_KEY':'fixture-not-real'}),patch.object(model_selection,'current',return_value='openai/gpt-6.1-sol'):
            result=art_director.plan('Тема','<b>Пост</b>'+'x'*10000,'Правка',{'concept':'Идея','prompt':'y'*9000,'history':'secret history'})
        payload=request.call_args.args[1]
        self.assertEqual(payload['model'],'deepseek/deepseek-v4.1-flash')
        self.assertEqual(payload['reasoning_effort'],'none');self.assertEqual(payload['max_tokens'],1500)
        data=json.loads(payload['messages'][1]['content'])
        self.assertEqual(len(data['post']),4096)
        self.assertNotIn('history',data['previous']);self.assertNotIn('profile',data)
        self.assertEqual(result['render_mode'],'generated_poster')
        self.assertEqual(result['texts'],['КОМАНДА'])
