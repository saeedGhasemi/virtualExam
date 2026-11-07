"""«ورود گروهی سؤالات» from a Word (.docx) file — standard library only (a .docx is a zip of XML parts).

The teacher types the questions the way an exam paper is usually written, every question type of the builder:

    1- پایتخت ایران کدام است؟
    الف) تبریز      ب) تهران *      ج) شیراز      د) مشهد
    بارم: 1

`read_docx_questions` returns, per question, the same POST fields the question builder form sends (so the view
checks and saves them with the builder's own code) plus the pictures/files to store for it:
- single / multi / true_false: options «الف)» «1)» «a)» (one per line or several on a line, bullets, a grid table);
  the correct one by *, «(صحیح)», «پاسخ: ب», an answer key at the end («کلید: 1-ب 2-ج») or formatting (highlight…).
- short_answer / numeric / true_false / essay: no options, told apart by the «پاسخ:» line (a number → numeric).
- fill_blank: «[تهران]» in the text, or blanks («……», «____», «[1]») with «پاسخ: …» / «جای خالی 1: …» lines.
- matching: «ایران = تهران» lines (or → ←) or a two-column table. ordering: options + «ترتیب صحیح:».
- matrix: a table, first row = column titles, ✓ / * in the correct cells.
- image_label: a picture + «نشانه 1: قلب (30، 40)» lines (x, y in % of the picture).
- media_response: «فایل: listening.mp3» naming an audio/video file uploaded together with the Word file.
Pictures inside the question, its options, pairs, items or the «توضیح» line are carried over.
A table whose first row holds the Excel headers («نوع», «متن سؤال», …) is returned as spreadsheet rows instead.
"""
import io
import json
import posixpath
import re
import struct
import zipfile
import zlib
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
MC_FALLBACK = '{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback'
MAX_OPTIONS = 10
MEDIA_BASE = 0xE000  # a picture/file inside the text is a private-use character: chr(MEDIA_BASE + index)
MEDIA_CHAR_RE = re.compile('[-]')
IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'gif'}
AUDIO_EXTENSIONS = {'mp3', 'wav', 'ogg', 'm4a'}
VIDEO_EXTENSIONS = {'mp4', 'webm'}
UNSUPPORTED_IMAGES = {'emf', 'wmf', 'bmp', 'tif', 'tiff', 'svg', 'jfif'}
PACKAGE_MEDIA = IMAGE_EXTENSIONS | AUDIO_EXTENSIONS | VIDEO_EXTENSIONS | UNSUPPORTED_IMAGES

# same length on both sides, so a normalized line keeps the character positions of the original (formatting per char)
_NORMALIZE = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩يكؤ', '01234567890123456789یکو')
_INVISIBLE = '‎‏‪‫‬‭‮⁦⁧⁨⁩﻿  \t'
ABJAD = ['الف', 'ب', 'ج', 'د', 'ه', 'و', 'ز', 'ح', 'ط', 'ی']
ALEFBA = ['الف', 'ب', 'ت', 'ث', 'ج', 'ح', 'خ', 'د', 'ذ', 'ر']
PERSIAN_LABELS = 'الف|هـ|ب|پ|ت|ث|ج|د|ه|و|ز|ح|ط'
_SEP = r'(?:[)\]]|[.:](?=\s|$)|\s*[\-–—ـ])'
OPTION_RE = re.compile(rf'^(?:گزینه\s*)?[(\[]?\s*({PERSIAN_LABELS}|[a-jA-J]|10|[1-9])\s*{_SEP}\s*')
INLINE_OPTION_RE = re.compile(rf'(?:(?<=\s)|^)[(\[]?({PERSIAN_LABELS}|[a-jA-J]|10|[1-9])\s*{_SEP}\s*')
QUESTION_PREFIX_RE = re.compile(r'^(?:سوال|پرسش|question|q)\s*(?:شماره\s*)?(\d{1,4})\s*(?:[\-–—ـ:.)]\s*)?', re.I)
QUESTION_NUMBER_RE = re.compile(r'^[(\[]?(\d{1,4})\s*(?:[)\]]|[.:](?=\s|$|\D)|\s*[\-–—ـ])\s*')
ANSWER_KEY_RE = re.compile(r'^(?:کلید(?:\s*(?:سوالات|سوال ها|پاسخ ها|پاسخ|ازمون))?|پاسخ\s*نامه|جدول پاسخ ها|answer\s*key|answers)\s*[:：\-–]?\s*', re.I)
KEY_PAIR_RE = re.compile(rf'(\d{{1,4}})\s*[\-–—ـ.):=]?\s*(درست|نادرست|صحیح|غلط|{PERSIAN_LABELS}|[a-jA-J]|[1-9])(?![^\s\d,،;|\-–—ـ.):=])')
PAIR_RE = re.compile(r'^(.+?)\s*(?:<=>|<->|=>|->|-->|→|←|↔|⇐|⇒|⟵|⟶|⟷|=)\s*(.+)$')
INDEXED_META_RE = re.compile(r'^(نشانه|جای خالی|جاخالی|پاسخ|جواب|blank|marker)\s*(\d{1,2})$')
BRACKET_BLANK_RE = re.compile(r'\[([^\[\]\n]+)\]')
NUMBER_BLANK_RE = re.compile(r'\[\s*(\d{1,2})\s*\]')
DOTS_BLANK_RE = re.compile(r'_{3,}|\.{4,}|…{2,}|(?:\.\s){3,}\.?')
COORDS_RE = re.compile(r'[(\[]\s*(-?\d+(?:\.\d+)?)\s*%?\s*[,،]\s*(-?\d+(?:\.\d+)?)\s*%?\s*[)\]]\s*$')
NUMBER_RE = re.compile(r'^\s*([-+−]?\d[\d,٬]*(?:[.٫]\d+)?)\s*(.*)$')
META_RE = re.compile(r'^\s*([^:：]{1,28}?)\s*[:：]\s*(.*)$')
CORRECT_MARK_RE = re.compile(r'\s*(?:\*+|\((?:صحیح|درست|correct)\)|[✓✔√☑])\s*$', re.I)
MATRIX_MARKS = {'✓', '✔', '√', '☑', '☒', '*', '**', 'x', '×', '✗', '✘', '■', '●', '+', 'بله', 'صحیح', 'درست', 'yes', '1', '⬤', '○●'}
TRUE_WORDS = {'درست', 'صحیح', 'true', 't', 'ص', 'بله'}
FALSE_WORDS = {'نادرست', 'غلط', 'false', 'f', 'غ', 'نا درست', 'خیر'}
SHORT_ANSWER_MAX_WORDS = 8

TYPE_LABELS = {
    'single': 'تک‌گزینه‌ای', 'multi': 'چندپاسخی', 'true_false': 'درست/نادرست', 'short_answer': 'پاسخ کوتاه',
    'essay': 'تشریحی', 'fill_blank': 'جای خالی', 'matching': 'تطبیقی', 'ordering': 'مرتب‌سازی',
    'numeric': 'پاسخ عددی', 'matrix': 'ماتریسی / جدول', 'image_label': 'تصویری / نشانه‌گذاری',
    'media_response': 'صوتی / ویدئویی',
}
_TYPE_WORDS = {
    'single': ('تک گزینه ای', 'تستی', 'چهار گزینه ای', 'تک پاسخی', 'single'),
    'multi': ('چند گزینه ای', 'چند پاسخی', 'چند جوابی', 'multi'),
    'true_false': ('درست نادرست', 'صحیح غلط', 'درست غلط', 'true false'),
    'short_answer': ('پاسخ کوتاه', 'کوتاه پاسخ', 'short answer'),
    'essay': ('تشریحی', 'باز پاسخ', 'essay'),
    'fill_blank': ('جای خالی', 'جا خالی', 'کامل کردنی', 'تکمیلی', 'fill blank'),
    'matching': ('تطبیقی', 'جور کردنی', 'وصل کردنی', 'matching'),
    'ordering': ('مرتب سازی', 'ترتیبی', 'ordering'),
    'numeric': ('عددی', 'پاسخ عددی', 'محاسباتی', 'numeric'),
    'matrix': ('ماتریسی', 'جدولی', 'ماتریسی جدول', 'matrix'),
    'image_label': ('تصویری', 'نشانه گذاری', 'تصویری نشانه گذاری', 'image label'),
    'media_response': ('صوتی', 'ویدئویی', 'صوتی ویدئویی', 'شنیداری', 'media response'),
}
META_FIELDS = {
    'type': ('نوع', 'نوع سوال', 'type'),
    'correct': ('پاسخ', 'پاسخ صحیح', 'پاسخ درست', 'جواب', 'جواب صحیح', 'جواب درست', 'گزینه صحیح', 'گزینه درست',
                'گزینه ی صحیح', 'گزینه ی درست', 'کلید', 'answer', 'correct'),
    'order': ('ترتیب صحیح', 'ترتیب درست', 'ترتیب', 'order'),
    'points': ('بارم', 'نمره', 'امتیاز', 'points', 'score'),
    'difficulty': ('دشواری', 'سطح دشواری', 'سطح', 'difficulty'),
    'tags': ('تگ', 'تگ ها', 'برچسب', 'برچسب ها', 'tags'),
    'subject': ('مبحث', 'موضوع', 'فصل', 'subject'),
    'explanation': ('توضیح', 'توضیحات', 'شرح', 'بازخورد', 'explanation', 'feedback'),
    'sample': ('پاسخ نمونه', 'پاسخ تشریحی', 'پاسخ کامل', 'sample answer'),
    'instructions': ('دستورالعمل', 'دستور العمل', 'راهنمای پاسخ', 'instructions'),
    'formats': ('قالب پاسخ', 'قالب های پاسخ', 'نوع پاسخ'),
    'unit': ('واحد', 'unit'),
    'tolerance': ('تلرانس', 'خطای مجاز', 'محدوده خطا', 'tolerance'),
    'decimals': ('رقم اعشار', 'تعداد اعشار', 'ارقام اعشار', 'decimals'),
    'distractors': ('گزینه های اضافی', 'گزینه اضافی', 'موارد اضافی', 'گزینه های انحرافی', 'distractors'),
    'matching_mode': ('حالت تطبیق', 'نوع تطبیق'),
    'selection': ('نوع انتخاب', 'حالت انتخاب'),
    'scoring': ('نمره دهی', 'روش نمره دهی', 'scoring'),
    'negative': ('نمره منفی', 'negative'),
    'image': ('تصویر', 'عکس', 'image'),
    'media': ('فایل', 'صوت', 'صدا', 'ویدئو', 'فیلم', 'فایل صوتی', 'فایل ویدئویی', 'audio', 'video', 'media'),
    'transcript': ('متن فایل', 'رونوشت', 'متن صوت', 'transcript'),
    'plays': ('دفعات پخش', 'تعداد پخش'),
    'record': ('مدت ضبط', 'زمان ضبط'),
    'label_mode': ('حالت پاسخ',),
}
DIFFICULTY = {'easy': 'easy', 'اسان': 'easy', 'ساده': 'easy', 'medium': 'medium', 'متوسط': 'medium',
              'hard': 'hard', 'سخت': 'hard', 'دشوار': 'hard'}
