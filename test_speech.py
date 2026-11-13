import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app
import speech


class SpeechTests(unittest.TestCase):
    def test_recognition_is_local_without_api_key(self):
        model = Mock()
        model.transcribe.return_value = ([SimpleNamespace(text='Нужно два поста')], None)
        with patch.dict(app.os.environ, {'DEEPSEEK_API_KEY': '', 'WHISPER_LANGUAGE': 'ru'}), patch.object(speech, 'load_model', return_value=model), patch.object(app.urllib.request, 'urlopen') as network:
            self.assertEqual(speech.transcribe(b'ogg-bytes'), 'Нужно два поста')
            network.assert_not_called()
            self.assertEqual(model.transcribe.call_args.kwargs['language'], 'ru')
            self.assertEqual(model.transcribe.call_args.args[0].read(), b'ogg-bytes')

    def test_audio_size_is_limited_before_model_load(self):
        with patch.object(speech, 'load_model') as load:
            with self.assertRaises(ValueError):
                speech.transcribe(b'x' * (speech.MAX_AUDIO_BYTES + 1))
            load.assert_not_called()

    def test_empty_transcript_is_not_used(self):
        model = Mock()
        model.transcribe.return_value = ([], None)
        with patch.object(speech, 'load_model', return_value=model):
            with self.assertRaises(ValueError):
                speech.transcribe(b'ogg-bytes')

    def test_local_failure_never_falls_back_to_cloud(self):
        with patch.object(speech, 'load_model', side_effect=ValueError('no local model')), patch.object(app.urllib.request, 'urlopen') as network:
            with self.assertRaises(ValueError):
                speech.transcribe(b'ogg-bytes')
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
