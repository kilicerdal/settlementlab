"""Portable machine-readable and human-readable evidence from actual runs."""
import html
import json
from pathlib import Path
from xml.etree.ElementTree import Element,SubElement,ElementTree


def write_reports(report,directory):
    output=Path(directory);output.mkdir(parents=True,exist_ok=True)
    (output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    cases=report['cases'];failures=sum(c['status']=='failed' for c in cases)
    suite=Element('testsuite',name='SettlementLab assurance',tests=str(len(cases)),failures=str(failures),time=str(report['duration']))
    for case in cases:
        entry=SubElement(suite,'testcase',classname=case['suite'],name=case['id'],time=str(case['duration']))
        if case['status']=='failed':SubElement(entry,'failure',message=case.get('detail','Failed')).text=case.get('detail','Failed')
        if case['status']=='skipped':SubElement(entry,'skipped')
    ElementTree(suite).write(output/'junit.xml',encoding='utf-8',xml_declaration=True)
    rows=[]
    for case in cases:
        details=html.escape(case.get('detail',''))
        steps=''.join('<li>'+html.escape(str(step['index'])+' / '+step['action']+' / '+step['status'])+'</li>' for step in case.get('steps',[]))
        rows.append('<tr><td>'+html.escape(case['suite'])+'</td><td>'+html.escape(case['id'])+'</td><td class="'+case['status']+'">'+case['status']+'</td><td>'+format(case['duration'],'.3f')+'s</td><td><details><summary>Evidence</summary><pre>'+details+'</pre><ol>'+steps+'</ol></details></td></tr>')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SettlementLab assurance report</title><style>body{background:#0a111c;color:#dbe6ef;font:14px/1.6 system-ui;margin:40px auto;padding:0 24px;max-width:1250px}h1{font-size:36px;color:#a3dfca}.passed{color:#a3dfca}.failed{color:#f0ad91}.skipped{color:#d9c788}table{border-collapse:collapse;width:100%}td,th{padding:12px;text-align:left;border-bottom:1px solid #304050}pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer}.scroll{overflow:auto}small{color:#9baebe}</style><h1>SettlementLab / Assurance evidence</h1>'''
    page+='<p>'+html.escape(report['status'].upper())+' · '+str(len(cases))+' cases · '+str(failures)+' failed</p><small>'+html.escape(report['generated_at'])+' · Python '+html.escape(report['python'])+'</small><p>This report records executed controls and scenarios. It is not a model-accuracy or production-readiness claim.</p><div class="scroll"><table><thead><tr><th>Suite</th><th>Case</th><th>Status</th><th>Duration</th><th>Details</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div></html>'
    (output/'index.html').write_text(page)
    return output/'index.html'
