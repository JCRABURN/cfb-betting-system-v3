import pytest
from scripts.verify_week12_integration import inherited_changes,protected_inventory

@pytest.mark.parametrize('path',[
    'outputs/2026-week11-postgame-audit/v2/audit_manifest.json',
    'data/ingest/2026-week12-splashsports/original.pdf',
    'outputs/2026-week12-delivery/initial-seal.json',
    'models/approved-model.py',
])
def test_inherited_evidence_cannot_change_or_disappear(path):
    assert inherited_changes({path:'original'},{path:'modified'})==[path]
    assert inherited_changes({path:'original'}, {})==[path]

def test_new_receipts_do_not_rewrite_parent_inventory():
    assert inherited_changes({'original':'same'},{'original':'same','new_receipt':'new'})==[]

def test_inventory_freezes_evidence_without_freezing_unrelated_application_code():
    tree={'outputs/history.json':'evidence','data/ingest/source.pdf':'source',
          'production-weeks/locked.csv':'locked','application.py':'code',
          '.github/workflows/ci.yml':'ci','.gitattributes':'attributes'}
    assert protected_inventory(tree)=={key:tree[key] for key in
        ('outputs/history.json','data/ingest/source.pdf','production-weeks/locked.csv')}
