from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import source_discovery
from player_catalog import choice

class DiscoveryCompletenessTests(unittest.TestCase):
    def test_all_exact_title_pages_are_inspected_instead_of_only_the_first_two(self):
        selected={'title':'Exact show','kind':'anime','year':2024,'ids':{'mal':'123'}}
        candidates=[{'title':'Exact show','kind':'anime','year':2024,'url':'https://catalog.example.com/show-'+str(i)} for i in range(7)]
        def inspect(url,**kwargs):
            return {'title':'Exact show','url':url,'year':2024,'dubs':[choice('Studio '+url[-1],'https://kodikplayer.com/serial/'+url[-1]+'/hash/720p')],'complete':True}
        with patch.object(source_discovery,'SITES',[SimpleNamespace(id='fixture',name='Fixture',kind='anime')]),patch.object(source_discovery,'search_site',return_value={'status':'ok','results':candidates}),patch.object(source_discovery,'inspect_source',side_effect=inspect) as parser:
            result=source_discovery.discover(selected,refresh=True)
        self.assertEqual(parser.call_count,7)
        self.assertEqual(len(result['voices']),7)
        self.assertTrue(result['complete'])

    def test_inspection_continuation_is_bound_to_the_owner_and_exact_selection(self):
        from fastapi import HTTPException
        import api
        api._inspection_states.clear()
        root='https://catalog.example.com/show'
        def inspect(url,**kwargs):
            state=kwargs['state'];state['steps']=state.get('steps',0)+1
            return {'pending':state['steps']==1,'complete':state['steps']>1,'scannedPages':state['steps']*128,'dubs':[]}
        with patch.object(api,'inspect_source',side_effect=inspect):
            first=api.source_inspect(api.Inspection(url=root),subject='owner-one')
            token=first['continuation']
            with self.assertRaises(HTTPException):api.source_inspect(api.Inspection(url=root,continuation=token),subject='owner-two')
            with self.assertRaises(HTTPException):api.source_inspect(api.Inspection(url='https://other.example.com/show',continuation=token),subject='owner-one')
            final=api.source_inspect(api.Inspection(url=root,continuation=token),subject='owner-one')
        self.assertTrue(final['complete']);self.assertNotIn('continuation',final)
        self.assertNotIn(token,api._inspection_states)

    def test_explicit_refresh_sees_new_studios_while_continuation_reuses_complete_sources(self):
        selected={'title':'Refresh show','kind':'anime','year':2024}
        candidate={'title':'Refresh show','kind':'anime','year':2024,'url':'https://catalog.example.com/refresh-show'}
        count=[1]
        def inspect(url,**kwargs):
            return {**candidate,'dubs':[choice('Studio '+str(i),'https://kodikplayer.com/serial/'+str(i)+'/hash/720p') for i in range(count[0])],'complete':True}
        with patch.object(source_discovery,'SITES',[SimpleNamespace(id='fixture',name='Fixture',kind='anime')]),patch.object(source_discovery,'search_site',return_value={'status':'ok','results':[candidate]}),patch.object(source_discovery,'inspect_source',side_effect=inspect) as parser:
            first=source_discovery.discover(selected,refresh=True)
            count[0]=2
            continued=source_discovery.discover(selected,refresh=True,continuing=True)
            refreshed=source_discovery.discover(selected,refresh=True)
        self.assertEqual(len(first['voices']),1);self.assertEqual(len(continued['voices']),1)
        self.assertEqual(len(refreshed['voices']),2);self.assertEqual(parser.call_count,2)