ESSAY_FORMAT_WORDS = {'متن': 'text', 'متنی': 'text', 'text': 'text', 'تصویر': 'image', 'عکس': 'image', 'image': 'image',
                      'صوت': 'audio', 'صدا': 'audio', 'صوتی': 'audio', 'audio': 'audio', 'ویدئو': 'video', 'فیلم': 'video',
                      'ویدئویی': 'video', 'video': 'video', 'فایل': 'file', 'پیوست': 'file', 'file': 'file'}


def _key(text) -> str:
    """Loose comparison: Persian/Arabic letters and digits unified, ZWNJ → space, «آ» → «ا», lower case."""
    text = str(text or '').translate(_NORMALIZE).replace('‌', ' ').replace('آ', 'ا').replace('ـ', '')
    return ' '.join(text.split()).lower()


def _squash(text) -> str:
    return re.sub(r'[\s/\\\-_()«»]', '', _key(text))


_META_LOOKUP = {name: field for field, names in META_FIELDS.items() for name in names}
_TYPE_LOOKUP = {_squash(word): kind for kind, words in _TYPE_WORDS.items() for word in words}
_TYPE_LOOKUP.update({_squash(kind): kind for kind in TYPE_LABELS})
_TYPE_LOOKUP.update({_squash(label): kind for kind, label in TYPE_LABELS.items()})


def question_type(value):
    """The builder type of a «نوع:» value («تطبیقی», «سؤال جای خالی», «matching» …), or None."""
    word = _squash(value).replace('سوال', '')
    if not word:
        return None
    if word in _TYPE_LOOKUP:
        return _TYPE_LOOKUP[word]
    for known in sorted(_TYPE_LOOKUP, key=len, reverse=True):  # «تشریحی و روبریک نمره دهی» → essay
        if len(known) >= 4 and known in word:
            return _TYPE_LOOKUP[known]
    return None


def _number_text(value):
    """«۲٫۵», «2,5», «1,200» → '2.5' / '1200'; None when it isn't a number."""
    text = str(value or '').translate(_NORMALIZE).replace('٫', '.').replace('−', '-').replace('٬', ',').strip()
    if text.count(',') == 1 and '.' not in text and len(text.split(',')[1]) != 3:
        text = text.replace(',', '.')
    text = text.replace(',', '')
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number or number in (float('inf'), float('-inf')):
        return None
    return f'{number:g}' if 'e' not in f'{number:g}' else text


def _val(element):
    return element.get(f'{W}val') if element is not None else None


def _on(element) -> bool:
    return element is not None and (_val(element) or 'true').lower() not in ('0', 'false', 'off', 'none')


def take_media(text):
    """(text without picture/file marks, [media indexes in order])."""
    text = str(text or '')
    found = [ord(char) - MEDIA_BASE for char in MEDIA_CHAR_RE.findall(text)]
    return (re.sub(r'[ \t]{2,}', ' ', MEDIA_CHAR_RE.sub(' ', text)).strip() if found else text.strip()), found


class _Line:
    __slots__ = ('text', 'fmt', 'bullet', 'blank', 'heading')

    def __init__(self, text, fmt, bullet=False, heading=False):
        self.heading = heading  # a Word heading/title paragraph: a section title, not part of a question
        start = 0
        while start < len(text) and text[start] in _INVISIBLE:
            start += 1
        end = len(text)
        while end > start and text[end - 1] in _INVISIBLE:
            end -= 1
        self.text, self.fmt = text[start:end], fmt[start:end]
        self.bullet, self.blank = bullet, not text[start:end].strip()


class _Table:
    def __init__(self, rows):
        self.rows = rows  # [[[_Line, …] per cell] per row]

    def cell_text(self, cell) -> str:
        return '\n'.join(line.text for line in cell if not line.blank).strip()

    def texts(self):
        return [[self.cell_text(cell) for cell in row] for row in self.rows]

    def lines(self):
        out = []
        for row in self.rows:
            for cell in row:
                out.extend(cell)
            out.append(_Line('', []))
        return out


# ---------------------------------------------------------------- reading the .docx

def _format_number(number, fmt) -> str:
    if fmt in ('lowerLetter', 'upperLetter'):
        letter = 'abcdefghijklmnopqrstuvwxyz'[(number - 1) % 26]
        return letter.upper() if fmt == 'upperLetter' else letter
    if fmt == 'arabicAbjad':
        return ABJAD[(number - 1) % len(ABJAD)]
    if fmt == 'arabicAlpha':
        return ALEFBA[(number - 1) % len(ALEFBA)]
    return str(number)


class _Numbering:
    """Word's automatic list numbers («1.», «الف)») are not in the text; rebuild them so they read like typed ones."""

    def __init__(self, xml):
        self.levels, self.counters = {}, {}
        if not xml:
            return
        root = ET.fromstring(xml)
        abstract = {}
        for node in root.findall(f'{W}abstractNum'):
            levels = {}
            for level in node.findall(f'{W}lvl'):
                ilvl = int(level.get(f'{W}ilvl') or 0)
                text = _val(level.find(f'{W}lvlText'))
                levels[ilvl] = [_val(level.find(f'{W}numFmt')) or 'decimal', f'%{ilvl + 1}.' if text is None else text,
                                int(_val(level.find(f'{W}start')) or 1)]
            abstract[node.get(f'{W}abstractNumId')] = levels
        for node in root.findall(f'{W}num'):
            levels = {ilvl: list(spec) for ilvl, spec in abstract.get(_val(node.find(f'{W}abstractNumId')), {}).items()}
            for override in node.findall(f'{W}lvlOverride'):
                start = _val(override.find(f'{W}startOverride'))
                ilvl = int(override.get(f'{W}ilvl') or 0)
                if start is not None and ilvl in levels:
                    levels[ilvl][2] = int(start)
            self.levels[node.get(f'{W}numId')] = levels

    def label(self, paragraph):
        """(label text, is a bullet) of a list paragraph; ('', False) otherwise."""
        num_pr = paragraph.find(f'{W}pPr/{W}numPr')
        if num_pr is None:
            return '', False
        num_id = _val(num_pr.find(f'{W}numId'))
        ilvl = int(_val(num_pr.find(f'{W}ilvl')) or 0)
        levels = self.levels.get(num_id) or {}
        if ilvl not in levels:
            return '', False
        counts = self.counters.setdefault(num_id, {})
        counts[ilvl] = counts.get(ilvl, levels[ilvl][2] - 1) + 1
        for deeper in [lvl for lvl in counts if lvl > ilvl]:
            del counts[deeper]
        fmt, text, _start = levels[ilvl]
        if fmt == 'bullet':
            return '', True
        if fmt == 'none':
            return '', False

        def number(match):
            lvl = int(match.group(1)) - 1
            spec = levels.get(lvl, ['decimal', '', 1])
            return _format_number(counts.get(lvl, spec[2]), spec[0])
        return re.sub(r'%(\d)', number, text).strip(), False


def _run_format(run) -> frozenset:
    props = run.find(f'{W}rPr')
    if props is None:
        return frozenset()
    flags = set()
    if _on(props.find(f'{W}b')) or _on(props.find(f'{W}bCs')):
        flags.add('bold')
    if _on(props.find(f'{W}u')):
        flags.add('underline')
    shade = props.find(f'{W}shd')
    if _on(props.find(f'{W}highlight')) or (shade is not None and (shade.get(f'{W}fill') or 'auto').lower() not in ('auto', 'ffffff')):
        flags.add('highlight')
    color = (_val(props.find(f'{W}color')) or 'auto').lower()
    if color not in ('auto', '000000'):
        flags.add('color')
    return frozenset(flags)


class _Docx:
    def __init__(self, data, header_field):
        self.archive = zipfile.ZipFile(io.BytesIO(data))
        names = set(self.archive.namelist())
        self.rels = {}
        if 'word/_rels/document.xml.rels' in names:
            for rel in ET.fromstring(self.archive.read('word/_rels/document.xml.rels')):
                if (rel.get('TargetMode') or '').lower() != 'external':
                    self.rels[rel.get('Id')] = rel.get('Target') or ''
        self.numbering = _Numbering(self.archive.read('word/numbering.xml') if 'word/numbering.xml' in names else None)
        self.media, self._media_ids = [], {}  # [(file name, bytes)]
        self.header_field = header_field
        self.style_names = {}  # paragraph style id → lower-case English name («heading 1», «title», «mq guide» …)
        if 'word/styles.xml' in names:
            for style in ET.fromstring(self.archive.read('word/styles.xml')).findall(f'{W}style'):
                self.style_names[style.get(f'{W}styleId')] = (_val(style.find(f'{W}name')) or '').lower()
        self.document = ET.fromstring(self.archive.read('word/document.xml'))

    def media_char(self, rel_id) -> str:
        target = self.rels.get(rel_id)
        if not target:
            return ''
        path = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('word', target))
        if path.rsplit('.', 1)[-1].lower() not in PACKAGE_MEDIA:
            return ''  # a hyperlink, an embedded OLE object (.bin) …
        if path not in self._media_ids:
            try:
                data = self.archive.read(path)
            except KeyError:
                return ''
            self._media_ids[path] = len(self.media)
            self.media.append((posixpath.basename(path), data))
        return chr(MEDIA_BASE + self._media_ids[path])

    def paragraph_lines(self, paragraph) -> list:
        style = _val(paragraph.find(f'{W}pPr/{W}pStyle')) or ''
        name = self.style_names.get(style, '')
        if style.startswith('MQ') or name.startswith('mq '):
            return []  # the sample file's instruction boxes and headings: never part of a question
        heading = name.startswith(('heading', 'title', 'subtitle')) or style.lower().startswith(('heading', 'title'))
        label, bullet = self.numbering.label(paragraph)
        chars, fmts = [], []

        def add(text, fmt):
            chars.append(text)
            fmts.extend([fmt] * len(text))

        def visit(node):
            if node.tag == MC_FALLBACK:  # the same picture again for old Word versions
                return
            if node.tag == f'{W}r':
                fmt = _run_format(node)
                for child in node:
                    if child.tag == f'{W}t':
                        add(child.text or '', fmt)
                    elif child.tag in (f'{W}tab', f'{W}ptab'):
                        add('\t', fmt)
                    elif child.tag in (f'{W}br', f'{W}cr'):
                        add('\n', fmt)
                    elif child.tag != f'{W}rPr':
                        seen = []
                        for element in child.iter():
                            if element.tag == MC_FALLBACK:
                                break
                            for attribute in (f'{R}embed', f'{R}id', f'{R}link'):
                                mark = self.media_char(element.get(attribute))
                                if mark and mark not in seen:
                                    seen.append(mark)
                        if seen:
                            add(' ' + ''.join(seen) + ' ', frozenset())
                        for nested in child:  # text boxes inside a drawing
                            visit(nested)
                return
            if node.tag == f'{M}t':  # an equation's text (Word's equation editor)
                add(node.text or '', frozenset())
                return
            for child in node:
                visit(child)
        if label:
            add(label + ' ', frozenset())
        for child in paragraph:
            if child.tag != f'{W}pPr':
                visit(child)
        text = ''.join(chars)
        lines, start = [], 0
        for piece in text.split('\n'):
            lines.append(_Line(piece, fmts[start:start + len(piece)], bullet=bullet and not lines, heading=heading))
            start += len(piece) + 1
        return lines

    def walk(self, container, items, header_rows):
        for child in container:
            if child.tag == f'{W}p':
                items.extend(self.paragraph_lines(child))
            elif child.tag == f'{W}tbl' and (_val(child.find(f'{W}tblPr/{W}tblStyle')) or '').startswith('MQ'):
                continue  # a guide table of the sample file
            elif child.tag == f'{W}tbl':
                rows = []
                for row in child.findall(f'{W}tr'):
                    cells = []
                    for cell in row.findall(f'{W}tc'):
                        found = []
                        self.walk(cell, found, header_rows)
                        cells.append([line for item in found for line in (item.lines() if isinstance(item, _Table) else [item])])
                    rows.append(cells)
                table = _Table(rows)
                texts = table.texts()
                heads = [' '.join(text.split()) for text in (texts[0] if texts else [])]
                if {'type', 'text'} <= {self.header_field(head) for head in heads}:  # the Excel columns as a Word table
                    header_rows.extend(dict(zip(heads, values)) for values in texts[1:] if any(values))
                elif rows:
                    items.append(table)
            elif child.tag in (f'{W}sdt', f'{W}sdtContent', f'{W}customXml', f'{W}smartTag', f'{W}ins'):
                self.walk(child, items, header_rows)


