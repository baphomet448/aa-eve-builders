"""
Example Test
"""

# Django
from django.test import TestCase


class TestEveBuilders(TestCase):
    """
    TestEveBuilders
    """

    @classmethod
    def setUpClass(cls) -> None:
        """
        Test setup
        :return:
        :rtype:
        """

        super().setUpClass()

    def test_example(self):
        """
        Dummy test function
        :return:
        :rtype:
        """

        self.assertEqual(True, True)
