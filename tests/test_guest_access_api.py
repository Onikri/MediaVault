import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from fastapi import HTTPException
import api


class FakeStore:
    def __init__(self,record):self.record=record
    def setting(self,name,value=None):return self.record if name=='guest:g1' else None


class GuestGuard(unittest.TestCase):
    def test_owner_is_never_limited_and_guest_only_sees_opened_titles(self):
        record={'id':'g1','access':{'scope':'titles','watch':True,'read':True,'titles':[{'key':'anime:34599'}]}}
        with patch.object(api,'store',FakeStore(record)):
            api.guest_may_open('owner-sub',{'kind':'anime','ids':{'mal':'1'}})
            api.guest_may_open('guest:g1',{'kind':'anime','ids':{'mal':'34599'}})
            with self.assertRaises(HTTPException) as caught:api.guest_may_open('guest:g1',{'kind':'anime','ids':{'mal':'54250'}})
            self.assertEqual(caught.exception.status_code,403)
        with patch.object(api,'store',FakeStore({'id':'g1'})):
            api.guest_may_open('guest:g1',{'kind':'anime','ids':{'mal':'54250'}})


if __name__=='__main__':unittest.main()
