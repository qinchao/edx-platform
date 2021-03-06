import unittest
import decimal
import ddt
from mock import patch
from django.conf import settings
from django.core.urlresolvers import reverse
from pytz import timezone
from datetime import datetime

from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase

from util.date_utils import get_time_display
from util.testing import UrlResetMixin
from embargo.test_utils import restrict_course
from xmodule.modulestore.tests.factories import CourseFactory
from course_modes.tests.factories import CourseModeFactory
from student.tests.factories import CourseEnrollmentFactory, UserFactory
from student.models import CourseEnrollment
from course_modes.models import CourseMode, Mode


@ddt.ddt
@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
class CourseModeViewTest(UrlResetMixin, ModuleStoreTestCase):
    @patch.dict(settings.FEATURES, {'MODE_CREATION_FOR_TESTING': True})
    def setUp(self):
        super(CourseModeViewTest, self).setUp('course_modes.urls')
        self.course = CourseFactory.create()
        self.user = UserFactory.create(username="Bob", email="bob@example.com", password="edx")
        self.client.login(username=self.user.username, password="edx")

    @unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
    @ddt.data(
        # is_active?, enrollment_mode, redirect?
        (True, 'verified', True),
        (True, 'honor', False),
        (True, 'audit', False),
        (False, 'verified', False),
        (False, 'honor', False),
        (False, 'audit', False),
        (False, None, False),
    )
    @ddt.unpack
    def test_redirect_to_dashboard(self, is_active, enrollment_mode, redirect):
        # Create the course modes
        for mode in ('audit', 'honor', 'verified'):
            CourseModeFactory(mode_slug=mode, course_id=self.course.id)

        # Enroll the user in the test course
        if enrollment_mode is not None:
            CourseEnrollmentFactory(
                is_active=is_active,
                mode=enrollment_mode,
                course_id=self.course.id,
                user=self.user
            )

        # Configure whether we're upgrading or not
        url = reverse('course_modes_choose', args=[unicode(self.course.id)])
        response = self.client.get(url)

        # Check whether we were correctly redirected
        if redirect:
            self.assertRedirects(response, reverse('dashboard'))
        else:
            self.assertEquals(response.status_code, 200)

    def test_no_id_redirect(self):
        # Create the course modes
        CourseModeFactory(mode_slug=CourseMode.NO_ID_PROFESSIONAL_MODE, course_id=self.course.id, min_price=100)

        # Enroll the user in the test course
        CourseEnrollmentFactory(
            is_active=False,
            mode=CourseMode.NO_ID_PROFESSIONAL_MODE,
            course_id=self.course.id,
            user=self.user
        )

        # Configure whether we're upgrading or not
        url = reverse('course_modes_choose', args=[unicode(self.course.id)])
        response = self.client.get(url)
        # Check whether we were correctly redirected
        start_flow_url = reverse('verify_student_start_flow', args=[unicode(self.course.id)])
        self.assertRedirects(response, start_flow_url)

    def test_no_enrollment(self):
        # Create the course modes
        for mode in ('audit', 'honor', 'verified'):
            CourseModeFactory(mode_slug=mode, course_id=self.course.id)

        # User visits the track selection page directly without ever enrolling
        url = reverse('course_modes_choose', args=[unicode(self.course.id)])
        response = self.client.get(url)

        self.assertEquals(response.status_code, 200)

    @ddt.data(
        '',
        '1,,2',
        '1, ,2',
        '1, 2, 3'
    )
    def test_suggested_prices(self, price_list):

        # Create the course modes
        for mode in ('audit', 'honor'):
            CourseModeFactory(mode_slug=mode, course_id=self.course.id)

        CourseModeFactory(
            mode_slug='verified',
            course_id=self.course.id,
            suggested_prices=price_list
        )

        # Enroll the user in the test course to emulate
        # automatic enrollment
        CourseEnrollmentFactory(
            is_active=True,
            course_id=self.course.id,
            user=self.user
        )

        # Verify that the prices render correctly
        response = self.client.get(
            reverse('course_modes_choose', args=[unicode(self.course.id)]),
            follow=False,
        )

        self.assertEquals(response.status_code, 200)
        # TODO: Fix it so that response.templates works w/ mako templates, and then assert
        # that the right template rendered

    @ddt.data(
        (['honor', 'verified', 'credit'], True),
        (['honor', 'verified'], False),
    )
    @ddt.unpack
    def test_credit_upsell_message(self, available_modes, show_upsell):
        # Create the course modes
        for mode in available_modes:
            CourseModeFactory(mode_slug=mode, course_id=self.course.id)

        # Check whether credit upsell is shown on the page
        # This should *only* be shown when a credit mode is available
        url = reverse('course_modes_choose', args=[unicode(self.course.id)])
        response = self.client.get(url)

        if show_upsell:
            self.assertContains(response, "Credit")
        else:
            self.assertNotContains(response, "Credit")

    @ddt.data('professional', 'no-id-professional')
    def test_professional_enrollment(self, mode):
        # The only course mode is professional ed
        CourseModeFactory(mode_slug=mode, course_id=self.course.id, min_price=1)

        # Go to the "choose your track" page
        choose_track_url = reverse('course_modes_choose', args=[unicode(self.course.id)])
        response = self.client.get(choose_track_url)

        # Since the only available track is professional ed, expect that
        # we're redirected immediately to the start of the payment flow.
        start_flow_url = reverse('verify_student_start_flow', args=[unicode(self.course.id)])
        self.assertRedirects(response, start_flow_url)

        # Now enroll in the course
        CourseEnrollmentFactory(
            user=self.user,
            is_active=True,
            mode=mode,
            course_id=unicode(self.course.id),
        )

        # Expect that this time we're redirected to the dashboard (since we're already registered)
        response = self.client.get(choose_track_url)
        self.assertRedirects(response, reverse('dashboard'))

    # Mapping of course modes to the POST parameters sent
    # when the user chooses that mode.
    POST_PARAMS_FOR_COURSE_MODE = {
        'honor': {'honor_mode': True},
        'verified': {'verified_mode': True, 'contribution': '1.23'},
        'unsupported': {'unsupported_mode': True},
    }

    @ddt.data(
        ('honor', 'dashboard'),
        ('verified', 'start-flow'),
    )
    @ddt.unpack
    def test_choose_mode_redirect(self, course_mode, expected_redirect):
        # Create the course modes
        for mode in ('audit', 'honor', 'verified'):
            min_price = 0 if course_mode in ["honor", "audit"] else 1
            CourseModeFactory(mode_slug=mode, course_id=self.course.id, min_price=min_price)

        # Choose the mode (POST request)
        choose_track_url = reverse('course_modes_choose', args=[unicode(self.course.id)])
        response = self.client.post(choose_track_url, self.POST_PARAMS_FOR_COURSE_MODE[course_mode])

        # Verify the redirect
        if expected_redirect == 'dashboard':
            redirect_url = reverse('dashboard')
        elif expected_redirect == 'start-flow':
            redirect_url = reverse(
                'verify_student_start_flow',
                kwargs={'course_id': unicode(self.course.id)}
            )
        else:
            self.fail("Must provide a valid redirect URL name")

        self.assertRedirects(response, redirect_url)

    def test_remember_donation_for_course(self):
        # Create the course modes
        for mode in ('honor', 'verified'):
            CourseModeFactory(mode_slug=mode, course_id=self.course.id)

        # Choose the mode (POST request)
        choose_track_url = reverse('course_modes_choose', args=[unicode(self.course.id)])
        self.client.post(choose_track_url, self.POST_PARAMS_FOR_COURSE_MODE['verified'])

        # Expect that the contribution amount is stored in the user's session
        self.assertIn('donation_for_course', self.client.session)
        self.assertIn(unicode(self.course.id), self.client.session['donation_for_course'])

        actual_amount = self.client.session['donation_for_course'][unicode(self.course.id)]
        expected_amount = decimal.Decimal(self.POST_PARAMS_FOR_COURSE_MODE['verified']['contribution'])
        self.assertEqual(actual_amount, expected_amount)

    def test_successful_honor_enrollment(self):
        # Create the course modes
        for mode in ('honor', 'verified'):
            CourseModeFactory(mode_slug=mode, course_id=self.course.id)

        # Enroll the user in the default mode (honor) to emulate
        # automatic enrollment
        params = {
            'enrollment_action': 'enroll',
            'course_id': unicode(self.course.id)
        }
        self.client.post(reverse('change_enrollment'), params)

        # Explicitly select the honor mode (POST request)
        choose_track_url = reverse('course_modes_choose', args=[unicode(self.course.id)])
        self.client.post(choose_track_url, self.POST_PARAMS_FOR_COURSE_MODE['honor'])

        # Verify that the user's enrollment remains unchanged
        mode, is_active = CourseEnrollment.enrollment_mode_for_user(self.user, self.course.id)
        self.assertEqual(mode, 'honor')
        self.assertEqual(is_active, True)

    def test_unsupported_enrollment_mode_failure(self):
        # Create the supported course modes
        for mode in ('honor', 'verified'):
            CourseModeFactory(mode_slug=mode, course_id=self.course.id)

        # Choose an unsupported mode (POST request)
        choose_track_url = reverse('course_modes_choose', args=[unicode(self.course.id)])
        response = self.client.post(choose_track_url, self.POST_PARAMS_FOR_COURSE_MODE['unsupported'])

        self.assertEqual(400, response.status_code)

    @unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
    def test_default_mode_creation(self):
        # Hit the mode creation endpoint with no querystring params, to create an honor mode
        url = reverse('create_mode', args=[unicode(self.course.id)])
        response = self.client.get(url)

        self.assertEquals(response.status_code, 200)

        expected_mode = [Mode(u'honor', u'Honor Code Certificate', 0, '', 'usd', None, None, None)]
        course_mode = CourseMode.modes_for_course(self.course.id)

        self.assertEquals(course_mode, expected_mode)

    @unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
    @ddt.data(
        (u'verified', u'Verified Certificate', 10, '10,20,30', 'usd'),
        (u'professional', u'Professional Education', 100, '100,200', 'usd'),
    )
    @ddt.unpack
    def test_verified_mode_creation(self, mode_slug, mode_display_name, min_price, suggested_prices, currency):
        parameters = {}
        parameters['mode_slug'] = mode_slug
        parameters['mode_display_name'] = mode_display_name
        parameters['min_price'] = min_price
        parameters['suggested_prices'] = suggested_prices
        parameters['currency'] = currency

        url = reverse('create_mode', args=[unicode(self.course.id)])
        response = self.client.get(url, parameters)

        self.assertEquals(response.status_code, 200)

        expected_mode = [Mode(mode_slug, mode_display_name, min_price, suggested_prices, currency, None, None, None)]
        course_mode = CourseMode.modes_for_course(self.course.id)

        self.assertEquals(course_mode, expected_mode)

    @unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
    def test_multiple_mode_creation(self):
        # Create an honor mode
        base_url = reverse('create_mode', args=[unicode(self.course.id)])
        self.client.get(base_url)

        # Excluding the currency parameter implicitly tests the mode creation endpoint's ability to
        # use default values when parameters are partially missing.
        parameters = {}
        parameters['mode_slug'] = u'verified'
        parameters['mode_display_name'] = u'Verified Certificate'
        parameters['min_price'] = 10
        parameters['suggested_prices'] = '10,20'

        # Create a verified mode
        url = reverse('create_mode', args=[unicode(self.course.id)])
        self.client.get(url, parameters)

        honor_mode = Mode(u'honor', u'Honor Code Certificate', 0, '', 'usd', None, None, None)
        verified_mode = Mode(u'verified', u'Verified Certificate', 10, '10,20', 'usd', None, None, None)
        expected_modes = [honor_mode, verified_mode]
        course_modes = CourseMode.modes_for_course(self.course.id)

        self.assertEquals(course_modes, expected_modes)


