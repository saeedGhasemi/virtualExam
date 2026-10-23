"""Rich text stored as a Quill Delta, rendered to HTML on the server.

User HTML is never accepted or parsed: the editor posts its Delta (JSON), we keep only plain-text
inserts plus a fixed set of formats, and build HTML ourselves with every text fragment escaped.
That makes the output safe by construction without an HTML sanitizer dependency.
"""
import json
import logging
from html import escape

logger = logging.getLogger(__name__)

MAX_OPS = 3000
INLINE_FORMATS = (('bold', 'strong'), ('italic', 'em'), ('underline', 'u'))
ALLOWED_HEADERS = {1, 2, 3}
ALLOWED_LISTS = {'ordered': 'ol', 'bullet': 'ul'}
ALLOWED_ALIGNS = {'center', 'right', 'left', 'justify'}
SAFE_LINK_PREFIXES = ('http://', 'https://', 'mailto:')


def clean_delta(raw) -> dict:
    """Parse posted Delta JSON and keep only text inserts with whitelisted attributes."""
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw or '{}')
        except (TypeError, ValueError):
            logger.warning('Rejected unparseable rich text payload')
            return {'ops': []}
    ops = data.get('ops') if isinstance(data, dict) else None
    if not isinstance(ops, list):
        return {'ops': []}
    cleaned = []
    for op in ops[:MAX_OPS]:
        if not isinstance(op, dict) or not isinstance(op.get('insert'), str):
            continue  # embeds (images, formulas, …) are not allowed
        attributes = op.get('attributes') if isinstance(op.get('attributes'), dict) else {}
        kept = {name: True for name, _tag in INLINE_FORMATS if attributes.get(name) is True}
        link = attributes.get('link')
        if isinstance(link, str) and link.strip().lower().startswith(SAFE_LINK_PREFIXES):
            kept['link'] = link.strip()
        if attributes.get('header') in ALLOWED_HEADERS:
            kept['header'] = attributes['header']
        if attributes.get('list') in ALLOWED_LISTS:
            kept['list'] = attributes['list']
        if attributes.get('align') in ALLOWED_ALIGNS:
            kept['align'] = attributes['align']
        cleaned.append({'insert': op['insert'], 'attributes': kept} if kept else {'insert': op['insert']})
    return {'ops': cleaned}


def delta_text(delta: dict) -> str:
    """Plain text of a Delta (used for length limits and empty checks)."""
    return ''.join(op['insert'] for op in (delta or {}).get('ops', []) if isinstance(op.get('insert'), str))


def delta_length(delta: dict) -> int:
    return len(delta_text(delta).strip())


def _inline_html(text: str, attributes: dict) -> str:
    html = escape(text).replace('\n', '')
    for name, tag in INLINE_FORMATS:
        if attributes.get(name):
            html = f'<{tag}>{html}</{tag}>'
    if attributes.get('link'):
        html = f'<a href="{escape(attributes["link"], quote=True)}" target="_blank" rel="noopener noreferrer">{html}</a>'
    return html


def delta_to_html(delta: dict) -> str:
    """Render a cleaned Delta to HTML. Re-cleans first so stored data is never trusted blindly."""
    delta = clean_delta(delta)
    lines, current = [], []
    for op in delta['ops']:
        attributes = op.get('attributes', {})
        parts = op['insert'].split('\n')
        for index, part in enumerate(parts):
            if part:
                current.append(_inline_html(part, attributes))
            if index < len(parts) - 1:  # a newline ends the line; its attributes format the block
                lines.append((''.join(current), attributes))
                current = []
    if current:
        lines.append((''.join(current), {}))

    html, open_list = [], None
    for content, block in lines:
        list_tag = ALLOWED_LISTS.get(block.get('list'))
        if open_list and open_list != list_tag:
            html.append(f'</{open_list}>')
            open_list = None
        style = f' style="text-align:{block["align"]}"' if block.get('align') in ALLOWED_ALIGNS else ''
        if list_tag:
            if not open_list:
                html.append(f'<{list_tag}>')
                open_list = list_tag
            html.append(f'<li{style}>{content}</li>')
        elif block.get('header') in ALLOWED_HEADERS:
            level = block['header'] + 2  # h3–h5 so content never outranks the page headings
            html.append(f'<h{level}{style}>{content}</h{level}>')
        else:
            html.append(f'<p{style}>{content or "<br>"}</p>')
    if open_list:
        html.append(f'</{open_list}>')
    return ''.join(html)