# ---------------------------------------------------------------- recognising the questions

class _Question:
    def __init__(self, number, sep=''):
        self.number, self.sep = number, sep
        self.text, self.options, self.meta, self.indexed = [], [], {}, {}
        self.tables, self.pairs = [], []
        self.last = 'text'
        self.ignored = []  # lines after this question that belong to no part of it (shown as a note)
        self.closed = False  # (files without question numbers) a blank line after options/answer ends the question

    def add_option(self, label, text, fmt):
        marked = False
        stripped = text.lstrip()
        if stripped.startswith('*'):
            marked, offset = True, len(text) - len(stripped.lstrip('*').lstrip())
            text, fmt = text[offset:], fmt[offset:]
        match = CORRECT_MARK_RE.search(text)
        if match:
            marked, text, fmt = True, text[:match.start()], fmt[:match.start()]
        flags = [f for c, f in zip(text, fmt) if not c.isspace() and not MEDIA_CHAR_RE.match(c)]
        common = frozenset.intersection(*flags) if flags else frozenset()
        self.options.append({'label': _key(label), 'text': text.strip(), 'marked': marked, 'format': common})
        self.last = 'option'


def _option_family(label) -> str:
    return 'digit' if label.isdigit() else 'latin' if label.isascii() else 'persian'


def _split_inline_options(norm, first_label):
    """[(label, start, end of marker)] of the option markers on one line («الف) … ب) … ج) …»), same family only."""
    family, used, markers = _option_family(first_label), set(), []
    for match in INLINE_OPTION_RE.finditer(norm):
        label = match.group(1)
        if _option_family(label) != family or _key(label) in used:
            continue
        if markers and family == 'digit' and int(label) != int(markers[-1][0]) + 1:
            continue
        if markers and family == 'latin' and ord(label.lower()) != ord(markers[-1][0].lower()) + 1:
            continue
        if not markers and match.start() != 0:
            continue
        used.add(_key(label))
        markers.append((label, match.start(), match.end()))
    return markers


def _question_number(norm):
    """(number, rest start, separator) when the line starts a numbered question, else None."""
    for pattern in (QUESTION_PREFIX_RE, QUESTION_NUMBER_RE):
        match = pattern.match(norm)
        if match:
            return int(match.group(1)), match.end(), norm[match.start(1) + len(match.group(1)):match.end()].strip()[:1]
    return None


def _is_data_table(table) -> bool:
    """A table of pairs / a matrix that belongs to the question above it (not a layout table holding options)."""
    texts = table.texts()
    if len(texts) < 2 or any(len(row) < 2 for row in texts):
        return False
    for row in texts:
        for cell in row:
            norm = cell.translate(_NORMALIZE)
            if OPTION_RE.match(norm) or (_question_number(norm) and len(norm) > 4):
                return False
    return True


class _Parser:
    def __init__(self, items):
        self.items = items
        all_lines = [line for item in items for line in (item.lines() if isinstance(item, _Table) else [item])]
        self.numbered = any(not line.blank and _question_number(line.text.translate(_NORMALIZE)) for line in all_lines)
        self.questions, self.current, self.typical, self.key_text = [], None, None, None

    def run(self):
        for item in self.items:
            if isinstance(item, _Table):
                current = self.current
                if current is not None and not current.closed and self.key_text is None and _is_data_table(item):
                    current.tables.append(item)
                    current.last = 'table'
                else:
                    for line in item.lines():
                        self.feed(line)
            else:
                self.feed(item)
        if self.key_text:
            by_number = {}
            for question in self.questions:
                by_number.setdefault(question.number, question)
            for number, answer in KEY_PAIR_RE.findall(' '.join(self.key_text)):
                question = by_number.get(int(number))
                if question is not None and not question.meta.get('correct'):
                    question.meta['correct'] = answer
        return [q for q in self.questions if q.text or q.options or q.tables or q.pairs]

    def start(self, number, sep=''):
        if self.current is not None and len(self.current.options) >= 2:
            self.typical = len(self.current.options)
        self.current = _Question(number, sep)
        self.questions.append(self.current)
        return self.current

    @staticmethod
    def add_text(question, text):
        text = text.strip()
        if not text:
            return
        if question.last == 'option' and question.options:
            question.options[-1]['text'] = (question.options[-1]['text'] + ' ' + text).strip()
        elif question.last in ('explanation', 'sample', 'instructions', 'transcript'):
            question.meta[question.last] = (question.meta[question.last] + '\n' + text).strip()
        elif not question.options and not question.tables and question.text and PAIR_RE.match(_key(text)):
            question.pairs.append(text)
            question.last = 'pair'
        else:
            question.text.append(text)
            question.last = 'text'

    @staticmethod
    def add_options(question, line, markers):
        for index, (label, _start, end) in enumerate(markers):
            stop = markers[index + 1][1] if index + 1 < len(markers) else len(line.text)
            question.add_option(label, line.text[end:stop], line.fmt[end:stop])

    CONTINUED = ('explanation', 'sample', 'instructions', 'transcript')  # fields that may run over several lines

    def feed(self, line):
        current = self.current
        if line.blank:
            if current is not None and not self.numbered and (current.options or current.meta):
                current.closed = True
            return
        norm = line.text.translate(_NORMALIZE)
        if self.key_text is not None:  # everything after «کلید سؤالات» is the answer key
            self.key_text.append(_key(norm))
            return
        key_match = ANSWER_KEY_RE.match(_key(norm))
        if key_match and self.questions:
            rest = _key(norm)[key_match.end():]
            if not rest or KEY_PAIR_RE.search(rest):
                self.key_text = [rest]
                return
        meta = META_RE.match(norm)
        if meta and current is not None:
            name = _key(meta.group(1))
            field = _META_LOOKUP.get(name)
            indexed = INDEXED_META_RE.match(name)
            value = line.text[meta.start(2):].strip()
            if field or indexed:
                if value and indexed:
                    kind = 'marker' if indexed.group(1) in ('نشانه', 'marker') else 'blank'
                    current.indexed.setdefault(kind, {})[int(indexed.group(2))] = value
                    current.last = 'indexed'
                elif value:
                    current.meta[field] = value
                    current.last = field
                return
        option = OPTION_RE.match(norm)
        numbered_q = _question_number(norm)
        is_option = option is not None and current is not None and not current.closed
        if is_option and numbered_q and option.group(1).isdigit():
            number = int(option.group(1))
            family_ok = not current.options or _option_family(current.options[0]['label']) == 'digit'
            is_option = family_ok and number == len(current.options) + 1
            if is_option and current.number is not None and number == current.number + 1 and self.typical and len(current.options) >= self.typical:
                is_option = False  # «3)» after three options when questions here have three: the next question
            if is_option and number == 1 and current.number and not current.options and numbered_q[2] == current.sep:
                is_option = False  # numbering restarted («1-» again) after a question without options
        if is_option:
            markers = _split_inline_options(norm, option.group(1)) or [(option.group(1), 0, option.end())]
            self.add_options(current, line, markers)
            return
        if numbered_q:
            number, offset, sep = numbered_q
            question = self.start(number, sep)
            rest = norm[offset:]
            inline = [m for m in INLINE_OPTION_RE.finditer(rest) if m.start() > 0 and _key(m.group(1)) in ('الف', 'a')]
            if inline:  # «1- سؤال؟ الف) … ب) …» on one line
                cut = offset + inline[0].start()
                question.text.append(line.text[offset:cut].strip())
                markers = [(label, s + cut, e + cut) for label, s, e in _split_inline_options(norm[cut:], inline[0].group(1))]
                self.add_options(question, line, markers)
            else:
                self.add_text(question, line.text[offset:])
            return
        if line.heading:  # «بخش دوم: سؤالات تشریحی» in a Word heading style: a section title
            if current is not None:
                current.closed = True
            return
        if line.bullet and current is not None and current.text and not current.closed:
            current.add_option('', line.text, line.fmt)
            return
        if current is None or (not self.numbered and (current.closed or current.options or current.meta)):
            if self.numbered and current is None:
                return  # the title / instructions above question 1
            self.add_text(self.start(None), line.text)
            return
        if self.numbered and current.last not in self.CONTINUED and (
                current.closed or current.options or current.meta or current.tables or current.indexed):
            if not take_media(line.text)[0] and current.last in ('option', 'text') and not current.closed:
                self.add_text(current, line.text)  # a picture on its own line under an option / the question
            else:
                current.ignored.append(take_media(line.text)[0] or '(تصویر)')  # a section title, a stray note …
            return
        self.add_text(current, line.text)


