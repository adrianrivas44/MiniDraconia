import unittest
from unittest.mock import patch
from DyberPet.brain import Brain

class ScriptedProduct(unittest.TestCase):
    def test_legacy_local_never_constructs_or_contacts_local_runtime(self):
        with patch('DyberPet.brain.local.LocalServer', side_effect=AssertionError('local runtime forbidden')), patch('socket.socket', side_effect=AssertionError('network forbidden')):
            brain = Brain(config={'provider': 'builtin_local'}, environ={})
            self.assertIn(brain.reply('hello'), brain.lines)
            brain.close()

    def test_default_migrates_only_mode_preserving_profile(self):
        import json
        from DyberPet.paths import user_root
        from DyberPet.brain import load_config
        path = user_root()/'ai.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        old = {'provider':'builtin_local', 'local_model':'old', 'custom':{'retained':True}}
        path.write_text(json.dumps(old), encoding='utf-8')
        self.assertEqual(load_config()['provider'], 'offline_phrases')
        self.assertEqual(json.loads(path.read_text()), dict(old, provider='offline_phrases'))
        self.assertEqual(json.loads(path.with_suffix('.s1-backup.json').read_text()), old)

    def test_events_cooldown_exhaustion_and_state_reload(self):
        import random
        from DyberPet.paths import user_root
        brain = Brain(config={'provider':'offline_phrases'}, environ={}, rng=random.Random(3))
        state = user_root()/'scripted-state.json'
        for event in ['greet','touch','drag','happy','bye','idle']:
            previous = None
            for i in range(12):
                line = brain.event(event, now=100+i*4)
                self.assertTrue(line)
                self.assertNotEqual(previous, line)
                self.assertEqual(brain.event(event, now=100+i*4+1), '')
                previous = line
            brain.save_state(state)
            other = Brain(config={'provider':'offline_phrases'}, environ={}, rng=random.Random(3), state_path=state)
            self.assertNotEqual(other.event(event, now=200), previous)

    def test_byo_unavailable_cannot_contact_even_timeout_transport(self):
        def forbidden(*a, **k):
            self.fail('No transport may run while BYO is unavailable')
        brain = Brain(config={'provider':'connect_my_ai'}, environ={}, transport=forbidden)
        self.assertEqual(brain.config['provider'], 'offline_phrases')
        self.assertIn(brain.reply('hello'), brain.lines)

    def test_preferences_refuse_unavailable_provider(self):
        from DyberPet.brain import save_preferences
        with self.assertRaisesRegex(ValueError, 'not available'):
            save_preferences('connect_my_ai', '', '')

    def test_legacy_entry_points_never_ping(self):
        from DyberPet import local_brain
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            self.assertFalse(local_brain.ping('http://127.0.0.1:11434'))
            self.assertIsNone(local_brain.chat('hello', {'enabled':True}))
            self.assertIsNone(local_brain.chat_with_messages([], {'enabled':True}))

    def test_ui_only_two_modes_and_unavailable_byo(self):
        from PySide6.QtWidgets import QApplication
        from DyberPet.DyberSettings.AIPrivacyUI import AIPrivacyInterface
        app = QApplication.instance() or QApplication([])
        view = AIPrivacyInterface()
        self.assertEqual(view.provider.count(), 2)
        self.assertEqual(view.provider.itemText(0), 'Scripted offline')
        view.provider.setCurrentIndex(1)
        self.assertFalse(view.save.isEnabled())
        self.assertIn('not available', view.status.text().lower())
        view.close()

    def test_real_qt_chat_signal_and_pet_event_methods(self):
        from DyberPet.brain.selftest import exercise
        result = exercise()
        self.assertEqual(result['qt_chat_sent'], 1)
        self.assertEqual(result['pet_event_bubbles'], 2)
        self.assertEqual(result['network_attempts'], 0)


