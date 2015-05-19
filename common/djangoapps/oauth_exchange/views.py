"""
Views to support third-party to first-party OAuth 2.0 access token exchange
"""
from django.conf import settings
from django.contrib.auth import login
import django.contrib.auth as auth
from django.contrib.auth.models import User
from django.http import HttpResponse, HttpResponseNotFound
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from provider import constants
from provider.oauth2.views import AccessTokenView as AccessTokenView
from rest_framework import permissions
from rest_framework.views import APIView
import social.apps.django_app.utils as social_utils

from oauth_exchange.forms import AccessTokenExchangeForm
from openedx.core.lib.api.authentication import OAuth2AuthenticationAllowInactiveUser


class AccessTokenExchangeView(AccessTokenView):
    """View for access token exchange"""
    @method_decorator(csrf_exempt)
    @method_decorator(social_utils.strategy("social:complete"))
    def dispatch(self, *args, **kwargs):
        return super(AccessTokenExchangeView, self).dispatch(*args, **kwargs)

    def get(self, request, _backend):
        return super(AccessTokenExchangeView, self).get(request)

    def post(self, request, _backend):
        form = AccessTokenExchangeForm(request=request, data=request.POST)
        if not form.is_valid():
            return self.error_response(form.errors)

        user = form.cleaned_data["user"]
        scope = form.cleaned_data["scope"]
        client = form.cleaned_data["client"]

        if constants.SINGLE_ACCESS_TOKEN:
            edx_access_token = self.get_access_token(request, user, scope, client)
        else:
            edx_access_token = self.create_access_token(request, user, scope, client)

        return self.access_token_response(edx_access_token)


class SessionCookieExchangeView(APIView):
    """
    View for exchanging an access token for session cookies
    """
    authentication_classes = (OAuth2AuthenticationAllowInactiveUser,)
    permission_classes = (permissions.IsAuthenticated,)

    @method_decorator(csrf_exempt)
    def get(self, request):
        if request.user and isinstance(request.user, User):
            request.user.backend = get_backend_for_user(request.user)
            login(request, request.user)
            return HttpResponse(status=204)
        else:
            return HttpResponseNotFound()


def get_backend_for_user(user):
    for backend_path in settings.AUTHENTICATION_BACKENDS:
        backend = auth.load_backend(backend_path)
        if backend.get_user(user.id):
            return backend
    return None

