import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.error

import configure_deepseek as setup


class ConfigureTests(unittest.TestCase):
    def test_save_replaces_key_and_preserves_telegram(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '.env'
            path.write_text('TELEGRAM_BOT_TOKEN=telegram-test\nDEEPSEEK_API_KEY=old\nDEEPSEEK_API_KEY=duplicate\n', encoding='utf-8')
            setup.save_key(path, 'new-test-key')
            text = path.read_text(encoding='utf-8')
            self.assertIn('TELEGRAM_BOT_TOKEN=telegram-test', text)
            self.assertEqual(text.count('DEEPSEEK_API_KEY='), 1)
            self.assertIn('DEEPSEEK_API_KEY=new-test-key', text)
            self.assertFalse(path.with_name('.env.tmp').exists())

    def test_rejected_key_is_never_saved(self):
        with patch.object(setup.getpass, 'getpass', return_value='test-key'), patch.object(setup, 'verify', side_effect=urllib.error.HTTPError('https://api.deepseek.com/models', 401, '', {}, None)), patch.object(setup, 'save_key') as save, patch('builtins.print'):
            self.assertEqual(setup.main(), 1)
            save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
