import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import telegram_bot as bot
import start_miniapp
from runtime_lock import single_instance


class StartupTests(unittest.TestCase):
    def test_connection_retries_transport_errors_without_repeating_mutations(self):
        with patch.object(bot,'tg',side_effect=[bot.TelegramConnectionError('offline'),{'id':1},{'url':''}]) as api,patch.object(bot.time,'sleep') as sleep:
            identity,webhook=bot.connect_telegram()
        self.assertEqual(identity,{'id':1});self.assertEqual(webhook,{'url':''})
        self.assertEqual([c.args[0] for c in api.call_args_list],['getMe','getMe','getWebhookInfo'])
        sleep.assert_called_once_with(5)

    def test_invalid_token_does_not_retry_forever(self):
        with patch.object(bot,'tg',side_effect=bot.TelegramAPIError('bad token','other')),patch.object(bot.time,'sleep') as sleep:
            with self.assertRaises(bot.TelegramAPIError):bot.connect_telegram()
        sleep.assert_not_called()

    def test_duplicate_miniapp_launch_finishes_without_traceback_or_new_tunnel(self):
        with patch.object(start_miniapp.miniapp_server,'server',side_effect=ValueError('Mini App уже запущен.')),patch.object(start_miniapp.subprocess,'Popen') as process,patch('builtins.print') as output:
            start_miniapp.main()
        process.assert_not_called();self.assertIn('Повторный запуск не нужен',output.call_args.args[0])

    def test_process_lock_blocks_second_instance_and_releases(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bot.lock'
            with single_instance(path):
                with self.assertRaises(BlockingIOError):
                    with single_instance(path):pass
            with single_instance(path):pass

    def test_tunnel_reconnect_keeps_same_local_server(self):
        from unittest.mock import Mock
        http=Mock();process=Mock();process.stdout=[]
        with patch.object(start_miniapp.miniapp_server,'server',return_value=http) as server,patch.object(start_miniapp.threading,'Thread'),patch.object(start_miniapp.subprocess,'Popen',return_value=process) as launch,patch.object(start_miniapp.time,'sleep',side_effect=[None,KeyboardInterrupt]),patch('builtins.print'):
            with self.assertRaises(KeyboardInterrupt): start_miniapp.main()
        server.assert_called_once();self.assertEqual(launch.call_count,2)
        http.shutdown.assert_called_once();http.server_close.assert_called_once()
