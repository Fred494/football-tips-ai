"""Official CAF qualifying fixtures for the November 2026 window."""
import html
import re

SOURCE = 'https://www.cafonline.com/afcon2025/news/crucial-matchdays-3-and-4-to-shape-totalenergies-caf-afcon-pamoja-2027-qualification-race/'
CODE = 'int.afconq'
ALIASES = {'Côte d’Ivoire': 'Ivory Coast', "Côte d'Ivoire": 'Ivory Coast',
           'Cabo Verde': 'Cape Verde', 'The Gambia': 'Gambia', 'Congo DR': 'DR Congo'}
NEUTRAL = {('Madagascar','Guinea-Bissau'), ('Benin','Central African Republic'),
           ('Eritrea','Guinea'), ('Lesotho','Gabon'), ('Sudan','Senegal'),
           ('Zimbabwe','Equatorial Guinea'), ('Niger','Morocco'),
           ('Central African Republic','Benin')}

def parse_afcon(page):
    rows = []
    for block in re.findall(r'<p\b[^>]*>(.*?)</p>', page, re.S):
        line = ' '.join(html.unescape(re.sub(r'<[^>]+>', '', block)).split())
        group = re.search(r'Group ([A-L]):', line)
        if not group:
            continue
        for m in re.finditer(r'(?:^|,\s*)([^,(]+?)\s+v\s+([^,(]+?)\s*\((\d{2})/11,\s*(\d{2})h(\d{2})\)', line[group.end():].strip()):
            home, away = (ALIASES.get(m[i].strip(),m[i].strip()) for i in (1,2))
            rows.append(dict(day='2026-11-'+m[3],home=home,away=away,league=CODE,
                             group=group[1],score=None,kickoffUTC=m[4]+':'+m[5],source=SOURCE,
                             neutral=(home,away) in NEUTRAL))
    unique = {(m['day'],m['home'],m['away']):m for m in rows}
    if len(unique)!=48:
        raise ValueError(f'Expected 48 CAF group fixtures, found {len(unique)}')
    return list(unique.values())
