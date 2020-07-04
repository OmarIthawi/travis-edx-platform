"""
Helpers for testing retirement functionality
"""
import datetime

import pytest
import pytz
from django.test import TestCase
from social_django.models import UserSocialAuth

from enrollment import api
from openedx.core.djangoapps.user_api.models import (
    RetirementState,
    UserRetirementStatus
)
from student.models import (
    get_retired_username_by_username,
    get_retired_email_by_email,
    Registration,
)
from student.tests.factories import UserFactory

from ..views import AccountRetirementView


@pytest.fixture
def setup_retirement_states(scope="module"):  # pylint: disable=unused-argument
    """
    Create basic states that mimic the retirement process.
    """
    default_states = [
        ('PENDING', 1, False, True),
        ('LOCKING_ACCOUNT', 20, False, False),
        ('LOCKING_COMPLETE', 30, False, False),
        ('RETIRING_CREDENTIALS', 40, False, False),
        ('CREDENTIALS_COMPLETE', 50, False, False),
        ('RETIRING_ECOM', 60, False, False),
        ('ECOM_COMPLETE', 70, False, False),
        ('RETIRING_FORUMS', 80, False, False),
        ('FORUMS_COMPLETE', 90, False, False),
        ('RETIRING_EMAIL_LISTS', 100, False, False),
        ('EMAIL_LISTS_COMPLETE', 110, False, False),
        ('RETIRING_ENROLLMENTS', 120, False, False),
        ('ENROLLMENTS_COMPLETE', 130, False, False),
        ('RETIRING_NOTES', 140, False, False),
        ('NOTES_COMPLETE', 150, False, False),
        ('RETIRING_LMS', 160, False, False),
        ('LMS_COMPLETE', 170, False, False),
        ('ADDING_TO_PARTNER_QUEUE', 180, False, False),
        ('PARTNER_QUEUE_COMPLETE', 190, False, False),
        ('ERRORED', 200, True, True),
        ('ABORTED', 210, True, True),
        ('COMPLETE', 220, True, True),
    ]

    for name, ex, dead, req in default_states:
        RetirementState.objects.create(
            state_name=name,
            state_execution_order=ex,
            is_dead_end_state=dead,
            required=req
        )

    yield

    RetirementState.objects.all().delete()


def create_retirement_status(state=None, create_datetime=None):
    """
    Helper method to create a RetirementStatus with useful defaults.
    Assumes that retirement states have been setup before calling.
    """
    if create_datetime is None:
        create_datetime = datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=8)

    user = UserFactory()
    retirement = UserRetirementStatus.create_retirement(user)
    if state:
        retirement.current_state = state
        retirement.last_state = state
    retirement.created = create_datetime
    retirement.modified = create_datetime
    retirement.save()
    return retirement


def _fake_logged_out_user(user):
    # Simulate the initial logout retirement endpoint.
    user.username = get_retired_username_by_username(user.username)
    user.email = get_retired_email_by_email(user.email)
    user.set_unusable_password()
    user.save()


@pytest.fixture
def logged_out_retirement_request():
    """
    Returns a UserRetirementStatus test fixture object that has been logged out and email-changed,
    which is the first step which happens to a user being added to the retirement queue.
    """
    retirement = create_retirement_status()
    _fake_logged_out_user(retirement.user)
    return retirement


@pytest.mark.usefixtures("setup_retirement_states")
class RetirementTestCase(TestCase):
    """
    Test case with a helper methods for retirement
    """
    def _retirement_to_dict(self, retirement, all_fields=False):
        """
        Return a dict format of this model to a consistent format for serialization, removing the long text field
        `responses` for performance reasons.
        """
        retirement_dict = {
            u'id': retirement.id,
            u'user': {
                u'id': retirement.user.id,
                u'username': retirement.user.username,
                u'email': retirement.user.email,
                u'profile': {
                    u'id': retirement.user.profile.id,
                    u'name': retirement.user.profile.name
                },
            },
            u'original_username': retirement.original_username,
            u'original_email': retirement.original_email,
            u'original_name': retirement.original_name,
            u'retired_username': retirement.retired_username,
            u'retired_email': retirement.retired_email,
            u'current_state': {
                u'id': retirement.current_state.id,
                u'state_name': retirement.current_state.state_name,
                u'state_execution_order': retirement.current_state.state_execution_order,
            },
            u'last_state': {
                u'id': retirement.last_state.id,
                u'state_name': retirement.last_state.state_name,
                u'state_execution_order': retirement.last_state.state_execution_order,
            },
            u'created': retirement.created,
            u'modified': retirement.modified
        }

        if all_fields:
            retirement_dict['responses'] = retirement.responses

        return retirement_dict

    def _create_users_all_states(self):
        return [create_retirement_status(state) for state in RetirementState.objects.all()]

    def _get_non_dead_end_states(self):
        return [state for state in RetirementState.objects.filter(is_dead_end_state=False)]

    def _get_dead_end_states(self):
        return [state for state in RetirementState.objects.filter(is_dead_end_state=True)]


class RetirementTestUserMixin(object):
    """
    Create a test user for retirement
    """
    def setUp(self):
        self.test_password = 'password'
        self.test_user = UserFactory(password=self.test_password)
        UserSocialAuth.objects.create(
            user=self.test_user,
            provider='some_provider_name',
            uid='xyz@gmail.com'
        )
        UserSocialAuth.objects.create(
            user=self.test_user,
            provider='some_other_provider_name',
            uid='xyz@gmail.com'
        )

        Registration().register(self.test_user)


def fake_completed_retirement(user):
    """
    Makes an attempt to put user for the given user into a "COMPLETED"
    retirement state by faking important parts of retirement.

    Use to test idempotency for retirement API calls. Since there are many
    configurable retirement steps this is only a "best guess" and may need
    additional changes added to more accurately reflect post-retirement state.
    """
    # Deactivate / logout and hash username & email
    UserSocialAuth.objects.filter(user_id=user.id).delete()
    _fake_logged_out_user(user)
    user.first_name = ''
    user.last_name = ''
    user.is_active = False
    user.save()

    # Clear profile
    AccountRetirementView.clear_pii_from_userprofile(user)

    # Unenroll from all courses
    api.unenroll_user_from_all_courses(user.username)
