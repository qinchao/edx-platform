"""
Accessibility tests for Studio Library pages.
"""
from ..tests.studio.base_studio_test import StudioLibraryTest
from ..pages.studio.library import LibraryEditPage


class StudioLibraryAxsTest(StudioLibraryTest):
    """
    Base class to test Studio pages accessibility.
    """

    def test_lib_edit_page_axs(self):
        """
        Check accessibility of LibraryEditPage.
        """
        lib_page = LibraryEditPage(self.browser, self.library_key)
        lib_page.visit()
        lib_page.wait_until_ready()
        lib_page._check_for_accessibility_errors()
