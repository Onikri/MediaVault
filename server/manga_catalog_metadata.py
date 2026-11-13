"""Fetch source-provided catalogue facts, without requesting chapter pages/images."""
from manga_source_tags import from_api
from source_parser import SourceError


def enrich(row):
    from suwayomi_bridge import Client, parse_reference
    url=row.get('url') or row.get('sourceUrl') or ''
    reference=parse_reference(url)
    if reference:
        manga,_,_=reference
        client=Client()
        try:
            data=client.get(f'/manga/{manga}?onlineFetch=true',timeout=35)
        finally:client.close()
        expected=str(row.get('sourceId') or row.get('provider','').split(':')[-1])
        if data.get('sourceId') is not None and str(data['sourceId'])!=expected:
            raise SourceError('Источник метаданных не совпадает с записью каталога.')
        from manga_discovery import public_aliases
        return {**row,**from_api(data),'title':data.get('title') or row['title'],
                'description':data.get('description') or row.get('description',''),
                'aliases':public_aliases(data),'metadataInspected':True}
    # These adapters read a title and its chapter listing. They return image
    # addresses only when given a chapter; catalogue entries use title URLs.
    from manga_sources import site_for
    from manga_inspection import inspect
    if not site_for(url):raise SourceError('Для этого источника пока нет адаптера метаданных.')
    detail=inspect(url)
    if detail.get('pages'):raise SourceError('Для каталога нужна карточка произведения, а не страница главы.')
    return {**row,**detail,'metadataInspected':True}
