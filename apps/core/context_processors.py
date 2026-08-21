from django.db import connection


ROLE_LABELS = {
    'admin': 'مدیر سامانه',
    'academic_manager': 'مدیر آموزشی',
    'teacher': 'استاد',
    'student': 'دانشجو',
}


def panel_user(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}

    profile = getattr(request, '_panel_profile_info', None)
    roles = [profile.get('role')] if profile and profile.get('role') else []
    if profile:
        return {
            'panel_avatar_url': profile.get('avatar_url') or '',
            'panel_display_name': profile.get('full_name') or profile.get('username') or user.get_username(),
            'panel_role_label': ROLE_LABELS.get(roles[0], roles[0]) if roles else '',
        }

    profile = None
    roles = []
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, full_name, username, email, avatar_url
            FROM profiles
            WHERE email = %s OR username = %s
            LIMIT 1
            """,
            [getattr(user, 'email', '') or '', getattr(user, 'username', '') or ''],
        )
        columns = [column[0] for column in cursor.description]
        row = cursor.fetchone()
        if row:
            profile = dict(zip(columns, row))
            cursor.execute("SELECT role FROM user_roles WHERE user_id = %s ORDER BY created_at", [profile['id']])
            roles = [item[0] for item in cursor.fetchall()]

    if profile:
        return {
            'panel_avatar_url': profile.get('avatar_url') or '',
            'panel_display_name': profile.get('full_name') or profile.get('username') or user.get_username(),
            'panel_role_label': ROLE_LABELS.get(roles[0], roles[0]) if roles else '',
        }

    avatar_url = ''
    user_profile = getattr(user, 'profile', None)
    profile_image = getattr(user_profile, 'profile_image', None)
    if profile_image:
        try:
            avatar_url = profile_image.url
        except ValueError:
            avatar_url = ''
    return {
        'panel_avatar_url': avatar_url,
        'panel_display_name': user.get_full_name() or user.get_username(),
        'panel_role_label': '',
    }
