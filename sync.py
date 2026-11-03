"""VyatSU group schedule -> subscribable Apple Calendar (.ics)."""
from __future__ import annotations
import hashlib, io, json, re, sys
from datetime import datetime, date, timedelta
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
import pdfplumber
from icalendar import Calendar, Event

SOURCE = 'https://old.vyatsu.ru/studentu-1/spravochnaya-informatsiya/raspisanie-zanyatiy-dlya-studentov.html'
GROUP = 'МНб-3601-02-00'
TZ = ZoneInfo('Europe/Moscow')
TIME_RE = re.compile(r'(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})')
DATE_RE = re.compile(r'\b(\d{2})(\d{2})(20\d{2})\b')
ROOM_RE = re.compile(r'\b\d{1,2}-\d{2,4}[_/]?\b')
TYPES = ('Лабораторная работа', 'Практическое занятие', 'Лекция', 'Семинар')


def discover_pdfs(session):
    resp = session.get(SOURCE, timeout=40); resp.raise_for_status()
    soup = BeautifulSoup(resp.content, 'html.parser')
    found = {}
    # Table rows contain a group label and multiple period links.
    for tr in soup.find_all('tr'):
        if GROUP not in tr.get_text(' ', strip=True):
            continue
        for a in tr.find_all('a', href=True):
            url = urljoin(SOURCE, a['href'])
            if '/reports/schedule/Group/' not in url or not url.lower().endswith('.pdf'):
                continue
            m = re.search(r'_(\d{8})_(\d{8})\.pdf', url)
            if m:
                start = datetime.strptime(m.group(1), '%d%m%Y').date()
                found[start] = url
    if not found:
        raise ValueError('No PDF links found for group; university page layout may have changed')
    return dict(sorted(found.items()))


def select_cell(raw):
    raw = re.sub(r'\s+', ' ', raw).strip()
    if not raw:
        return None
    if 'Элективные дисциплины' in raw or 'физической культуре' in raw:
        # Several parallel options appear inside the same time slot.
        parts = re.split(r'(?='+re.escape(GROUP)+r',\s*0[12]\s*подгруппа)', raw)
        selected = [p for p in parts if '01 подгруппа' in p and re.search(r'Боков\s+А\.?\s*В\.?', p, re.I)]
        if not selected:
            return None
        raw = selected[0]
        raw = re.sub(r'^.*?01\s*подгруппа\s*', '', raw, count=1)
    elif '02 подгруппа' in raw and '01 подгруппа' not in raw:
        return None
    kind = next((k for k in TYPES if k in raw), 'Занятие')
    room = ROOM_RE.findall(raw)
    teacher = re.search(r'([А-ЯЁ][а-яё-]+\s+[А-ЯЁ]\.\s*[А-ЯЁ]\.)', raw)
    title = raw.split(kind, 1)[0].strip(' ,.-') if kind != 'Занятие' else raw
    if 'Элективные дисциплины' in title:
        title = 'Физическая культура'
    if not title or len(title) > 180:
        return None
    return {'title':title, 'kind':kind, 'teacher':teacher.group(1) if teacher else '', 'room':room[-1].rstrip('_') if room else '', 'raw':raw}


def extract_pdf(data, start):
    """Read one PDF. University uses 7 time rows per day, 14 days across 4 pages."""
    events = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        day_offset = 0
        for page in pdf.pages:
            # Use text-line geometry: seven lesson slots per day; dates appear rotated.
            words = page.extract_words(x_tolerance=2, y_tolerance=3)
            times = []
            for w in words:
                if w['x0'] > page.width * .34:
                    continue
                match = TIME_RE.fullmatch(w['text'].replace('–','-'))
                if match:
                    times.append((float(w['top']), float(w['bottom']), match.group(1), match.group(2)))
            times.sort()
            if not times or len(times) % 7:
                raise ValueError(f'Unexpected timetable grid: {len(times)} time slots on page')
            for index, (top, bottom, begin, end) in enumerate(times):
                # The time label top is the top edge of its table row; next row starts after it.
                next_top = times[index+1][0] if index+1 < len(times) else page.height - 30
                # In long elective slots the text wraps, so use table horizontal rules when possible.
                horizontal = sorted({round(l['top'], 1) for l in page.lines if abs(l['y1']-l['y0']) < 1 and l['x1']-l['x0'] > page.width*.55})
                before = max((y for y in horizontal if y <= top+3), default=top-2)
                after = min((y for y in horizontal if y > top+3), default=next_top)
                cell = page.crop((page.width*.245, max(0,before+0.3), page.width*.95, min(page.height,after-0.3))).extract_text(x_tolerance=2, y_tolerance=3) or ''
                lesson = select_cell(cell)
                if not lesson:
                    continue
                lesson_date = start + timedelta(days=day_offset + index//7)
                events.append({**lesson, 'date':lesson_date, 'begin':begin, 'end':end})
            day_offset += len(times)//7
        if day_offset != 14:
            raise ValueError(f'Expected 14 days, got {day_offset}')
    return events


def make_ics(lessons):
    cal = Calendar(); cal.add('prodid','-//VyatSU Calendar Sync//RU'); cal.add('version','2.0')
    cal.add('x-wr-calname',f'ВятГУ · {GROUP} · 1 подгруппа')
    cal.add('x-wr-timezone','Europe/Moscow')
    now = datetime.now(TZ)
    for x in lessons:
        event = Event()
        event.add('summary', x['title'])
        event.add('dtstart',datetime.combine(x['date'],datetime.strptime(x['begin'],'%H:%M').time(),TZ))
        event.add('dtend',datetime.combine(x['date'],datetime.strptime(x['end'],'%H:%M').time(),TZ))
        event.add('dtstamp',now)
        key = f"{GROUP}|{x['date']}|{x['begin']}|{x['title']}|{x['kind']}"
        event.add('uid',hashlib.sha256(key.encode()).hexdigest()[:24]+'@vyatsu-calendar.local')
        event.add('description',f"{x['kind']}\nПреподаватель: {x['teacher']}\nАудитория: {x['room']}\nГруппа: {GROUP}, 01 подгруппа\nИсточник: {SOURCE}")
        if x['room']:
            event.add('location',x['room'])
        cal.add_component(event)
    return cal.to_ical()


def main():
    session = requests.Session(); session.headers['User-Agent'] = 'VyatSU-CalendarSync/0.1 (personal academic calendar)'
    pdfs = discover_pdfs(session)
    today = date.today()
    # Keep already published periods, including recent history, to avoid disappearing past events.
    lessons = []
    for start, url in pdfs.items():
        if start < today-timedelta(days=120):
            continue
        response = session.get(url,timeout=50); response.raise_for_status()
        extracted = extract_pdf(response.content,start)
        if not extracted:
            raise ValueError(f'No lessons parsed: {url}; refusing to overwrite calendar')
        lessons.extend(extracted)
        print(start, len(extracted), url)
    if not lessons:
        raise ValueError('No current periods found; refusing to overwrite calendar')
    unique = {(e['date'],e['begin'],e['title'],e['kind']):e for e in lessons}
    Path('calendar.ics').write_bytes(make_ics(sorted(unique.values(),key=lambda x:(x['date'],x['begin']))))
    print('Wrote',len(unique),'lessons')

if __name__ == '__main__':
    main()
