import json,sys,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from fastapi import HTTPException
from youtube_auth import normalize_cookies

FUTURE=time.time()+86400*30
EDIT_THIS_COOKIE=[
 {'domain':'.youtube.com','expirationDate':FUTURE,'hostOnly':False,'httpOnly':True,'name':'SID','path':'/','sameSite':'unspecified','secure':False,'session':False,'storeId':'0','value':'sid-value','id':1},
 {'domain':'.youtube.com','expirationDate':FUTURE,'hostOnly':False,'httpOnly':True,'name':'__Secure-3PSID','path':'/','secure':True,'session':False,'value':'psid'},
 {'domain':'www.youtube.com','hostOnly':True,'httpOnly':False,'name':'PREF','path':'/','secure':True,'session':True,'value':'f6=40000000'},
 {'domain':'.google.com','expirationDate':FUTURE,'name':'SID','path':'/','secure':False,'value':'google-must-not-be-stored'},
 {'domain':'.youtube.com','expirationDate':time.time()-60,'name':'OLD','path':'/','secure':False,'value':'expired'},
]


class CookieFormats(unittest.TestCase):
    def test_editthiscookie_json_becomes_youtube_only_netscape(self):
        text=normalize_cookies(json.dumps(EDIT_THIS_COOKIE))
        lines=text.strip().split('\n')
        self.assertEqual(lines[0],'# Netscape HTTP Cookie File')
        rows=[l.split('\t') for l in lines[1:]]
        self.assertEqual({r[5] for r in rows},{'SID','__Secure-3PSID','PREF'})
        self.assertNotIn('google-must-not-be-stored',text)
        self.assertNotIn('expired',text)
        self.assertEqual(rows[0][:4],['.youtube.com','TRUE','/','FALSE'])

    def test_cookie_editor_object_and_bom(self):
        text=normalize_cookies('﻿'+json.dumps({'cookies':EDIT_THIS_COOKIE[:2]}))
        self.assertIn('sid-value',text)

    def test_unauthenticated_or_broken_exports_are_clear_errors(self):
        with self.assertRaises(HTTPException) as caught:normalize_cookies(json.dumps(EDIT_THIS_COOKIE[2:]))
        self.assertIn('авторизованной',caught.exception.detail)
        with self.assertRaises(HTTPException):normalize_cookies('[not json')
        with self.assertRaises(HTTPException) as caught:normalize_cookies('hello')
        self.assertIn('EditThisCookie',caught.exception.detail)


class Bloated(unittest.TestCase):
    def test_hundreds_of_page_state_cookies_are_dropped_not_rejected(self):
        noise=[{'domain':'.youtube.com','name':'ST-'+str(i)+'abc','path':'/','secure':False,'session':True,'value':'s'} for i in range(450)]
        noise+=[{'domain':'.youtube.com','name':'_ga_X'+str(i),'path':'/','session':True,'value':'g'} for i in range(20)]
        text=normalize_cookies(json.dumps(EDIT_THIS_COOKIE[:2]+noise))
        self.assertNotIn('ST-',text);self.assertNotIn('_ga',text);self.assertIn('sid-value',text)


if __name__=='__main__':unittest.main()
