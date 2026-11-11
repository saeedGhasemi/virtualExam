"""Each account's own «تنظیمات ظاهری» (apps/core/appearance.py, card: partials/my_appearance.html).

On the student and teacher settings pages the card's fields go with that page's «ذخیره تغییرات»
(save_posted_appearance in their views). On the admin / academic manager «پروفایل من» → «ظاهر من» tab the card is
its own form and posts here.
"""
from django.contrib import messages
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .appearance import save_posted_appearance
from .views import erd_role_required, log_activity


@require_POST
@erd_role_required('admin', 'academic_manager', 'teacher', 'student')
def my_appearance_save(request):
    if save_posted_appearance(request.erd_profile_id, request.POST):
        log_activity(request.user, 'appearance_updated', 'تغییر تنظیمات ظاهری حساب', request)
        messages.success(request, 'تنظیمات ظاهری ذخیره شد.')
    target = request.POST.get('next') or ''
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = ''
    return redirect(target or 'core:profile')
