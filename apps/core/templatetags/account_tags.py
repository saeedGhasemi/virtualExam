"""Account helpers for templates: the signed-in user's password state (never the password itself)."""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def password_state(context):
    """{'changed_at': aware datetime or None, 'required': bool} for request.user, read from `profiles` (migration 0062)."""
    from ..views import erd_profile_for_user  # views imports this package's siblings; keep the import lazy

    request = context.get('request')
    profile = erd_profile_for_user(getattr(request, 'user', None)) if request else None
    profile = profile or {}
    return {'changed_at': profile.get('password_changed_at'), 'required': bool(profile.get('password_change_required'))}


@register.inclusion_tag('super_admin/_password_card.html', takes_context=True)
def admin_password_card(context, kind, user_id):
    """The «رمز عبور» card a super admin sees on a teacher / student / manager edit page."""
    from ..views import admin_password_card_context

    request = context['request']
    return {**admin_password_card_context(request, kind, user_id), 'csrf_token': context.get('csrf_token'), 'kind': kind}
