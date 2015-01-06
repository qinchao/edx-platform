"""Data Aggregation Layer for the Course About API.
This is responsible for combining data from the following resources:
* CourseDescriptor
* CourseAboutDescriptor
"""
import logging
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey
from course_about.serializers import serialize_content
from course_about.errors import CourseNotFoundError
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import ItemNotFoundError
from util.memcache import safe_key
from django.core.cache import get_cache
from django.conf import settings


log = logging.getLogger(__name__)

ABOUT_ATTRIBUTES = [
    'effort',
]


def get_course_about_details(course_id):  # pylint: disable=unused-argument
    """
    Return course information for a given course id.
    First its checks the default cache for given course id if its exists then returns
    the course otherwise it get the course from module store and set the cache.
    if course has version then use that for making cache-key.
    if version is None then set the expiry timeout for cache key.

    Args:
        course_id(str) : The course id to retrieve course information for.

    Returns:
        Serializable dictionary of the Course About Information.

    Raises:
        CourseNotFoundError
    """
    try:
        cache = get_cache("default")
        course_key = CourseKey.from_string(course_id)
        course_version = _get_course_version(course_key)
        key_prefix = getattr(settings, 'COURSE_INFO_API_CACHE_PREFIX', '')
        if course_version:
            cache_key = safe_key(course_id, key_prefix, course_version)
        else:
            cache_key = safe_key(course_id, key_prefix, '')
        course_info = cache.get(cache_key)
        if not course_info:
            course_descriptor = modulestore().get_course(course_key, remove_version=False, remove_branch=False)
            if course_descriptor is None:
                raise CourseNotFoundError("course not found")
            about_descriptor = {}
            for attribute in ABOUT_ATTRIBUTES:
                about_descriptor[attribute] = _fetch_course_detail(course_key, attribute)
            course_info = serialize_content(course_descriptor=course_descriptor, about_descriptor=about_descriptor)
            if course_version:
                cache.set(cache_key, course_info, None)
            else:
                time_out = getattr(settings, 'COURSE_INFO_API_CACHE_TIME_OUT', 300)
                cache.set(cache_key, course_info, time_out)
    except InvalidKeyError as err:
        raise CourseNotFoundError(err.message)
    return course_info


def _fetch_course_detail(course_key, attribute):
    """
    Fetch the course about attribute for the given course's attribute from persistence and return its value.
    """
    usage_key = course_key.make_usage_key('about', attribute)
    try:
        value = modulestore().get_item(usage_key).data
    except ItemNotFoundError:
        value = None
    return value


def _get_course_version(course_key):
    """
    Return the version of course
    """
    #TODO User proper way to return the version of key
    return course_key.version_guid