@unittest.skipUnless(settings.ROOT_URLCONF == 'lms.urls', 'Test only valid in lms')
class TrackSelectionEmbargoTest(UrlResetMixin, ModuleStoreTestCase):
    """Test embargo restrictions on the track selection page. """

    @patch.dict(settings.FEATURES, {'EMBARGO': True})
    def setUp(self):
        super(TrackSelectionEmbargoTest, self).setUp('embargo')

        # Create a course and course modes
        self.course = CourseFactory.create()
        CourseModeFactory(mode_slug='honor', course_id=self.course.id)
        CourseModeFactory(mode_slug='verified', course_id=self.course.id, min_price=10)

        # Create a user and log in
        self.user = UserFactory.create(username="Bob", email="bob@example.com", password="edx")
        self.client.login(username=self.user.username, password="edx")

        # Construct the URL for the track selection page
        self.url = reverse('course_modes_choose', args=[unicode(self.course.id)])

    @patch.dict(settings.FEATURES, {'EMBARGO': True})
    def test_embargo_restrict(self):
        with restrict_course(self.course.id) as redirect_url:
            response = self.client.get(self.url)
            self.assertRedirects(response, redirect_url)

    def test_embargo_allow(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


class AdminCourseModePageTest(ModuleStoreTestCase):
    """Test the django admin course mode form saving data in db without any conversion
     properly converts the tzinfo from default zone to utc
    """

    def test_save_valid_data(self):
        user = UserFactory.create(is_staff=True, is_superuser=True)
        user.save()
        course = CourseFactory.create()
        expiration = datetime(2015, 10, 20, 1, 10, 23, tzinfo=timezone(settings.TIME_ZONE))

        data = {
            'course_id': unicode(course.id),
            'mode_slug': 'professional',
            'mode_display_name': 'professional',
            'min_price': 10,
            'currency': 'usd',
            'expiration_datetime_0': expiration.date(),  # due to django admin datetime widget passing as seperate vals
            'expiration_datetime_1': expiration.time(),

        }

        self.client.login(username=user.username, password='test')

        # creating new course mode from django admin page
        response = self.client.post(reverse('admin:course_modes_coursemode_add'), data=data)
        self.assertRedirects(response, reverse('admin:course_modes_coursemode_changelist'))

        # verifying that datetime is appearing on list page
        response = self.client.get(reverse('admin:course_modes_coursemode_changelist'))
        self.assertContains(response, get_time_display(expiration, '%B %d, %Y, %H:%M  %p'))

        # verifiying the on edit page datetime value appearing without any modifications
        resp = self.client.get(reverse('admin:course_modes_coursemode_change', args=(1,)))
        self.assertContains(resp, expiration.date())
        self.assertContains(resp, expiration.time())

        # checking the values in db. comparing values without tzinfo
        course_mode = CourseMode.objects.get(pk=1)
        self.assertEqual(course_mode.expiration_datetime.replace(tzinfo=None), expiration.replace(tzinfo=None))