# ---------------------------------------------------------------- one question → builder fields

def _answer_indices(options, value):
    """Option positions (0-based) named by a «پاسخ» value: labels («ب»، «2»، «a»), several («الف، ج» / «1,3»), or the option text."""
    wanted = _key(value)
    for index, option in enumerate(options):
        if wanted and wanted == _key(option['text']):
            return [index]
    labelled = {option['label']: index for index, option in enumerate(options) if option['label']}
    cleaned = re.sub(r'گزینه(?:\s*ی|\s*های|\s*ها)?', ' ', wanted)
    tokens = [token.strip('()[].-–:') for token in re.split(r'[\s,،;/+|>]+', cleaned)]
    tokens = [token for token in tokens if token]
    if len(tokens) > 1:
        tokens = [token for position, token in enumerate(tokens) if token != 'و' or position in (0, len(tokens) - 1)]
    if not tokens:
        return None
    picked = []
    for token in tokens:
        token = {'هـ': 'ه'}.get(token, token)
        if token in labelled:
            picked.append(labelled[token])
        elif token.isdigit() and not any(label.isdigit() for label in labelled):
            picked.append(int(token) - 1)
        elif token in ABJAD and not labelled:
            picked.append(ABJAD.index(token))
        elif len(token) == 1 and 'a' <= token <= 'j' and not labelled:
            picked.append(ord(token) - ord('a'))
        else:
            return None
    if any(not 0 <= index < len(options) for index in picked):
        return None
    return list(dict.fromkeys(picked))


def _true_false_word(value):
    word = _key(value).strip('.)( ')
    return 'درست' if word in TRUE_WORDS else 'نادرست' if word in FALSE_WORDS else ''


def _alternatives(value):
    """«تهران / طهران» → 'تهران، طهران' (the builder splits a blank's answers on commas)."""
    return '، '.join(part.strip() for part in re.split(r'[/|،,]', str(value or '')) if part.strip())


def _is_mark(text) -> bool:
    return _key(text).strip() in MATRIX_MARKS


