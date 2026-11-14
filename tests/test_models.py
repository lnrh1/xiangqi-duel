import os
import stat
import tempfile
import unittest

from xiangqi_duel.models import ModelRegistry, RegistryError


class ModelRegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "models.json")
        self.registry = ModelRegistry(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_list_remove_persist(self):
        entry = self.registry.add("engine", "alpha-beta", "", "", "离线引擎")
        self.assertTrue(entry["id"].startswith("m-"))
        public = self.registry.public()
        self.assertEqual(len(public), 1)
        self.assertNotIn("api_key", public[0])
        self.assertFalse(public[0]["has_key"])

        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, 0o600)

        reloaded = ModelRegistry(self.path)
        self.assertEqual(len(reloaded.entries()), 1)
        self.assertEqual(reloaded.entries()[0]["model"], "alpha-beta")

        self.registry.remove(entry["id"])
        self.assertEqual(len(ModelRegistry(self.path).entries()), 0)

    def test_unknown_provider_rejected(self):
        with self.assertRaises(RegistryError):
            self.registry.add("not-a-provider", "x")

    def test_custom_base_url(self):
        entry = self.registry.add("custom", "my-model", "secret", "http://localhost:1234/v1", "本地")
        config = self.registry.config_for(entry["id"])
        self.assertEqual(config.base_url, "http://localhost:1234/v1")
        self.assertEqual(config.api_key, "secret")
        self.assertEqual(config.model, "my-model")

    def test_default_model_filled_from_preset(self):
        entry = self.registry.add("deepseek", "", "key")
        self.assertEqual(entry["model"], "deepseek-chat")

    def test_remove_missing(self):
        with self.assertRaises(RegistryError):
            self.registry.remove("m-missing")
