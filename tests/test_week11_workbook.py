"""Reject changed formula caches, dropped rows and workbook formula errors."""
from zipfile import ZipFile
import xml.etree.ElementTree as ET
import pytest
from scripts.verify_week11_workbook import OUT, NS, verify


@pytest.mark.parametrize('mutation',['cache','error','missing_row'])
def test_corrupt_workbook_rejected(tmp_path,mutation):
    target=tmp_path/'corrupt.xlsx'
    with ZipFile(OUT/'deliverables/season-performance.xlsx') as src,ZipFile(target,'w') as dst:
        for item in src.infolist():
            raw=src.read(item.filename)
            if item.filename=='xl/worksheets/sheet2.xml':
                root=ET.fromstring(raw)
                if mutation=='missing_row':
                    data=root.find('s:sheetData',NS)
                    data.remove(next(r for r in data if r.get('r')=='6'))
                else:
                    cell=next(c for c in root.iterfind('.//s:c',NS) if c.get('r')=='N6')
                    cell.find('s:v',NS).text='999' if mutation=='cache' else '#REF!'
                    if mutation=='error':cell.set('t','e')
                raw=ET.tostring(root)
            dst.writestr(item,raw)
    with pytest.raises((ValueError,KeyError)):verify(target)
