"""Standalone rollout checks: python -m unittest discover -s tests -p test_hook_title_frame.py"""
import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from backend.studio.render.hook_title_frame import localized_title, render_hook_title_frame


class HookFrameTests(unittest.TestCase):
    def test_three_languages_and_image_dimensions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.png'
            Image.new('RGB', (1920, 1080), 'red').save(source)
            production = SimpleNamespace(slug='george_martin', manifest={})
            for language in ('en', 'es', 'pt-BR'):
                output = root / (language+'.png')
                render_hook_title_frame(source, output, title=localized_title(production, language), language=language)
                with Image.open(output) as image:
                    self.assertEqual(image.size, (1920, 1080))
                    self.assertEqual(image.getpixel((960, 600)), (255, 0, 0))
                    self.assertNotEqual(image.getpixel((0, 600)), (255, 0, 0))

    def test_translation_required_and_override(self):
        production = SimpleNamespace(slug='unknown', title='Example', subtitle='A story', manifest={})
        self.assertEqual(localized_title(production, 'en'), 'Example: A story')
        with self.assertRaisesRegex(ValueError, 'hook_titles.es'):
            localized_title(production, 'es')
        production.manifest['hook_titles'] = {'es': 'Una historia'}
        self.assertEqual(localized_title(production, 'es'), 'Una historia')

    def test_long_title_fits(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'source.png'
            Image.new('RGB', (1920, 1080)).save(source)
            render_hook_title_frame(source, Path(folder)/'frame.png', title='The extraordinary story of the artists who transformed music around the world', language='en')

    def rollout(self, completed, recorded):
        # Load actual station control flow without unavailable DB/Supabase imports.
        source = Path(__file__).resolve().parents[1]/'backend/studio/stations/build_localized_delivery.py'
        tree = ast.parse(source.read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_localized_deliveries')
        namespace = {'Any': object, 'ProductionExecution': object, 'Builder': object,
                     'MediaValidator': object, 'BedEnsurer': object, 'ffmpeg_delivery': None,
                     'validate_delivery_media': None, 'SUPPORTED_LANGUAGE_CODES': ('en',),
                     'LAYOUT_VERSION': 'widescreen-title-v1', 'localized_title': lambda p,l:'George Martin',
                     'station': lambda l:l, 'video_artifact': lambda l:'video',
                     'sidecar': lambda e,l:Path('sidecar'), '_recorded':lambda p:recorded,
                     'resolve_bed_track':lambda *a,**k:Path('bed')}
        calls=[]
        namespace['render_hook_title_frame']=lambda *a,**k: calls.append('frame') or Path('frame')
        namespace['save_json_atomic']=lambda p,v: calls.append(v)
        namespace['_inputs']=lambda *a:(Path('opening'),Path('master'),Path('hook'),Path('brand'),Path('bed'),(),{'hook_visual':'digest'})
        namespace['bool']=bool
        compile_tree=ast.Module(body=[node], type_ignores=[])
        exec(compile(compile_tree, str(source), 'exec'), namespace)
        session=SimpleNamespace(**{name:lambda *a,**k:None for name in ('start_station','finish_station','metric','artifact')})
        execution=SimpleNamespace(factory_root=Path('factory'), resume=lambda:None,
            pending_artifacts=lambda **k:[] if completed else ['video'],
            output_path=lambda **k:Path('existing'), requeue_artifact=lambda **k:calls.append('requeue'),
            start_artifact=lambda **k:Path('output'), complete_artifact=lambda **k:None,
            require_verified_completed=lambda **k:None)
        changed=namespace['run_localized_deliveries'](SimpleNamespace(session=session),execution,
            builder=lambda *a:calls.append(('build',a[2])),
            media_validator=lambda *a:{'fps':30,'duration_seconds':100})
        return changed,calls

    def test_completed_legacy_not_rebuilt(self):
        self.assertEqual(self.rollout(True, {'hook_visual':'digest'}), (False, []))

    def test_pending_uses_frame_and_records_layout(self):
        changed,calls=self.rollout(False,{})
        self.assertTrue(changed)
        self.assertIn(('build',Path('frame')),calls)
        self.assertEqual(calls[-1]['input_sha256']['hook_layout_version'],'widescreen-title-v1')

    def test_completed_styled_resumes_without_render(self):
        recorded={'hook_visual':'digest','hook_layout_version':'widescreen-title-v1','hook_title':'George Martin','hook_language':'en'}
        self.assertEqual(self.rollout(True,recorded),(False,[]))

    def test_source_change_in_completed_legacy_retains_legacy_art(self):
        changed,calls=self.rollout(True,{'hook_visual':'old-digest'})
        self.assertTrue(changed)
        self.assertNotIn('frame',calls)
        self.assertIn(('build',Path('hook')),calls)


if __name__ == '__main__':
    unittest.main()
