"""Compact real benchmark results for OCI Run Command's bounded text output."""
import argparse
import json
from pathlib import Path


def summarize(report):
    options = report.get('options') or {}
    summary = {'architecture': report['host']['architecture'], 'mode': report['mode'],
               'ocr':options.get('ocr'), 'detector':options.get('detector'),
               'inpaint':options.get('inpaint'), 'upscale':options.get('upscale'), 'runs':[]}
    for run in report['runs']:
        # Older reports predate the explicit success field. A rendered image is
        # evidence of completion; a missing image must not become a fast result.
        success = run.get('success',bool(run.get('renderedImageBytes')))
        item = {'run':run['run'], 'success':success, 'seconds':run['wallSeconds'],
                'processTreeRssMiB':round(run['peakProcessTreeRssBytes']/1048576)}
        if success:
            item['stagesSeconds'] = {k.removesuffix('Ms'):round(v/1000,2) for k,v in (run.get('timings') or {}).items()}
            inpaint = run.get('inpaintRegions') or []
            item.update(regions=run.get('regions',0),lama=sum(r['method']=='lama' for r in inpaint),
                        fallback=sum(r['method']!='lama' for r in inpaint))
        else:
            item.update(errorType=run.get('errorType','unknown'),lastStage=run.get('lastStage','unknown'))
        summary['runs'].append(item)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(json.loads(args.report.read_text(encoding='utf-8'))),ensure_ascii=False,separators=(',',':')))
