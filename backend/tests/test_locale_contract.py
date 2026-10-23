from __future__ import annotations

import json
import unittest

from fastapi import HTTPException

from backend.app.main import _api_error_code, api_http_exception


class LocaleErrorContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_conflict_has_stable_code_and_preserves_detail(self):
        detail = "Road reports changed after the route preview; calculate the route again"
        response = await api_http_exception(None, HTTPException(409, detail))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.body), {"detail": detail, "code": "ROUTE_PREVIEW_STALE"})

    def test_archived_action_has_stable_code(self):
        self.assertEqual(_api_error_code("Planning records are archived", 410), "ARCHIVED_ACTION")
