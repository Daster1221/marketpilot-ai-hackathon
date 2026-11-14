"""Keep the authenticated Mini App available through a temporary HTTPS tunnel."""
import os
import re
import subprocess
import threading
import time
from pathlib import Path
import miniapp_server

ROOT = Path(__file__).resolve().parent


def main():
    try:
        http = miniapp_server.server()
    except ValueError as error:
        print(str(error)+'\nПовторный запуск не нужен. Если Mini App открывается в Telegram, это окно можно закрыть.',flush=True)
        return
    threading.Thread(target=http.serve_forever, daemon=True).start()
    known_hosts = ROOT / 'data' / 'miniapp_known_hosts'
    command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12', '-o', 'StrictHostKeyChecking=accept-new', '-o', 'UserKnownHostsFile=' + str(known_hosts), '-o', 'IdentityAgent=none', '-o', 'IdentityFile=none', '-o', 'ServerAliveInterval=30', '-o', 'ExitOnForwardFailure=yes', '-R', '80:127.0.0.1:8765', 'nokey@localhost.run']
    process=None
    try:
        while True:
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                for line in process.stdout:
                    match = re.search(r'https://[a-z0-9.-]+\.lhr\.life', line)
                    if match:
                        connect_url(match[0])
            except OSError:
                print('Не удалось подключить HTTPS-туннель. Проверяю соединение…',flush=True)
            finally:
                if process is not None:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill();process.wait(timeout=5)
                    process=None
            print('Соединение Mini App прервано. Переподключаюсь через 5 сек…',flush=True)
            time.sleep(5)
    finally:
        if process is not None:
            process.terminate()
        http.shutdown();http.server_close()


def connect_url(url):
    import miniapp_api
    import telegram_bot as bot
    import tempfile
    miniapp_api.register_origin(url)
    path=ROOT/'.env'
    text=path.read_text(encoding='utf-8-sig')
    text,count=re.subn(r'(?m)^MINI_APP_URL=.*$', 'MINI_APP_URL='+url,text)
    if not count:text+='\nMINI_APP_URL='+url+'\n'
    # Keep the settings file complete if another process reads it concurrently.
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=ROOT/'data',prefix='miniapp-env-',delete=False) as handle:
            handle.write(text);temporary=Path(handle.name)
        os.replace(temporary,path)
    finally:
        if temporary and temporary.exists():temporary.unlink()
    os.environ['MINI_APP_URL']=url
    for attempt in range(3):
        try:
            bot.configure_miniapp();break
        except bot.TelegramConnectionError:
            print('Не удалось обновить кнопку Telegram. Повторяю подключение…',flush=True)
            time.sleep(5)
        except ValueError:
            print('Не удалось обновить кнопку Telegram. Проверьте настройки бота. Сайт продолжает работать.',flush=True)
            break
    print('Mini App connected: '+url,flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Mini App остановлен.')
