"""Per-user model choice, pinned for one request and isolated across threads."""
from contextvars import ContextVar
from contextlib import contextmanager
import os,json

MODELS=(
    {'key':'deepseek','id':'deepseek/deepseek-v4.1-flash','title':'DeepSeek V4.1 Flash','description':'Экономичный · прежняя модель','input_price':26.07,'output_price':100.25},
    {'key':'gpt41','id':'openai/gpt-4.1','title':'GPT-4.1','description':'Сбалансированный вариант для повседневных задач','input_price':516,'output_price':2062},
    {'key':'sonnet','id':'anthropic/claude-sonnet-5-5','title':'Claude Sonnet 5.5','description':'Рекомендуем для сложных инструкций и редактуры','input_price':500,'output_price':2500},
    {'key':'sol61','id':'openai/gpt-6.1-sol','title':'GPT-6.1 Sol','description':'Усиленный режим для замысла и сложных текстов · рассуждения оплачиваются','input_price':420,'output_price':2100},
)
_CURRENT=ContextVar('request_ai_model',default=None)
_CHAT=ContextVar('request_ai_chat',default=None)

def chat():return _CHAT.get()

def validate(value):
    if not isinstance(value,str) or value not in {item['id'] for item in MODELS}:raise ValueError('Выберите модель из списка настроек.')
    return value

def model_for(chat):
    import bot_features
    saved=bot_features.preferences(chat).get('model')
    return saved if isinstance(saved,str) and saved in {item['id'] for item in MODELS} else os.environ.get('DEEPSEEK_MODEL') or MODELS[1]['id']

def current():
    return _CURRENT.get() or os.environ.get('DEEPSEEK_MODEL') or MODELS[1]['id']

def request_options():
    if current()=='openai/gpt-6.1-sol':
        return {'reasoning_effort':'medium','max_completion_tokens':12000}
    return {}

def title(value):
    return next((item['title'] for item in MODELS if item['id']==value),value)

def choose(chat,value):
    import app
    validate(value)
    with app.db() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT data FROM bot_preferences WHERE chat=?',(chat,)).fetchone()
        settings=json.loads(row['data']) if row else {}
        settings['model']=value
        con.execute('INSERT OR REPLACE INTO bot_preferences VALUES(?,?)',(chat,json.dumps(settings,ensure_ascii=False)))

@contextmanager
def for_chat(chat):
    chat_token=_CHAT.set(chat)
    token=_CURRENT.set(model_for(chat))
    try:yield
    finally:
        _CURRENT.reset(token);_CHAT.reset(chat_token)