class _Builder:
    """Turns one parsed question into builder POST fields + the media to store for it."""

    def __init__(self, question, media, attachments):
        self.q, self.media, self.attachments = question, media, attachments
        self.fields, self.files = {}, {}  # files: POST key → (file name, bytes or an uploaded file)
        self.errors, self.notes, self.details = [], [], []
        self.shown = ''

    def set(self, name, *values):
        self.fields[name] = [str(value) for value in values]

    def attach(self, key, indexes, what, kinds=('image',)):
        """Store the first usable picture/file of `indexes` under POST key `key`; notes for the rest."""
        used = False
        for index in indexes:
            name, data = self.media[index]
            extension = name.rsplit('.', 1)[-1].lower()
            kind = 'image' if extension in IMAGE_EXTENSIONS else 'audio' if extension in AUDIO_EXTENSIONS else 'video' if extension in VIDEO_EXTENSIONS else ''
            if extension in UNSUPPORTED_IMAGES:
                self.notes.append(f'تصویر {what} با قالب {extension.upper()} است و منتقل نمی‌شود؛ آن را در Word به PNG یا JPG تبدیل کنید.')
            elif kind not in kinds or used:
                self.notes.append(f'فقط یک تصویر/فایل برای {what} منتقل می‌شود.' if used else f'فایل «{name}» برای {what} مناسب نیست.')
            else:
                self.files[key] = (name, data)
                used = True
        return used

    def attach_named(self, value, key, kinds, what):
        name = posixpath.basename(str(value or '').strip().replace('\\', '/'))
        found = self.attachments.get(name.lower())
        if not found:
            self.errors.append(f'فایل «{name}» ({what}) همراه فایل Word بارگذاری نشده است؛ آن را در «فایل‌های همراه» انتخاب کنید.')
            return False
        extension = name.rsplit('.', 1)[-1].lower()
        allowed = set().union(*({'image': IMAGE_EXTENSIONS, 'audio': AUDIO_EXTENSIONS, 'video': VIDEO_EXTENSIONS}[kind] for kind in kinds))
        if extension not in allowed:
            self.errors.append(f'فایل «{name}» برای {what} مناسب نیست (مجاز: {"، ".join(sorted(allowed))}).')
            return False
        self.files[key] = (found.name, found)
        return True

    # ---- the kind of question

    def kind(self):
        q, meta = self.q, self.q.meta
        if meta.get('type'):
            kind = question_type(meta['type'])
            if kind is None:
                self.errors.append(f'نوع «{meta["type"]}» شناخته نشد (مثلاً تک‌گزینه‌ای، چندپاسخی، درست/نادرست، پاسخ کوتاه، '
                                   'تشریحی، جای خالی، تطبیقی، مرتب‌سازی، عددی، ماتریسی، تصویری، صوتی).')
            return kind
        text = '\n'.join(q.text)
        if q.tables:
            texts = q.tables[0].texts()
            body = [cell for row in texts[1:] for cell in row[1:]]
            if len(texts[0]) >= 3 or (body and all(not cell or _is_mark(cell) for cell in body) and any(body)):
                return 'matrix'
            return 'matching'
        if len(q.pairs) >= 2:
            return 'matching'
        if q.indexed.get('marker'):
            return 'image_label'
        if meta.get('media') and not q.options:
            return 'media_response'
        if q.options:
            if len(q.options) >= 2 and all(PAIR_RE.match(_key(option['text'])) for option in q.options) and not any(o['marked'] for o in q.options) and not meta.get('correct'):
                return 'matching'
            if meta.get('order'):
                return 'ordering'
            return None  # decided by the answer: single / multi / true_false / ordering
        if not q.options and (NUMBER_BLANK_RE.search(text) or DOTS_BLANK_RE.search(text) or q.indexed.get('blank')
                              or any(not _number_text(m.group(1)) for m in BRACKET_BLANK_RE.finditer(text))):
            return 'fill_blank'
        correct = meta.get('correct', '')
        if correct and _true_false_word(correct):
            return 'true_false'
        if correct and self.numeric_answer(correct) is not None:
            return 'numeric'
        if correct and len(correct.split()) <= SHORT_ANSWER_MAX_WORDS:
            return 'short_answer'
        return 'essay'

    @staticmethod
    def numeric_answer(value):
        """(number text, unit, tolerance text) of «9.8 m/s²» / «9.8 ± 0.1», or None."""
        text = str(value or '').translate(_NORMALIZE).strip()
        tolerance = ''
        if '±' in text:
            text, tolerance = (part.strip() for part in text.split('±', 1))
        match = NUMBER_RE.match(text)
        if not match:
            return None
        number = _number_text(match.group(1))
        unit = match.group(2).strip()
        if number is None or len(unit.split()) > 2 or (unit and unit[0].isdigit()):
            return None
        unit_tolerance = re.match(r'^(.*?)\s*±\s*(.+)$', unit)
        if unit_tolerance:
            unit, tolerance = unit_tolerance.group(1).strip(), unit_tolerance.group(2).strip()
        return number, unit, tolerance

    # ---- building

    def build(self):
        q, meta = self.q, self.q.meta
        kind = self.kind()
        text, stem_media = take_media('\n'.join(part for part in q.text if part))
        explanation, feedback_media = take_media(meta.get('explanation', ''))
        points = _number_text(meta.get('points')) if meta.get('points') else '1'
        if points is None or float(points) <= 0:
            self.errors.append(f'«بارم» باید عددی بزرگ‌تر از صفر باشد (نوشته شده: «{meta.get("points")}»).')
            points = '1'
        self.set('structure', 'independent')
        self.set('is_published', '1')
        self.set('default_points', points)
        self.set('difficulty', DIFFICULTY.get(_key(meta.get('difficulty')), 'medium'))
        self.set('tags', str(meta.get('tags') or '').replace('،', ',').strip())
        self.set('subject', str(meta.get('subject') or '').strip())
        self.set('feedback_text', explanation)
        if meta.get('negative'):
            negative = _number_text(str(meta['negative']).replace('-', ''))
            if negative is None:
                self.errors.append('«نمره منفی» باید عدد باشد (مثلاً 0.25).')
            else:
                self.set('negative_marking', '1')
                self.set('negative_value', negative)
        if feedback_media:
            self.attach('existing_feedback_media', feedback_media, 'توضیح', ('image', 'audio', 'video'))
        if meta.get('image'):
            self.attach_named(meta['image'], 'existing_question_image', ('image',), 'تصویر سؤال')
        if meta.get('media'):
            name = str(meta['media']).strip().lower()
            slot = 'existing_question_video' if name.rsplit('.', 1)[-1] in VIDEO_EXTENSIONS else 'existing_question_audio'
            self.attach_named(meta['media'], slot, ('audio', 'video'), 'فایل صوتی/ویدئویی سؤال')
        if stem_media:
            images = [i for i in stem_media if self.media[i][0].rsplit('.', 1)[-1].lower() not in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS]
            others = [i for i in stem_media if i not in images]
            if images and 'existing_question_image' not in self.files:
                self.attach('existing_question_image', images, 'متن سؤال')
            for index in others:
                slot = 'existing_question_video' if self.media[index][0].rsplit('.', 1)[-1].lower() in VIDEO_EXTENSIONS else 'existing_question_audio'
                if slot not in self.files:
                    self.attach(slot, [index], 'متن سؤال', ('audio', 'video'))
        if kind is None and not self.errors:
            kind = self.choice_kind()
        kind = kind or 'single'
        self.set('type', kind)
        getattr(self, f'build_{kind}')(text)
        if 'text' not in self.fields:
            self.set('text', text)
        return kind

    def choice_kind(self):
        q, correct = self.q, self.q.meta.get('correct', '')
        words = [_true_false_word(option['text']) for option in q.options]
        if len(q.options) == 2 and sorted(words) == ['درست', 'نادرست']:
            return 'true_false'
        picked = self.picked_options()
        if picked and len(picked) > 1:
            return 'multi'
        if not picked and not correct and re.search(r'مرتب|ترتیب', _key('\n'.join(q.text))):
            return 'ordering'
        return 'single'

    def picked_options(self):
        """Indexes of the correct options: «پاسخ:», *, then formatting; None when not told."""
        options, correct = self.q.options, self.q.meta.get('correct', '')
        if correct:
            return _answer_indices(options, correct)
        marked = [index for index, option in enumerate(options) if option['marked']]
        if marked:
            return marked
        for flag in ('highlight', 'bold', 'underline', 'color'):
            formatted = [index for index, option in enumerate(options) if flag in option['format']]
            if 0 < len(formatted) < len(options):
                return formatted
        return None

    def option_list(self, prefix='option'):
        """[(text, label)] of the options with their pictures attached under option_media_<n>."""
        result = []
        for number, option in enumerate(self.q.options, start=1):
            text, media = take_media(option['text'])
            if media:
                self.attach(f'{prefix}_media_{number}', media, f'گزینه {number}', ('image', 'audio', 'video'))
                text = text or (f'گزینه {option["label"]}' if option['label'] else f'گزینه {number}')
            result.append((text, option['label']))
        return result

    def build_single(self, text, multi=False):
        options = self.option_list()
        if len(options) > MAX_OPTIONS:
            self.errors.append(f'این سؤال {len(options)} گزینه دارد؛ حداکثر {MAX_OPTIONS} گزینه پذیرفته می‌شود.')
        picked = self.picked_options()
        correct = self.q.meta.get('correct', '')
        if picked is None and correct:
            self.errors.append(f'پاسخ «{correct}» با هیچ‌کدام از گزینه‌های این سؤال جور نیست.')
        elif not picked:
            self.errors.append('گزینه‌ی درست مشخص نشده است (با * کنار گزینه، خط «پاسخ: ب» یا کلید پاسخ در انتهای فایل).')
        self.fields['option_text'] = [option for option, _label in options]
        self.fields['correct_options'] = [str(index + 1) for index in picked or []]
        if multi:
            self.set('scoring_mode', 'partial' if 'جز' in _key(self.q.meta.get('scoring')) else 'all_or_nothing')
            self.set('min_correct', '1')
            self.set('max_correct', '0')
        self.details = [f"{label or number}) {option}" for number, (option, label) in enumerate(options, start=1)]
        self.shown = '، '.join(self.details[index] for index in picked or [])

    def build_multi(self, text):
        self.build_single(text, multi=True)

    def build_true_false(self, text):
        q = self.q
        if q.options:
            options = self.option_list()
            picked = self.picked_options()
            words = [_true_false_word(option) for option, _label in options]
            value = words[picked[0]] if picked and len(picked) == 1 else _true_false_word(q.meta.get('correct', ''))
        else:
            value = _true_false_word(q.meta.get('correct', ''))
        if not value:
            self.errors.append('پاسخ سؤال درست/نادرست را با «پاسخ: درست» یا «پاسخ: نادرست» مشخص کنید.')
        self.fields['option_text'] = ['درست', 'نادرست']
        self.fields['correct_options'] = ['1' if value == 'درست' else '2'] if value else []
        self.shown = value

    def build_short_answer(self, text):
        answers = [part.strip() for part in str(self.q.meta.get('correct', '')).split('|') if part.strip()]
        self.fields['accepted_answer'] = answers
        for index in range(1, len(answers) + 1):
            self.set(f'accepted_points_{index}', '100')
            self.set(f'accepted_mode_{index}', 'exact')
            self.set(f'accepted_normalize_{index}', '1')
        self.shown = ' | '.join(answers)

    def build_essay(self, text):
        meta = self.q.meta
        formats = [ESSAY_FORMAT_WORDS[word] for word in re.split(r'[\s,،/+و]+', _key(meta.get('formats'))) if word in ESSAY_FORMAT_WORDS]
        self.fields['answer_formats'] = list(dict.fromkeys(formats)) or ['text']
        self.set('student_instructions', meta.get('instructions', ''))
        self.set('sample_answer_text', meta.get('sample') or meta.get('correct', ''))
        self.shown = (meta.get('sample') or meta.get('correct', ''))[:120]

    def build_fill_blank(self, text):
        q = self.q
        answers = {}
        blanks = q.indexed.get('blank', {})
        count = 0

        def bracket(match):
            nonlocal count
            inner = match.group(1)
            if _number_text(inner) is not None and inner.strip().isdigit():
                return match.group(0)
            count += 1
            answers[count] = _alternatives(inner)
            return f'[{count}]'
        stem = BRACKET_BLANK_RE.sub(bracket, text)
        if not answers:
            numbered = [int(n) for n in NUMBER_BLANK_RE.findall(stem.translate(_NORMALIZE))]
            if not numbered:
                def dots(_match):
                    nonlocal count
                    count += 1
                    return f'[{count}]'
                stem = DOTS_BLANK_RE.sub(dots, stem)
                numbered = list(range(1, count + 1))
            else:
                stem = NUMBER_BLANK_RE.sub(lambda m: f'[{int(m.group(1).translate(_NORMALIZE))}]', stem)
            parts = [part for part in str(q.meta.get('correct', '')).split('|')] if q.meta.get('correct') else []
            if len(numbered) == 1 and len(parts) > 1:  # «پاسخ: تهران | طهران» for one blank = alternatives
                parts = ['، '.join(parts)]
            for position, number in enumerate(numbered):
                answers[number] = _alternatives(blanks.get(number) or (parts[position] if position < len(parts) else ''))
            count = max(numbered) if numbered else 0
        self.set('text', stem)
        self.set('blank_count', count)
        self.set('normalize_answers', '1')
        for number in range(1, count + 1):
            self.set(f'blank_answers_{number}', answers.get(number, ''))
            self.set(f'blank_points_{number}', '1')
        self.details = [f'جای خالی {number}: {answers.get(number) or "—"}' for number in range(1, count + 1)]
        self.shown = ' | '.join(answers.get(number, '') for number in range(1, count + 1))

    def build_matching(self, text):
        q, pairs, distractors = self.q, [], []
        if q.tables:
            table = q.tables[0]
            rows = table.rows
            texts = table.texts()
            start = 1 if texts and all(_key(cell).startswith('ستون') or _key(cell) in ('الف', 'ب', 'a', 'b', 'سوال', 'پاسخ') for cell in texts[0][:2]) else 0
            for row, values in zip(rows[start:], texts[start:]):
                left, right = values[0], values[1]
                if not take_media(left)[0] and not take_media(left)[1]:
                    if right:
                        distractors.append(take_media(right)[0])
                    continue
                pairs.append((left, right))
        elif q.pairs:
            for line in q.pairs:
                match = PAIR_RE.match(line.translate(_NORMALIZE)) or PAIR_RE.match(line)
                pairs.append((line[:match.start(2)].rstrip(' =<>-→←↔⇐⇒⟵⟶⟷'), line[match.start(2):]) if match else (line, ''))
        else:
            for option in q.options:
                match = PAIR_RE.match(option['text'])
                pairs.append((match.group(1), match.group(2)) if match else (option['text'], ''))
        lefts, rights = [], []
        for number, (left, right) in enumerate(pairs, start=1):
            left_text, left_media = take_media(left)
            right_text, right_media = take_media(right)
            if left_media:
                self.attach(f'matching_left_media_{number}', left_media, f'جفت {number}', ('image', 'audio', 'video'))
                left_text = left_text or f'تصویر {number}'
            if right_media:
                self.attach(f'matching_right_media_{number}', right_media, f'جفت {number}', ('image', 'audio', 'video'))
                right_text = right_text or f'تصویر {number}'
            lefts.append(left_text.strip())
            rights.append(right_text.strip())
            self.set(f'matching_points_{number}', '1')
        self.fields['matching_left'], self.fields['matching_right'] = lefts, rights
        distractors += [part.strip() for part in re.split(r'[،,\n]', str(q.meta.get('distractors') or '')) if part.strip()]
        self.set('matching_distractors', '، '.join(distractors))
        self.set('matching_mode', 'many_to_one' if 'چند' in _key(q.meta.get('matching_mode')) else 'one_to_one')
        self.details = [f'{left} ← {right}' for left, right in zip(lefts, rights)] + ([f'اضافی: {"، ".join(distractors)}'] if distractors else [])
        self.shown = f'{len(lefts)} جفت'

    def build_ordering(self, text):
        q = self.q
        options = self.option_list(prefix='ordering_tmp')
        order = list(range(len(options)))
        given = q.meta.get('order') or q.meta.get('correct')
        if given:
            picked = _answer_indices(q.options, given)
            if picked is None or sorted(picked) != order:
                self.errors.append(f'«ترتیب صحیح» ({given}) باید همه‌ی موارد را یک بار نام ببرد (مثلاً «ج، الف، ب، د»).')
            else:
                order = picked
        self.fields['ordering_item'] = [options[index][0] for index in order]
        for position, index in enumerate(order, start=1):  # the pictures follow their items into the new order
            source = self.files.pop(f'ordering_tmp_media_{index + 1}', None)
            if source:
                self.files[f'ordering_media_{position}'] = source
        self.files = {key: value for key, value in self.files.items() if not key.startswith('ordering_tmp_')}
        self.set('ordering_mode', 'exact')
        self.details = [f'{position}. {options[index][0]}' for position, index in enumerate(order, start=1)]
        self.shown = ' ← '.join(options[index][1] or options[index][0] for index in order)

    def build_numeric(self, text):
        meta = self.q.meta
        parsed = self.numeric_answer(meta.get('correct', ''))
        if parsed is None:
            self.errors.append(f'پاسخ سؤال عددی باید عدد باشد (نوشته شده: «{meta.get("correct", "")}»).')
            parsed = ('', '', '')
        value, unit, tolerance = parsed
        unit = meta.get('unit', '') or unit
        tolerance = str(meta.get('tolerance', '') or tolerance).translate(_NORMALIZE)
        percent = '%' in tolerance or 'درصد' in tolerance
        tolerance_value = _number_text(re.sub(r'[%±+\s]|درصد', '', tolerance)) if tolerance else '0'
        if tolerance_value is None:
            self.errors.append(f'«تلرانس» باید عدد باشد (مثلاً 0.1 یا 5%) — نوشته شده: «{tolerance}».')
            tolerance_value = '0'
        decimals = _number_text(meta.get('decimals')) if meta.get('decimals') else str(max(
            len(value.split('.')[1]) if '.' in value else 0, len(tolerance_value.split('.')[1]) if '.' in tolerance_value else 0))
        self.set('numeric_answer', value)
        self.set('numeric_unit', unit)
        self.set('numeric_decimals', decimals or '0')
        self.set('numeric_tolerance_mode', 'percent' if percent else 'absolute')
        self.set('numeric_tolerance', tolerance_value)
        self.set('numeric_accept_persian', '1')
        self.shown = f"{value}{' ± ' + tolerance_value + ('%' if percent else '') if tolerance_value not in ('0', '') else ''}{' ' + unit if unit else ''}"

    def build_matrix(self, text):
        q = self.q
        if not q.tables:
            self.errors.append('برای سؤال ماتریسی زیر متن سؤال یک جدول بگذارید: ردیف اول عنوان ستون‌ها، ستون اول متن هر سطر و ✓ در خانه‌های درست.')
            return
        texts = q.tables[0].texts()
        width = max(len(row) for row in texts)
        columns = [{'id': f'c{index}', 'text': take_media(cell)[0]} for index, cell in enumerate(texts[0][1:width], start=1)]
        rows = []
        for number, row in enumerate(texts[1:], start=1):
            if not any(row):
                continue
            correct = [f'c{index}' for index, cell in enumerate(row[1:], start=1) if cell and _is_mark(cell)]
            rows.append({'id': f'r{number}', 'text': take_media(row[0])[0], 'points': 1, 'correct': correct})
        self.set('matrix_json', json.dumps({'columns': columns, 'rows': rows}, ensure_ascii=False))
        multi = any(len(row['correct']) > 1 for row in rows) or 'چند' in _key(q.meta.get('selection'))
        self.set('matrix_selection', 'multi' if multi else 'single')
        self.set('matrix_show_column_titles', '1')
        self.set('matrix_show_row_titles', '1')
        titles = {column['id']: column['text'] for column in columns}
        self.details = [f"{row['text']} ← {'، '.join(titles.get(c, c) for c in row['correct']) or '—'}" for row in rows]
        self.shown = f'{len(rows)} سطر × {len(columns)} ستون'

    def build_image_label(self, text):
        q = self.q
        entries = sorted(q.indexed.get('marker', {}).items())
        if not entries and q.options:
            entries = [(number, option['text']) for number, option in enumerate(q.options, start=1)]
        markers, placed = [], False
        for position, (number, value) in enumerate(entries):
            value = take_media(value)[0]
            coords = COORDS_RE.search(value.translate(_NORMALIZE))
            if coords:
                x, y = float(coords.group(1)), float(coords.group(2))
                value = value[:coords.start()].strip()
            else:
                x, y = 15 + (position % 4) * 23, 15 + (position // 4) * 23
                placed = True
            names = [part.strip() for part in re.split(r'[،,/|]', value) if part.strip()]
            markers.append({'x': x, 'y': y, 'answer': names[0] if names else '', 'synonyms': '، '.join(names[1:]), 'points': 1})
        if placed and markers:
            self.notes.append('جای نشانه‌ها در فایل مشخص نشده بود؛ نشانه‌ها کنار هم گذاشته شدند — پس از ثبت، در ویرایش سؤال روی تصویر جابه‌جا کنید (یا در Word بنویسید «نشانه 1: قلب (30، 40)»).')
        self.set('label_markers_json', json.dumps(markers, ensure_ascii=False))
        self.set('label_answer_mode', 'drag' if 'کشیدن' in _key(q.meta.get('label_mode')) else 'type')
        self.set('label_accept_synonyms', '1')
        self.details = [f"نشانه {index}: {marker['answer']}{' (' + marker['synonyms'] + ')' if marker['synonyms'] else ''}" for index, marker in enumerate(markers, start=1)]
        self.shown = '، '.join(marker['answer'] for marker in markers)

    def build_media_response(self, text):
        meta = self.q.meta
        formats = [ESSAY_FORMAT_WORDS[word] for word in re.split(r'[\s,،/+و]+', _key(meta.get('formats'))) if word in ESSAY_FORMAT_WORDS]
        self.fields['answer_formats'] = [f for f in dict.fromkeys(formats) if f in ('text', 'audio', 'video')] or ['audio']
        self.set('media_allow_replay', '1')
        plays = _number_text(meta.get('plays')) if meta.get('plays') else '0'
        self.set('media_max_plays', plays or '0')
        record = _number_text(re.sub(r'[^\d.]', '', str(meta.get('record', '')).translate(_NORMALIZE))) if meta.get('record') else '120'
        self.set('media_max_record_seconds', record or '120')
        self.set('media_transcript', meta.get('transcript', ''))
        self.shown = 'تصحیح دستی'


def read_docx_questions(data: bytes, header_field, attachments=None):
    """(Excel-like rows from a header table, [question dicts]) of a .docx.

    Each question dict: number, kind, fields (POST name → [values]), files (POST key → (file name, bytes or an
    uploaded file)), errors, notes, text, correct (shown), details (options / pairs / … for the preview).
    `attachments` maps lower-case file names to files uploaded with the Word file («فایل: listening.mp3»)."""
    docx = _Docx(data, header_field)
    items, header_rows = [], []
    body = docx.document.find(f'{W}body')
    if body is not None:
        docx.walk(body, items, header_rows)
    questions = []
    for number, question in enumerate(_Parser(items).run(), start=1):
        builder = _Builder(question, docx.media, attachments or {})
        kind = builder.build()
        if question.ignored:
            shown = '»، «'.join(text[:60] for text in question.ignored[:3]) + ('» …' if len(question.ignored) > 3 else '»')
            builder.notes.append(f'این خط‌ها بعد از این سؤال آمده‌اند و جزو آن نیستند، پس ثبت نمی‌شوند: «{shown}')
        questions.append({
            'number': number, 'kind': kind, 'fields': builder.fields, 'files': builder.files,
            'errors': builder.errors, 'notes': builder.notes, 'text': builder.fields.get('text', [''])[0],
            'correct': builder.shown, 'details': builder.details,
        })
    return header_rows, questions


# ---------------------------------------------------------------- the sample file

def _png(width, height, pixel) -> bytes:
    raw = b''.join(b'\x00' + b''.join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))

    def chunk(tag, payload):
        return struct.pack('>I', len(payload)) + tag + payload + struct.pack('>I', zlib.crc32(tag + payload) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def sample_shapes_png() -> bytes:
    """300×180: a red circle centred at (30%, 50%) and a blue square centred at (70%, 50%)."""
    def pixel(x, y):
        if (x - 90) ** 2 + (y - 90) ** 2 <= 45 ** 2:
            return (220, 38, 38)
        if abs(x - 210) <= 40 and abs(y - 90) <= 40:
            return (37, 99, 235)
        return (241, 245, 249)
    return _png(300, 180, pixel)


def _shape_png(shape) -> bytes:
    """120×120 picture of one shape, for the «picture options» example."""
    def pixel(x, y):
        inside = (x - 60) ** 2 + (y - 60) ** 2 <= 42 ** 2 if shape == 'circle' else abs(x - 60) <= 38 and abs(y - 60) <= 38
        return ((220, 38, 38) if shape == 'circle' else (37, 99, 235)) if inside else (248, 250, 252)
    return _png(120, 120, pixel)


_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Tahoma" w:hAnsi="Tahoma" w:eastAsia="Tahoma" w:cs="Tahoma"/>'
    '<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-US" w:bidi="fa-IR"/></w:rPr></w:rPrDefault>'
    '<w:pPrDefault><w:pPr><w:bidi/><w:spacing w:after="40" w:line="300" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
    # everything in an «MQ…» style is instructions: the import skips it
    '<w:style w:type="paragraph" w:styleId="MQTitle"><w:name w:val="MQ Title"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:spacing w:after="60"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="1E3A8A"/><w:sz w:val="40"/><w:szCs w:val="40"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="MQSubtitle"><w:name w:val="MQ Subtitle"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:spacing w:after="240"/><w:pBdr><w:bottom w:val="single" w:sz="12" w:space="8" w:color="1D4ED8"/></w:pBdr></w:pPr>'
    '<w:rPr><w:color w:val="475569"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="MQHeading"><w:name w:val="MQ Heading"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:keepNext/><w:spacing w:before="420" w:after="120"/><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="4" w:color="93C5FD"/></w:pBdr></w:pPr>'
    '<w:rPr><w:b/><w:bCs/><w:color w:val="1D4ED8"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="MQGuide"><w:name w:val="MQ Guide"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:keepNext/><w:pBdr><w:top w:val="single" w:sz="4" w:space="4" w:color="BFDBFE"/><w:left w:val="single" w:sz="4" w:space="6" w:color="BFDBFE"/>'
    '<w:bottom w:val="single" w:sz="4" w:space="4" w:color="BFDBFE"/><w:right w:val="single" w:sz="24" w:space="6" w:color="3B82F6"/></w:pBdr>'
    '<w:shd w:val="clear" w:color="auto" w:fill="EFF6FF"/><w:spacing w:after="0" w:line="288" w:lineRule="auto"/><w:ind w:left="170" w:right="170"/></w:pPr>'
    '<w:rPr><w:color w:val="1E293B"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="MQCode"><w:name w:val="MQ Code"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:pBdr><w:top w:val="dashed" w:sz="4" w:space="4" w:color="94A3B8"/><w:left w:val="dashed" w:sz="4" w:space="6" w:color="94A3B8"/>'
    '<w:bottom w:val="dashed" w:sz="4" w:space="4" w:color="94A3B8"/><w:right w:val="dashed" w:sz="4" w:space="6" w:color="94A3B8"/></w:pBdr>'
    '<w:shd w:val="clear" w:color="auto" w:fill="F8FAFC"/><w:spacing w:after="0"/><w:ind w:left="170" w:right="170"/></w:pPr>'
    '<w:rPr><w:color w:val="334155"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="MQExample"><w:name w:val="MQ Example"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/></w:pPr>'
    '<w:rPr><w:b/><w:bCs/><w:color w:val="15803D"/><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style>'
    '<w:style w:type="table" w:styleId="MQGuideTable"><w:name w:val="MQ Guide Table"/></w:style>'
    '</w:styles>'
)


