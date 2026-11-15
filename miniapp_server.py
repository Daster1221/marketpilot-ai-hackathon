"""Mini App static assets and authenticated API; no project file browsing."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
import mimetypes
import json

ROOT = Path(__file__).resolve().parent / 'miniapp'


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def api_response(self, status, value):
        raw=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store, private')
        try:
            self.end_headers();self.wfile.write(raw)
        except (ConnectionError,BrokenPipeError):
            # The job is already persisted. A dropped HTTP reply must not cause
            # a second response or retry the operation. Clients recover by key.
            pass

    def handle_api(self, method):
        import miniapp_api as api
        path=urlsplit(self.path).path
        try:
            chat=api.authenticate(self.headers.get('X-Telegram-Init-Data',''))
            if method=='GET':
                if path.startswith('/post-images/') and path[13:].isdigit():
                    raw,mime=api.image(chat,int(path[13:]))
                    self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store, private');self.end_headers();self.wfile.write(raw);return
                if path=='/data': result=api.data(chat)
                elif path=='/users':result=__import__('user_access').listing(chat)
                elif path=='/knowledge':result=__import__('marketer').snapshot(chat)
                elif path=='/last-transcript': result=api.last_transcript(chat)
                elif path.startswith('/job-requests/'): result=api.job_request(chat,path.removeprefix('/job-requests/'))
                elif path.startswith('/posts/') and path[7:].isdigit(): result=api.serialize(api.post(chat,int(path[7:])))
                elif path.startswith('/jobs/'): result=api.job(chat,path[6:])
                else: return self.api_response(404,{'detail':'Раздел не найден.'})
            else:
                import os
                origin=self.headers.get('Origin','')
                if not api.origin_allowed(origin,self.headers.get('Host','')):
                    raise PermissionError('Запрос с другого сайта отклонён.')
                if method=='POST' and path=='/documents':
                    size=int(self.headers.get('Content-Length','0'))
                    if not 1<=size<=5*1024*1024:raise ValueError('Документ должен быть не больше 5 МБ.')
                    raw=self.rfile.read(size)
                    if len(raw)!=size:raise ValueError('Загрузка документа прервана.')
                    return self.api_response(200,api.enqueue(chat,{'operation':'document','document':raw,'filename':unquote(self.headers.get('X-Filename','document')),'request_id':self.headers.get('X-Request-ID','')}))
                if method=='POST' and path=='/transcribe':
                    size=int(self.headers.get('Content-Length','0'))
                    if not 1<=size<=5*1024*1024: raise ValueError('Запись должна быть не больше 5 МБ.')
                    mime=self.headers.get('Content-Type','')
                    if not mime.startswith(('audio/','video/webm','application/octet-stream')): raise ValueError('Отправьте аудиозапись.')
                    audio=self.rfile.read(size)
                    if len(audio)!=size:raise ValueError('Загрузка записи прервана. Попробуйте отправить её снова.')
                    return self.api_response(200,api.enqueue(chat,{'operation':'transcribe','audio':audio,'content_type':mime,'request_id':self.headers.get('X-Request-ID','')}))
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    raise ValueError('Ожидался JSON-запрос.')
                size=int(self.headers.get('Content-Length','0'))
                if not 1<=size<=32000: raise ValueError('Слишком большой запрос.')
                body=json.loads(self.rfile.read(size))
                if not isinstance(body,dict): raise ValueError('Некорректный запрос.')
                if method=='POST' and path=='/users':
                    import user_access,telegram_bot as b
                    if body.get('action')=='remove':user_access.revoke(chat,body.get('user_id'))
                    else:
                        uid=user_access.grant(chat,body.get('user_id',''))
                        try:
                            profile=b.tg('getChat',{'chat_id':uid});user_access.observe({'id':uid,**{k:profile.get(k,'') for k in ('username','first_name','last_name')}})
                        except ValueError:pass
                    result=user_access.listing(chat)
                elif method=='POST' and path=='/workflow': result=api.enqueue(chat,body)
                elif method=='PATCH' and path.startswith('/posts/') and path[7:].isdigit(): result=api.save_post(chat,int(path[7:]),body)
                elif method=='PATCH' and path=='/data':
                    import telegram_bot as b
                    import model_selection
                    if 'model' in body:model_selection.validate(body['model'])
                    state=b.session(chat); answers=json.loads(state['answers'])
                    for source,target in (('audience','audience'),('tone','style'),('goals','objective')):
                        if source in body:
                            if not isinstance(body[source],str) or len(body[source])>600: raise ValueError('Сократите настройку до 600 символов.')
                            answers[target]=body[source]
                    state['answers']=json.dumps(answers,ensure_ascii=False);b.save(state)
                    if 'model' in body:model_selection.choose(chat,body['model'])
                    result=api.data(chat)['profile']
                else: return self.api_response(404,{'detail':'Действие недоступно.'})
            return self.api_response(200,result)
        except ConnectionError: return
        except PermissionError as error: return self.api_response(403,{'detail':str(error)})
        except (ValueError,KeyError,TypeError) as error: return self.api_response(400,{'detail':str(error) if isinstance(error,ValueError) else 'Некорректный запрос.'})
        except Exception: return self.api_response(500,{'detail':'Не удалось выполнить запрос. Попробуйте ещё раз.'})

    def do_POST(self):
        self.handle_api('POST')

    def do_PATCH(self):
        self.handle_api('PATCH')

    def do_GET(self):
        path=urlsplit(self.path).path
        if path in ('/data','/last-transcript','/knowledge','/users') or path.startswith(('/posts/','/jobs/','/post-images/','/job-requests/')):
            return self.handle_api('GET')
        try:
            name = unquote(urlsplit(self.path).path).lstrip('/') or 'index.html'
            target = (ROOT / name).resolve()
            valid = target.is_relative_to(ROOT.resolve()) and target.is_file() and target.suffix.lower() in ('.html', '.css', '.js', '.png', '.jpg', '.jpeg', '.webp', '.svg', '.woff', '.woff2')
        except (ValueError, OSError):
            valid = False
        if not valid:
            self.send_error(404)
            return
        raw = target.read_bytes()
        self.send_response(200)
        mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        if target.suffix in ('.html', '.css', '.js'):
            mime += '; charset=utf-8'
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Permissions-Policy', 'microphone=(self)')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'")
        try:
            self.end_headers()
            self.wfile.write(raw)
        except ConnectionError:
            pass

    def log_message(self, *args):
        pass


def server():
    import miniapp_api
    import socket
    # Windows otherwise permits two HTTPServer instances on the same port.
    # That leaves separate tunnels updating the menu while serving stale code.
    http=ThreadingHTTPServer(('127.0.0.1',8765),Handler,bind_and_activate=False)
    if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
        http.allow_reuse_address=False
        http.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
    try:
        http.server_bind();http.server_activate()
    except OSError:
        http.server_close()
        raise ValueError('Mini App уже работает. Второй запуск не требуется.') from None
    miniapp_api.init_db()
    return http


if __name__ == '__main__':
    print('Mini App: http://127.0.0.1:8765')
    server().serve_forever()
