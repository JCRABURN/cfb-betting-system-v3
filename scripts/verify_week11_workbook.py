"""Read-only OOXML check of the delivered workbook against the audit ledger."""
from __future__ import annotations

import json
import math
import posixpath
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/2026-week11-postgame-audit'
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def verify(path: Path = OUT/'deliverables/season-performance.xlsx') -> dict:
    findings = json.loads((OUT/'v1/audit_findings.json').read_bytes())
    with ZipFile(path) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            for item in ET.fromstring(archive.read('xl/sharedStrings.xml')):
                strings.append(''.join(x.text or '' for x in item.iterfind('.//s:t', NS)))
        relations = {r.attrib['Id']: r.attrib['Target'] for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        sheets = {}
        for sheet in ET.fromstring(archive.read('xl/workbook.xml')).findall('s:sheets/s:sheet', NS):
            target = relations[sheet.attrib[REL]]
            target = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
            cells = {}
            for cell in ET.fromstring(archive.read(target)).iterfind('.//s:sheetData/s:row/s:c', NS):
                kind = cell.get('t'); raw = cell.findtext('s:v', default='', namespaces=NS)
                if kind == 'e':
                    raise ValueError(f"Workbook error {sheet.attrib['name']}!{cell.get('r')}: {raw}")
                if kind == 's': value = strings[int(raw)]
                elif kind == 'inlineStr': value = ''.join(t.text or '' for t in cell.iterfind('.//s:t',NS))
                elif kind in ('str','d'): value = raw
                else: value = float(raw) if raw else None
                cells[cell.attrib['r']] = (value, cell.findtext('s:f',namespaces=NS))
            sheets[sheet.attrib['name']] = cells
    if len(sheets) != 44:
        raise ValueError('Expected 44 worksheets')
    for name, expected in {'All 621 games':621,'PDF export source':621,'External records':5,
                           'W11 ATS':64,'W11 totals':64,'Research predictions':610,'Pregame vs observed':49}.items():
        count=sum(address.startswith('A') and address[1:].isdigit() and int(address[1:])>=6
                  and value[0] is not None for address,value in sheets[name].items())
        if count!=expected:raise ValueError('Workbook table coverage differs: '+name)
    for i,row in enumerate(findings['season_contest']['finals'],6):
        if sheets['All 621 games'][f'C{i}'][0]!=row['game_id']:
            raise ValueError('Reconciled game ID changed in workbook')
    ledger = sheets['Actual v3 picks']
    for i, row in enumerate(findings['season_contest']['ledger'], 6):
        for column, expected in zip('LMNO', [row['grading_margin'],row['result'],row['weighted_points'],row['units_minus110']]):
            observed, formula = ledger[f'{column}{i}']
            if not formula or (not math.isclose(observed,expected,abs_tol=1e-8) if isinstance(expected,(int,float)) else observed != expected):
                raise ValueError(f'Workbook grade/cache differs: {column}{i}')
        if str(ledger[f'C{i}'][0]) != str(row['game_id']):
            raise ValueError('Provider game ID no longer stored as exact text')
    for column, expected in zip('ABCDEF', [50,20,30,0,55,-130/11]):
        value, formula = sheets['Dashboard'][column+'6']
        if not formula or not math.isclose(value,expected,abs_tol=1e-8):
            raise ValueError('Headline formula/cache differs')
    return dict(status='VERIFIED_READ_ONLY',sheets=len(sheets),graded_rows=50,formula_errors=0,
                native_excel_open_test=False,authoring_engine='bundled @oai/artifact-tool')


if __name__ == '__main__':
    print(json.dumps(verify()))
