"""Explicit read-only replay environment v1; never patches historical modules.

Historical CPython 3.12 floating sums used compensated arithmetic. Execute the
unchanged, hash-pinned function code in isolated module namespaces with that
arithmetic made explicit. No tolerance, rounding, expected-output substitution,
process-wide builtin patch, source rewrite, or model-policy change is involved.
"""
from __future__ import annotations

import csv
import hashlib
import importlib
import io
import math
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'historical-replay-compat-v1'
LEGACY_CODE_SHA256 = {
    'scripts/build_week7_postgame_audit.py': 'e39aa8a4a11b51c725b991c1217f3119f71758c7767a044f5c5c0347121f396a',
    'scripts/build_week8_postgame_audit.py': 'e6751ae6d7a4e9b5c56ae3cdf718aed783d338e5d4dae5407cb5050a4b0d8ac6',
    'scripts/research_week7_acceptance.py': '740d479e604b0c672035f38fc7befe11c38dee7e3ce5175d4aeac7ea80280df9',
    'scripts/research_week8_diagnostics.py': '800c52f9d5cad585fc8a249ed192ae2aedc5bda3d864688c20a79f648b3e0d16',
    'scripts/week8_numerical_research.py': 'b1a0403fc968dc80d5b66ccfbe9568837a55984a94f5083db9a69b278bf5131f',
    'scripts/verify_week7_audit_integrity.py': '4e7cf90cbbee2c1e3cc1f3ede800f2849c22d67febba11407f51a4feb1cdbf89',
}

def compensated_sum(values, start=0):
    """Finite int/bool/float CPython-3.12 sum semantics, explicit on every runtime.

    Neumaier correction is applied to float terms, preserving exact integer
    counting and the historical treatment of integer terms in a floating sum.
    Unsupported inputs and overflow fail closed; this is not a general sum API.
    """
    if type(start) not in (int, float, bool) or not math.isfinite(start):
        raise ValueError('unsupported replay summation start')
    total=start; correction=0.0
    for value in values:
        if type(value) not in (int, float, bool) or not math.isfinite(value):
            raise ValueError('unsupported or nonfinite replay summation term')
        if type(total) in (int,bool):
            total+=value
        elif type(value) in (int,bool):
            total+=value
        else:
            updated=total+value
            correction += (total-updated)+value if abs(total)>=abs(value) else (value-updated)+total
            total=updated
        if not math.isfinite(total) or not math.isfinite(correction):
            raise ValueError('replay summation overflow')
    return total+correction if correction else total

def verify_legacy_code():
    for name,expected in LEGACY_CODE_SHA256.items():
        actual=hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        if actual!=expected:raise ValueError('protected legacy code changed: '+name)

def clone(name):
    """Reuse original function bytecode with isolated globals, never sys.modules."""
    original=importlib.import_module('scripts.'+name)
    module=types.ModuleType('replay_compat_v1.'+name)
    module.__dict__.update(original.__dict__)
    for key,value in vars(original).items():
        if isinstance(value,types.FunctionType) and value.__module__==original.__name__:
            fn=types.FunctionType(value.__code__,module.__dict__,value.__name__,value.__defaults__,value.__closure__)
            fn.__kwdefaults__=value.__kwdefaults__;fn.__annotations__=value.__annotations__
            module.__dict__[key]=fn
    module.sum=compensated_sum
    return module

def initialize():
    verify_legacy_code()
    prior=clone('research_week7_acceptance')
    w7=clone('build_week7_postgame_audit')
    w8=clone('build_week8_postgame_audit')
    cross=clone('research_week8_diagnostics');cross.prior=prior
    numeric=clone('week8_numerical_research');numeric.load_modern=prior.load_modern
    gate=clone('verify_week7_audit_integrity');gate.replay=w7;gate.research=prior
    # The original payload builder contains a function-local import of the
    # historical cross-week module. Spell out the identical serialization here
    # so it calls the isolated compatibility module, without altering imports.
    def payloads():
        data,tables=w8.evaluate();analysis=cross.analyze(tables)
        result={'week8_diagnostics.json':w8.serialized(data),'cross_week_diagnostics.json':w8.serialized(analysis),
                'week8_postgame_report.md':w8.report(data,tables).encode(),
                'cross_week_tables.md':cross.markdown(analysis).encode()}
        for name,rows in tables.items():
            fields=list(dict.fromkeys(k for row in rows for k in row));stream=io.StringIO(newline='')
            writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)
            result[name]=stream.getvalue().encode()
        return data,result
    w8.payloads=payloads
    return prior,w7,w8,cross,numeric,gate

research,week7,week8,cross_week,week8_research,strict = initialize()