def _runs(text, style=None):
    """Runs of one paragraph: «**bold**» parts are bold, a tab is a Word tab; style: bold/highlight/size/color."""
    style = style or {}
    base = ''
    if style.get('highlight'):
        base += '<w:highlight w:val="yellow"/>'
    if style.get('color'):
        base += f'<w:color w:val="{style["color"]}"/>'
    if style.get('size'):
        base += f'<w:sz w:val="{style["size"]}"/><w:szCs w:val="{style["size"]}"/>'
    out = []
    for index, part in enumerate(str(text).split('**')):
        bold = style.get('bold') or index % 2 == 1
        props = ('<w:b/><w:bCs/>' if bold else '') + base
        for number, piece in enumerate(part.split('\t')):
            # a Persian run must be marked right-to-left, or Word puts «)», «.», «-» and digits on the wrong side
            rtl = '<w:rtl/>' if re.search('[؀-ۿ]', text) else ''
            if number:
                out.append(f'<w:r><w:rPr>{props}{rtl}</w:rPr><w:tab/></w:r>')
            if piece:
                out.append(f'<w:r><w:rPr>{props}{rtl}</w:rPr><w:t xml:space="preserve">{escape(piece)}</w:t></w:r>')
    return ''.join(out)


def _paragraph(inner, style_id=None, align=None, keep=False):
    props = (f'<w:pStyle w:val="{style_id}"/>' if style_id else '') + ('<w:keepNext/>' if keep else '') + '<w:bidi/>' + (f'<w:jc w:val="{align}"/>' if align else '')
    return f'<w:p><w:pPr>{props}</w:pPr>{inner}</w:p>'