class CloseBuildContract(unittest.TestCase):
    def test_build_preserves_authorized_buildtools(self):
        import importlib.util, os
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("package_scripted", root/"package_scripted.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertTrue(callable(getattr(module, "build_environment", None)), "missing build environment preservation")
        env = module.build_environment(root/"work/s1/test-profile")
        self.assertIn(str(root/"full-engine"), env["PYTHONPATH"].split(os.pathsep))
        self.assertIn(str(root/"buildtools"), env["PYTHONPATH"].split(os.pathsep))


class OfflineCloseProduct(unittest.TestCase):
    def test_actual_pet_events_settings_audio_and_quit_without_text(self):
        from DyberPet.brain import selftest
        self.assertTrue(callable(getattr(selftest, 'exercise_product', None)), 'missing no-chat product acceptance')
        result = selftest.exercise_product()
        self.assertEqual(result['touch_zones'], ['head', 'cheek', 'body'])
        self.assertEqual(result['menu'], ['Settings', 'Quit'])
        self.assertEqual(result['drag_bubbles'], 1)
        self.assertEqual(result['network_attempts'], 0)
        self.assertEqual(result['audio_play_calls'], 0)
        self.assertEqual(result['persisted_volume'], 0.4)
        self.assertEqual(result['quit_code'], 0)

    def test_voice_assets_have_individual_approval_gate(self):
        """REVISED REQUIREMENT (documented, not a weakened pass).

        The historical S1 version of this test required ALL 11 WAV files to be present and
        hash-matching. That was an integrity check of the private candidate, not a decision to
        distribute: ten of the clips are `approved: false`. Under the public-release policy
        (full-engine/packaging/asset_policy.py, tests/test_public_assets.py) only the approved
        clip is physically shipped. The original test is preserved byte-exact in the private
        intake (legacy-tests/test_scripted_product.py). What is asserted now:
          * the manifest still lists all 11 entries with their honest approval/listening state;
          * every APPROVED entry has its audio present and matching its sha256;
          * every NOT approved entry has no audio path and no WAV on disk, and its private
            original hash is kept for traceability.
        """
        import json, hashlib
        from pathlib import Path
        note = Path(__file__).resolve().parents[1]/'full-engine/res/role/Draconia/note'
        manifest = json.loads((note/'manifest.json').read_text())
        self.assertEqual(manifest['voice'], 'Gemini Aoede')
        entries = [entry for pool in manifest['events'].values() for entry in pool]
        self.assertEqual(len(entries), 11)
        self.assertEqual([e['id'] for e in entries if e['approved']], ['head-01'])
        for entry in entries:
            if entry['approved']:
                self.assertEqual(hashlib.sha256((note/entry['audio']).read_bytes()).hexdigest(), entry['sha256'])
            else:
                self.assertIsNone(entry['audio'], entry['id'])
                self.assertFalse((note/'voice'/(entry['id'] + '.wav')).exists(), entry['id'])
                self.assertEqual(len(entry['private_original_sha256']), 64)
        self.assertEqual(sorted(p.name for p in (note/'voice').glob('*.wav')), ['head-01.wav'])


class QtProvenanceGate(unittest.TestCase):
    def test_exact_installed_qt_models_provenance(self):
        import importlib.util, tempfile, shutil
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('package_classifier', root/'package_scripted.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertTrue(callable(getattr(module, 'qt_models_inventory', None)), 'missing RECORD-verified Qt inventory')
        inventory = module.qt_models_inventory()
        self.assertGreater(len(inventory), 1)
        with tempfile.TemporaryDirectory(dir=root/'work/s1') as folder:
            folder = Path(folder)
            for name, item in inventory.items():
                with self.subTest(name=name):
                    source = Path(item['source'])
                    self.assertEqual(module.record(source)['sha256'], item['sha256'])
                    self.assertEqual(module.record(source)['bytes'], item['bytes'])
                    copied = folder/source.name
                    shutil.copy2(source, copied)
                    self.assertFalse(module.forbidden_artifact(name, copied, inventory))
                    copied.write_bytes(copied.read_bytes()+b'modified')
                    self.assertTrue(module.forbidden_artifact(name, copied, inventory))
            for name in ['_internal/PySide6/qml/QtQml/Models/weights.gguf', '_internal/PySide6/qml/QtQml/Models/weights.onnx', '_internal/PySide6/qml/QtQml/Models/weights.safetensors', '_internal/PySide6/qml/QtQml/Models/weights.pt', '_internal/PySide6/qml/QtQml/Models/weights.pth', '_internal/PySide6/qml/QtQml/Models/extra.dll', '_internal/models/plugin.dll', '../escape.dll', '/absolute.dll', 'C:/absolute.dll', '_internal/PySide6/qml/QtQml/Models/../modelsplugin.dll']:
                self.assertTrue(module.forbidden_artifact(name, folder/'missing', inventory), name)
            name, item = next(iter(inventory.items()))
            self.assertTrue(module.forbidden_artifact(name, folder/'missing', inventory))
            # Read-only installed source is never modified. Symlink gate independent of OS privilege.
            with patch.object(Path, 'is_symlink', return_value=True):
                self.assertTrue(module.forbidden_artifact(name, Path(item['source']), inventory))


class PackageArtifactGate(unittest.TestCase):
    def test_qt_item_models_plugin_is_not_inference_weights(self):
        import importlib.util
        from pathlib import Path
        spec=importlib.util.spec_from_file_location('package_scripted_gate',Path(__file__).resolve().parents[1]/'package_scripted.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertTrue(callable(getattr(module,'forbidden_artifact',None)), 'missing precise artifact classification')
        self.assertFalse(module.forbidden_artifact('_internal/PySide6/qml/QtQml/Models/modelsplugin.dll'))
        for name in ['models/weights.gguf','_internal/models/weights.bin','_internal/runtime/server.exe','_internal/ollama.exe','_internal/PySide6/qml/QtQml/Models/weights.gguf']:
            self.assertTrue(module.forbidden_artifact(name), name)
