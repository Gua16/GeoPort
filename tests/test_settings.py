from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from settings import SettingsStore


class SettingsTests(unittest.TestCase):
    def test_history_mru_limit_dedup_restart_and_no_radius_update(self):
        for i in range(7):
            self.set_history_point(i)
        expected = [{'lat':i,'lng':i} for i in [6,5,4,3,2]]
        self.assertEqual(self.store.read()['base_history'], expected)
        self.set_history_point(4)
        self.assertEqual(self.store.read()['base_history'], [expected[2],expected[0],expected[1],expected[3],expected[4]])
        before = self.store.read()['base_history']
        self.store.update(random_radius_m=500)
        self.assertEqual(SettingsStore(self.path).read()['base_history'], before)

    def set_history_point(self, i):
        self.store.update(base_location={'lat':i,'lng':i})

    def test_history_failed_save_does_not_move_or_append(self):
        self.set_history_point(1)
        before = self.store.read()
        with patch('settings.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.set_history_point(2)
        self.assertEqual(self.store.read(), before)
        self.assertEqual(SettingsStore(self.path).read(), before)

    def test_legacy_base_is_imported_as_first_history_entry(self):
        self.path.write_text('{"schema_version":1,"base_location":{"lat":1,"lng":2}}')
        self.assertEqual(SettingsStore(self.path).read()['base_history'], [{'lat':1,'lng':2}])
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'config.json'
        self.store = SettingsStore(self.path)
    def tearDown(self): self.temp.cleanup()

    def test_persistence_and_no_shared_mutable_settings(self):
        base = {'lat':23.1291,'lng':113.2644}
        self.store.update(base_location=base,random_radius_m=500)
        base['lat'] = 0
        restored = SettingsStore(self.path).read()
        self.assertEqual(restored['base_location']['lat'],23.1291)
        self.assertEqual(restored['random_radius_m'],500)
        snapshot = self.store.read()
        snapshot['base_location']['lat'] = 1
        self.assertEqual(self.store.read(),restored)

    def test_corrupt_file_preserved_until_explicit_save(self):
        for contents in ['{broken', '[]', '{"schema_version":2}', '{"schema_version":1,"base_location":[]}']:
            self.path.write_text(contents)
            store = SettingsStore(self.path)
            self.assertIsNotNone(store.warning)
            self.assertIsNone(store.read()['base_location'])
            self.assertEqual(self.path.read_text(),contents)
        store.update(random_radius_m=200)
        self.assertIsNone(store.warning)
        self.assertEqual(SettingsStore(self.path).read()['random_radius_m'],200)

    def test_failed_atomic_write_preserves_file_and_memory(self):
        before = self.store.update(random_radius_m=400)
        contents = self.path.read_text()
        with patch('settings.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.store.update(random_radius_m=500)
        self.assertEqual(self.path.read_text(),contents)
        self.assertEqual(self.store.read(),before)
        self.assertEqual(list(self.path.parent.glob('.config-*')),[])

    def test_invalid_save_preserves_configuration(self):
        for changes in [dict(random_radius_m=-1),dict(ui_mode='other'),dict(base_location={'lat':90.1,'lng':0})]:
            with self.assertRaises(ValueError): self.store.update(**changes)
        self.assertFalse(self.path.exists())

    def test_sudo_save_preserves_configuration_directory_owner(self):
        owner = self.path.parent.stat()
        with patch.dict('os.environ', {'SUDO_UID': str(owner.st_uid)}), \
             patch('settings.os.geteuid', return_value=0), patch('settings.os.chown') as chown:
            self.store.update(random_radius_m=450)
        if owner.st_uid != 0:
            chown.assert_called_once()
            self.assertEqual(chown.call_args.args[1:], (owner.st_uid, owner.st_gid))

    def test_invalid_sudo_identity_cannot_change_file_ownership(self):
        with patch.dict('os.environ', {'SUDO_UID': 'not-a-user-id'}), \
             patch('settings.os.geteuid', return_value=0), patch('settings.os.chown') as chown:
            self.store.update(random_radius_m=450)
        chown.assert_not_called()