def build_docx(paragraphs) -> bytes:
    """A right-to-left .docx. Each item is one of:
    - 'text' or ('text', {'bold', 'highlight', 'size', 'color'}): a normal paragraph (a tab becomes a Word tab);
    - {'style': 'MQGuide' | 'MQHeading' | 'MQTitle' | 'MQSubtitle' | 'MQExample' | 'MQCode', 'text': …}: an
      instruction paragraph («**…**» is bold) — the import skips every «MQ…» paragraph;
    - {'image': png bytes, 'width': px, 'height': px}: a picture on its own line;
    - {'table': [[cell, …], …], 'guide': bool, 'header': bool}: a table (guide tables are skipped by the import)."""
    body, images = [], []
    for item in paragraphs:
        if isinstance(item, dict) and 'image' in item:
            images.append(item['image'])
            number = len(images)
            cx, cy = int(item.get('width', 300)) * 9525, int(item.get('height', 180)) * 9525
            body.append(_paragraph(
                f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
                f'<wp:docPr id="{number}" name="Picture {number}"/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
                f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{number}" name="image{number}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
                f'<pic:blipFill><a:blip r:embed="rIdImg{number}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
                f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
                '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>', keep=item.get('keep')))
        elif isinstance(item, dict) and 'table' in item:
            guide = item.get('guide')
            color = 'BFDBFE' if guide else 'CBD5E1'
            border = ''.join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
                             for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
            rows = []
            for row_number, row in enumerate(item['table']):
                header = item.get('header', True) and row_number == 0
                fill = ('DBEAFE' if guide else 'F1F5F9') if header else ('FFFFFF' if not guide else 'F8FBFF')
                cells = []
                for column, cell in enumerate(row):
                    mark = not guide and column > 0 and not header and len(cell) <= 2
                    inner = _runs(cell, {'bold': header, 'size': 20 if guide else None})
                    cells.append(f'<w:tc><w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="{fill}"/></w:tcPr>'
                                 f'{_paragraph(inner, align="center" if mark else None)}</w:tc>')
                rows.append('<w:tr>' + ''.join(cells) + '</w:tr>')
            style = '<w:tblStyle w:val="MQGuideTable"/>' if guide else ''
            body.append(f'<w:tbl><w:tblPr>{style}<w:bidiVisual/><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{border}</w:tblBorders>'
                        '<w:tblCellMar><w:top w:w="60" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/>'
                        f'<w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr>{"".join(rows)}</w:tbl>')
            body.append(_paragraph(''))
        elif isinstance(item, dict):
            body.append(_paragraph(_runs(item.get('text', '')), item.get('style')))
        else:
            text, style = (item, {}) if isinstance(item, str) else item
            body.append(_paragraph(_runs(text, style), keep=style.get('keep')))
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
                'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><w:body>'
                + ''.join(body) +
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" '
                'w:left="1134" w:header="709" w:footer="709" w:gutter="0"/><w:bidi/></w:sectPr></w:body></w:document>')
    relationships = ('<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
                     'Target="styles.xml"/>') + ''.join(
        f'<Relationship Id="rIdImg{number}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        f'Target="media/image{number}.png"/>' for number in range(1, len(images) + 1))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml',
                         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                         '<Default Extension="xml" ContentType="application/xml"/>'
                         '<Default Extension="png" ContentType="image/png"/>'
                         '<Override PartName="/word/document.xml" '
                         'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                         '<Override PartName="/word/styles.xml" '
                         'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                         '</Types>')
        archive.writestr('_rels/.rels',
                         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" '
                         'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                         'Target="word/document.xml"/></Relationships>')
        archive.writestr('word/_rels/document.xml.rels',
                         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relationships}</Relationships>')
        archive.writestr('word/styles.xml', _STYLES)
        archive.writestr('word/document.xml', document)
        for number, image in enumerate(images, start=1):
            archive.writestr(f'word/media/image{number}.png', image)
    return buffer.getvalue()


def _guide(*lines):
    return [{'style': 'MQGuide', 'text': line} for line in lines]


def _example(*lines, label='نمونه — دقیقاً به همین شکل بنویسید:'):
    """An example question: the first line bold, «عنوان: مقدار» lines grey (formatting never marks options here)."""
    items = [{'style': 'MQExample', 'text': label}]
    for index, line in enumerate(lines):
        keep = index < len(lines) - 1  # an example stays on one page
        if isinstance(line, dict):
            items.append({**line, 'keep': keep})
        elif index == 0:
            items.append((line, {'bold': True, 'keep': keep}))
        elif META_RE.match(line) and _META_LOOKUP.get(_key(META_RE.match(line).group(1))):
            items.append((line, {'color': '64748B', 'keep': keep}))
        else:
            items.append((line, {'keep': keep}))
    return items + ['']


def sample_docx() -> bytes:
    """The sample Word file: how to use it, the shared rules, then one worked example per question type.
    Every instruction is in an «MQ…» style and is skipped by the import, so the file itself imports 13 questions."""
    heading = lambda text: {'style': 'MQHeading', 'text': text}  # noqa: E731
    return build_docx([
        {'style': 'MQTitle', 'text': 'راهنما و نمونه‌ی فایل Word برای ورود گروهی سؤالات'},
        {'style': 'MQSubtitle', 'text': 'متاکوییز — سؤال‌های خود را به شکل نمونه‌های این فایل بنویسید و فایل را در صفحه‌ی «ورود گروهی سؤالات» بارگذاری کنید.'},

        heading('چطور از این فایل استفاده کنم؟'),
        *_guide(
            '**۱.** سؤال‌ها را دقیقاً به شکل نمونه‌های این فایل بنویسید. ساده‌ترین راه: همین فایل را ویرایش کنید، نمونه‌ها را پاک کنید و سؤال‌های خودتان را جای آن‌ها بنویسید.',
            '**۲.** متن‌های داخل کادرهای آبی (مثل همین کادر) و عنوان‌های آبی فقط راهنما هستند و ثبت نمی‌شوند؛ لازم نیست آن‌ها را پاک کنید.',
            '**۳.** فایل را با قالب «Word Document» (پسوند docx) ذخیره کنید؛ فایل‌های قدیمی با پسوند doc خوانده نمی‌شوند.',
            '**۴.** در سامانه: بانک سؤال ← «ورود گروهی» ← درس را انتخاب کنید ← فایل را انتخاب کنید ← «بررسی فایل».',
            '**۵.** سامانه هر سؤال را با نوع و پاسخ درستش نشان می‌دهد. سؤالی که ایراد دارد ثبت نمی‌شود و دلیلش کنارش نوشته می‌شود. پس از مرور، «ثبت در بانک سؤال» را بزنید.',
        ),

        heading('قواعد مشترک همه‌ی سؤال‌ها'),
        *_guide(
            '• **شماره:** هر سؤال با شماره و خط تیره شروع شود، مثل «1- متن سؤال». شماره‌گذاری خودکار Word هم قبول است.',
            '• **تنظیمات:** هر تنظیم در یک خط جدا، زیر همان سؤال، به شکل «عنوان: مقدار» نوشته شود؛ مثل «بارم: 2».',
            '• **نوع سؤال:** لازم نیست نوع را بنویسید؛ سامانه آن را از شکل سؤال تشخیص می‌دهد. اگر تشخیص درست نبود، خط «نوع: …» را اضافه کنید.',
            '• **عنوان بخش:** اگر بین سؤال‌ها عنوانی مثل «بخش دوم» می‌نویسید، آن را با سبک Heading در Word بنویسید تا جزو سؤال قبلی حساب نشود.',
            '• **فاصله:** بین دو سؤال یک خط خالی بگذارید تا فایل خواناتر باشد.',
        ),
        {'style': 'MQExample', 'text': 'خط‌های اختیاری که زیر هر سؤال می‌توانید بنویسید:'},
        {'guide': True, 'table': [
            ['خط', 'کاربرد', 'نمونه'],
            ['بارم', 'نمره‌ی سؤال (اگر ننویسید: ۱)', 'بارم: 2'],
            ['دشواری', 'آسان، متوسط یا سخت (اگر ننویسید: متوسط)', 'دشواری: سخت'],
            ['مبحث', 'موضوع درسی سؤال', 'مبحث: جغرافیا'],
            ['تگ', 'برچسب‌ها، با ویرگول جدا', 'تگ: پایتخت، آسیا'],
            ['توضیح', 'توضیح پاسخ، که به‌عنوان بازخورد به دانشجو نشان داده می‌شود', 'توضیح: …'],
            ['نمره منفی', 'نمره‌ای که برای پاسخ غلط کم می‌شود (سؤال‌های تستی)', 'نمره منفی: 0.25'],
            ['نوع', 'تعیین نوع سؤال به‌دست خودتان', 'نوع: تشریحی'],
        ]},

        heading('۱. تک‌گزینه‌ای (تستی)'),
        *_guide(
            '• هر گزینه را در یک خط جدا با «الف)»، «ب)»، «ج)»، «د)» شروع کنید (یا «1)»، «2)»، «3)»، «4)»).',
            '• کنار گزینه‌ی درست یک ستاره * بگذارید.',
            '• به‌جای ستاره می‌توانید خط «پاسخ: ب» را بنویسید، گزینه‌ی درست را هایلایت کنید، یا پاسخ را در «کلید پاسخ» انتهای فایل بنویسید.',
        ),
        *_example('1- پایتخت ایران کدام شهر است؟', 'الف) تبریز', 'ب) تهران *', 'ج) شیراز', 'د) مشهد',
                  'بارم: 1', 'دشواری: آسان', 'مبحث: جغرافیا', 'توضیح: تهران از سال ۱۱۶۵ خورشیدی پایتخت ایران است.'),

        heading('۲. چندپاسخی'),
        *_guide(
            '• مثل تک‌گزینه‌ای بنویسید، ولی بیش از یک گزینه را درست مشخص کنید؛ سامانه آن را خودکار «چندپاسخی» ثبت می‌کند.',
            '• می‌توانید چند گزینه را در یک خط بنویسید (با Tab یا چند فاصله بین آن‌ها).',
            '• پیش‌فرض: فقط پاسخ کاملاً درست نمره می‌گیرد. برای نمره‌ی جزئی، خط «نمره‌دهی: جزئی» را اضافه کنید.',
        ),
        *_example('2- کدام اعداد اول هستند؟', 'الف) 2\t\tب) 4\t\tج) 5\t\tد) 9', 'پاسخ: الف، ج', 'بارم: 2'),

        heading('۳. درست / نادرست'),
        *_guide('• گزینه ننویسید؛ فقط زیر سؤال بنویسید «پاسخ: درست» یا «پاسخ: نادرست».'),
        *_example('3- آب در فشار یک اتمسفر در دمای ۱۰۰ درجه‌ی سانتی‌گراد می‌جوشد.', 'پاسخ: درست'),

        heading('۴. پاسخ کوتاه'),
        *_guide(
            '• گزینه ننویسید. پاسخ را (یک کلمه یا عبارت کوتاه، حداکثر ۸ کلمه) در خط «پاسخ:» بنویسید.',
            '• اگر چند پاسخ درست است، آن‌ها را با خط عمودی | از هم جدا کنید.',
        ),
        *_example('4- فرمول شیمیایی آب چیست؟', 'پاسخ: H2O | اچ‌تواو'),

        heading('۵. پاسخ عددی'),
        *_guide(
            '• پاسخ را فقط به‌صورت عدد در خط «پاسخ:» بنویسید؛ سامانه آن را «پاسخ عددی» ثبت می‌کند.',
            '• اختیاری: «تلرانس:» مقدار خطای مجاز (عدد، یا درصد مثل 5%) و «واحد:» واحد پاسخ.',
            '• اگر پاسخ عدد است ولی می‌خواهید «پاسخ کوتاه» ثبت شود، خط «نوع: پاسخ کوتاه» را اضافه کنید.',
        ),
        *_example('5- شتاب جاذبه‌ی زمین چند متر بر مجذور ثانیه است؟', 'پاسخ: 9.8', 'تلرانس: 0.1', 'واحد: m/s²'),

        heading('۶. تشریحی'),
        *_guide(
            '• فقط متن سؤال را بنویسید، بدون خط «پاسخ:».',
            '• اختیاری: «پاسخ نمونه:» برای تصحیح‌کننده، و «قالب پاسخ:» (متن، تصویر، صوت، ویدئو یا فایل؛ اگر ننویسید: متن).',
        ),
        *_example('6- چرخه‌ی آب در طبیعت را توضیح دهید.', 'بارم: 5', 'دشواری: سخت',
                  'پاسخ نمونه: تبخیر، میعان، بارش و جاری شدن آب در زمین.'),

        heading('۷. جای خالی'),
        *_guide(
            '• جواب هر جای خالی را داخل کروشه [ ] در خود متن سؤال بنویسید؛ دانشجو به‌جای آن یک کادر خالی می‌بیند.',
            '• اگر برای یک جای خالی چند جواب قبول است، آن‌ها را با / جدا کنید.',
        ),
        *_example('7- پایتخت ایران [تهران] و پایتخت ترکیه [آنکارا / انکارا] است.'),

        heading('۸. تطبیقی (وصل کردنی)'),
        *_guide(
            '• زیر متن سؤال، هر جفت را در یک خط بنویسید: «مورد = جفت درست آن».',
            '• یا به‌جای این خط‌ها یک جدول دوستونه بگذارید، بدون ردیف عنوان: ستون اول مورد، ستون دوم جفت آن (نمونه‌ی دوم).',
            '• اختیاری: «گزینه‌های اضافی:» جواب‌های انحرافی که به هیچ موردی وصل نمی‌شوند.',
        ),
        *_example('8- هر کشور را به پایتخت آن وصل کنید.', 'ایران = تهران', 'فرانسه = پاریس', 'ژاپن = توکیو',
                  'گزینه‌های اضافی: رم، برلین'),
        *_example('9- هر عضو بدن را به کار آن وصل کنید.',
                  {'table': [['قلب', 'پمپاژ خون'], ['ریه', 'تبادل گازها'], ['کلیه', 'تصفیه‌ی خون']], 'header': False},
                  label='نمونه‌ی دوم — با جدول:'),

        heading('۹. مرتب‌سازی'),
        *_guide(
            '• موارد را مثل گزینه‌ها با «الف)»، «ب)»، … بنویسید (به هر ترتیبی).',
            '• در خط «ترتیب صحیح:» حروف موارد را به ترتیب درست بنویسید.',
            '• اگر موارد را از اول به ترتیب درست نوشته‌اید، به‌جای «ترتیب صحیح:» بنویسید «نوع: مرتب‌سازی».',
        ),
        *_example('10- مراحل رشد گیاه را به ترتیب مرتب کنید.', 'الف) جوانه زدن', 'ب) کاشت بذر', 'ج) گل دادن',
                  'د) رشد ساقه و برگ', 'ترتیب صحیح: ب، الف، د، ج'),

        heading('۱۰. ماتریسی (جدولی)'),
        *_guide(
            '• زیر متن سؤال یک جدول بگذارید. ردیف اول: عنوان ستون‌ها (خانه‌ی اولش را خالی بگذارید یا عنوانی بنویسید).',
            '• ستون اول: متن هر سطر. در خانه‌ی درست هر سطر علامت ✓ (یا *) بگذارید و بقیه‌ی خانه‌ها را خالی بگذارید.',
            '• اگر سطری بیش از یک ✓ داشته باشد، دانشجو در هر سطر می‌تواند چند خانه را انتخاب کند.',
        ),
        *_example('11- هر جانور در کدام محیط زندگی می‌کند؟',
                  {'table': [['جانور', 'خشکی', 'آب'], ['شیر', '✓', ''], ['نهنگ', '', '✓'], ['شتر', '✓', '']]}),

        heading('۱۱. تصویری (نشانه‌گذاری روی تصویر)'),
        *_guide(
            '• تصویر را زیر متن سؤال قرار دهید.',
            '• برای هر نقطه‌ای که دانشجو باید نامش را بنویسد، یک خط «نشانه شماره: پاسخ (x، y)» بنویسید.',
            '• x فاصله از لبه‌ی چپ تصویر و y فاصله از لبه‌ی بالای تصویر است، هر دو به درصد؛ مثلاً (50، 50) یعنی وسط تصویر.',
            '• اگر برای یک نشانه چند پاسخ قبول است، با ویرگول جدا کنید. اگر مختصات را ننویسید، پس از ثبت در ویرایش سؤال نشانه‌ها را روی تصویر جابه‌جا کنید.',
        ),
        *_example('12- نام شکل‌های مشخص‌شده روی تصویر را بنویسید.', {'image': sample_shapes_png(), 'width': 300, 'height': 180},
                  'نشانه 1: دایره (30، 50)', 'نشانه 2: مربع، چهارگوش (70، 50)'),

        heading('۱۲. تصویر در متن سؤال یا گزینه‌ها'),
        *_guide(
            '• تصویر را درست زیر خطی بگذارید که به آن تعلق دارد: زیر متن سؤال، تصویر سؤال می‌شود؛ زیر یک گزینه، تصویر همان گزینه.',
            '• برای گزینه‌ای که فقط تصویر است، فقط حرف گزینه را بنویسید (مثل «الف)») و تصویر را زیرش بگذارید.',
            '• قالب‌های قابل قبول: PNG، JPG، GIF و WEBP. تصویرهای EMF/WMF منتقل نمی‌شوند؛ آن‌ها را به PNG تبدیل کنید.',
            '• پاسخ این نمونه در «کلید پاسخ» انتهای فایل آمده است.',
        ),
        *_example('13- کدام شکل دایره است؟', 'الف)', {'image': _shape_png('square'), 'width': 90, 'height': 90},
                  'ب)', {'image': _shape_png('circle'), 'width': 90, 'height': 90}),

        heading('۱۳. صوتی / ویدئویی'),
        *_guide(
            '• Word فایل صوتی یا ویدئویی را در خود نگه نمی‌دارد؛ این فایل را جداگانه بارگذاری می‌کنید.',
            '• زیر متن سؤال بنویسید «نوع: صوتی» (یا «نوع: ویدئویی») و در خط بعد «فایل:» و نام دقیق فایل.',
            '• هنگام بارگذاری فایل Word، همان فایل را در کادر «فایل‌های همراه» هم انتخاب کنید (MP3، WAV، OGG، M4A، MP4 یا WEBM).',
            '• پاسخ این سؤال را استاد دستی تصحیح می‌کند. اختیاری: «قالب پاسخ:» (صوت، ویدئو یا متن؛ اگر ننویسید: صوت).',
        ),
        {'style': 'MQExample', 'text': 'نمونه (چون فایل صوتی همراه این فایل نیست، این نمونه در کادر راهنما آمده و ثبت نمی‌شود):'},
        {'style': 'MQCode', 'text': '14- به فایل صوتی گوش دهید و خلاصه‌ی آن را بیان کنید.'},
        {'style': 'MQCode', 'text': 'نوع: صوتی'},
        {'style': 'MQCode', 'text': 'فایل: listening1.mp3'},
        {'style': 'MQCode', 'text': 'قالب پاسخ: صوت'},

        heading('۱۴. کلید پاسخ در انتهای فایل (اختیاری)'),
        *_guide(
            '• اگر عادت دارید پاسخ‌ها را آخر برگه بنویسید، در آخر فایل یک خط «کلید پاسخ:» بنویسید و بعد شماره‌ی هر سؤال و حرف گزینه‌ی درست، مثل «کلید پاسخ: 1-ب 2-ج 3-الف».',
            '• کلید فقط برای سؤال‌هایی به کار می‌رود که پاسخشان در خود سؤال مشخص نشده است. بعد از کلید پاسخ، سؤال دیگری ننویسید.',
        ),
        *_example('کلید پاسخ: 13-ب', label='نمونه (پاسخ سؤال ۱۳):'),

        heading('اشتباه‌های رایج'),
        *_guide(
            '• سؤال بدون شماره، یا گزینه بدون «الف)» / «1)» ← سؤال یا گزینه تشخیص داده نمی‌شود.',
            '• گزینه‌ی درستِ سؤال تستی مشخص نشده ← آن سؤال با پیام «گزینه‌ی درست مشخص نشده» ثبت نمی‌شود.',
            '• توضیح یا عنوان بین سؤال‌ها با متن معمولی ← جزو هیچ سؤالی نیست و هنگام مرور کنار سؤال قبلی تذکر داده می‌شود.',
            '• ذخیره با پسوند قدیمی doc ← در Word از File ← Save As، قالب «Word Document» (پسوند docx) را انتخاب کنید.',
        ),
    ])
