"""smoke_e2e.py 를 unittest 발견(discover) 대상으로 노출하는 래퍼.

    python3 -m unittest discover -s tests -p 'test_smoke*.py'
    python3 tests/smoke_e2e.py            # 직접 실행해도 같은 시험
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from smoke_e2e import SmokeE2E  # noqa: E402,F401
