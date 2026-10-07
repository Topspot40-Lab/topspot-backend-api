import unittest
from backend.services.artist_spotlight_narration import spotlight_narration_choices, spotlight_bio_asset

class SpotlightNarrationTests(unittest.TestCase):
    def test_new_program_uses_short_bio_and_requested_details(self):
        self.assertEqual(spotlight_narration_choices({'detailLength': 'short'}, {}), ('short', 'short'))
        self.assertEqual(spotlight_narration_choices({'detailLength': 'off'}, {'bio_length': 'long'}), ('off', 'long'))

    def test_legacy_detail_default_and_invalid_choices(self):
        self.assertEqual(spotlight_narration_choices({}, {}), ('long', 'short'))
        with self.assertRaises(ValueError):
            spotlight_narration_choices({'detailLength': 'bad'}, {})
        with self.assertRaises(ValueError):
            spotlight_narration_choices({}, {'bio_length': 'bad'})

    def test_selects_matching_localized_bio_asset(self):
        assets = {'short_bucket': 'audio-es', 'short_key': 'artist/short.mp3', 'long_bucket': 'audio-es', 'long_key': 'stories/long.mp3'}
        self.assertEqual(spotlight_bio_asset(assets, 'short'), ('audio-es', 'artist/short.mp3'))
        self.assertEqual(spotlight_bio_asset(assets, 'long'), ('audio-es', 'stories/long.mp3'))

    def test_missing_long_bio_does_not_silently_play_short(self):
        self.assertEqual(spotlight_bio_asset({'short_bucket': 'audio-es', 'short_key': 'artist/short.mp3'}, 'long'), (None, None))


class SpotlightPlaybackBranchTests(unittest.TestCase):
    def run_branch(self, *, detail='short', bio='short', play_bio=True):
        # Exercise the actual router branch with narration acknowledgements and
        # localized metadata stubbed; no database or FastAPI installation needed.
        import ast
        import asyncio
        import logging
        from pathlib import Path
        from types import SimpleNamespace
        from urllib.parse import quote
        source = Path(__file__).parents[1] / 'routers' / 'playback_control.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        branch = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                      and isinstance(node.test, ast.Compare)
                      and any(isinstance(value, ast.Constant) and value.value == 'artist_spotlight'
                              for value in node.test.comparators))
        wrapper = ast.parse('async def launch(context, payload, track, selection):\n    pass').body[0]
        wrapper.body = branch.body
        phases = []
        class Event:
            def clear(self): pass
            async def wait(self): pass
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def execute(self, query, parameters):
                self.language = parameters['language']
                return self
            def mappings(self): return self
            def first(self):
                return {'short_bucket': 'audio-es', 'short_key': 'artist/short.mp3',
                        'long_bucket': 'audio-es', 'long_key': 'stories/long.mp3'}
        namespace = {
            'spotlight_narration_choices': spotlight_narration_choices,
            'spotlight_bio_asset': spotlight_bio_asset,
            'engine': SimpleNamespace(connect=Connection), 'text': lambda query: query,
            'logger': logging.getLogger(__name__), 'user_id': 'test-listener',
            'get_genre_bed_key': lambda genre: 'bed.mp3', 'BED_BUCKET': 'beds',
            'narration_done_event': lambda user: Event(), 'quote': quote,
            '_normalize_tts_locale': lambda language: language,
            'update_phase': lambda user, phase, **kwargs: phases.append((phase, kwargs['context'])),
            'short_detail_keys_for': lambda **kwargs: ('audio-es', 'short_detail/song.mp3'),
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])), str(source), 'exec'), namespace)
        context = {'type': 'artist_spotlight', 'spotify_artist_id': 'artist', 'artist_id': '42',
                   'language': 'es', 'bio_length': bio, 'play_artist_bio': play_bio}
        track = SimpleNamespace(spotify_track_id='song', track_name='Song', artist_name='Artist', rank=1)
        selection = SimpleNamespace(language='es', voicePlayMode='before')
        asyncio.run(namespace['launch'](context, {'selection': {'detailLength': detail}}, track, selection))
        return phases

    def test_short_program_publishes_short_bio_then_short_detail_then_track(self):
        phases = self.run_branch()
        self.assertEqual([phase for phase, _ in phases], ['artist', 'detail', 'track'])
        self.assertTrue(phases[0][1]['audio_url'].endswith('/audio-es/artist/short.mp3'))
        self.assertTrue(phases[1][1]['audio_url'].endswith('/audio-es/short_detail/song.mp3'))

    def test_long_bio_with_details_off_goes_directly_to_music_after_bio(self):
        phases = self.run_branch(detail='off', bio='long')
        self.assertEqual([phase for phase, _ in phases], ['artist', 'track'])
        self.assertTrue(phases[0][1]['audio_url'].endswith('/audio-es/stories/long.mp3'))

    def test_following_track_does_not_repeat_bio_and_uses_long_detail(self):
        phases = self.run_branch(detail='long', play_bio=False)
        self.assertEqual([phase for phase, _ in phases], ['detail', 'track'])
        self.assertTrue(phases[0][1]['audio_url'].endswith('/audio-es/detail/song.mp3'))

if __name__ == '__main__':
    unittest.main()
