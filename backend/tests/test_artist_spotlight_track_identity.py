import ast
from pathlib import Path
import unittest


class ArtistSpotlightTrackIdentityTest(unittest.TestCase):
    def test_artist_tracks_returns_artist_identity_for_browser_biography(self):
        source = Path(__file__).parents[1] / 'routers' / 'artist_spotlight.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == 'artist_tracks')
        function.decorator_list = []
        row = {'track_id': 10, 'artist_id': 1146, 'spotify_artist_id': 'artist-spotify-id'}
        queries = []

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def execute(self, query, params):
                queries.append((query, params))
                return self

            def mappings(self):
                return self

            def all(self):
                # A real database can return this field only if selected.
                self_test.assertIn('a.spotify_artist_id', queries[-1][0])
                return [row]

        class Engine:
            def connect(self):
                return Connection()

        self_test = self
        namespace = {'Query': lambda *args, **kwargs: None, 'text': lambda sql: sql, 'engine': Engine()}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        self.assertEqual(namespace['artist_tracks'](artist_id=1146), [row])
        self.assertEqual(queries[0][1], {'artist_id': 1146})


if __name__ == '__main__':
    unittest.main()
