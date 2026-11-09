"""Publication guards reject secrets and host data without needing credentials."""
import unittest

from tools.check_public_tree import json_issues, scan, text_issues


class PublicRepositoryTests(unittest.TestCase):
    def test_sensitive_patterns_are_rejected_and_public_urls_are_allowed(self):
        self.assertTrue(text_issues('gh' + 'p_' + 'X' * 36))
        self.assertTrue(text_issues(chr(67) + ':/' + 'Users/' + 'sample/file.json'))
        self.assertTrue(text_issues('research' + '-output/' + 'private.json'))
        self.assertFalse(text_issues('https://yourbot.gg/docs/developers'))

    def test_conversation_and_host_metadata_cannot_enter_data(self):
        self.assertTrue(json_issues({'nested': [{'user_approval': {'quote': 'synthetic'}}]}))
        self.assertFalse(json_issues({'asset_id': '0' * 16, 'quality': 'native_localization'}))

    def test_actual_public_tree_has_no_rejected_content(self):
        result = scan()
        self.assertTrue(result['ready'], result['issues'])


if __name__ == '__main__':
    unittest.main()
