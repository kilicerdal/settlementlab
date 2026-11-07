"""Run layered controls and shipped acceptance scenarios with portable reports."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import platform
import sys
import time
import unittest
from .scenarios import catalog,run_scenario
from .reporting import write_reports
from ..configuration import Settings


class EvidenceResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.cases=[];self.current={}
    def startTest(self,test):
        super().startTest(test);self.started=time.perf_counter();self.current=dict(id=test.id(),suite=test.id().split('.')[1],status='passed')
    def addFailure(self,test,error):
        super().addFailure(test,error);self.current.update(status='failed',detail=self._exc_info_to_string(error,test))
    def addError(self,test,error):
        super().addError(test,error);self.current.update(status='failed',detail=self._exc_info_to_string(error,test))
    def addSubTest(self,test,subtest,error):
        super().addSubTest(test,subtest,error)
        if error:self.current.update(status='failed',detail=self._exc_info_to_string(error,test))
    def addSkip(self,test,reason):
        super().addSkip(test,reason);self.current.update(status='skipped',detail=reason)
    def addExpectedFailure(self,test,error):
        super().addExpectedFailure(test,error);self.current.update(status='skipped',detail='Expected failure')
    def addUnexpectedSuccess(self,test):
        super().addUnexpectedSuccess(test);self.current.update(status='failed',detail='Unexpected success')
    def stopTest(self,test):
        self.current['duration']=time.perf_counter()-self.started;self.cases.append(self.current);super().stopTest(test)


def run(suite,root,report_directory):
    cases=[];start=time.perf_counter();setup_error=None
    try:
        if suite!='scenarios':
            directory=Path(root)/'tests'
            if not directory.is_dir():raise ValueError('Core suites require a source checkout; use --root or --suite scenarios')
            selected=['unit','integration','api'] if suite in ('all','core') else [suite]
            tests=unittest.TestSuite()
            for layer in selected:tests.addTests(unittest.defaultTestLoader.discover(str(directory/layer),top_level_dir=str(Path(root).resolve())))
            result=unittest.TextTestRunner(verbosity=1,resultclass=EvidenceResult).run(tests)
            cases.extend(result.cases)
        if suite in ('all','scenarios'):
            for spec in catalog():cases.append(run_scenario(spec))
    except Exception as error:
        setup_error=str(error);cases.append(dict(id='runner.setup',suite='runner',status='failed',detail=setup_error,duration=0))
    if not cases:cases.append(dict(id='runner.empty',suite='runner',status='failed',duration=0,detail='No cases executed'))
    report=dict(version=1,generated_at=datetime.now(timezone.utc).isoformat(),python=platform.python_version(),
                status='failed' if not cases or any(c['status']=='failed' for c in cases) else 'passed',
                duration=time.perf_counter()-start,cases=cases)
    write_reports(report,report_directory)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description='SettlementLab assurance runner')
    parser.add_argument('--suite',choices=['all','core','unit','integration','api','scenarios'],default='all')
    parser.add_argument('--root',default='.')
    parser.add_argument('--report-dir')
    parser.add_argument('--config')
    args=parser.parse_args(argv);settings=Settings.load(args.config)
    report=run(args.suite,args.root,args.report_dir or settings.reports)
    print(report['status'].upper()+': '+str(len(report['cases']))+' cases; reports in '+str(args.report_dir or settings.reports))
    return 0 if report['status']=='passed' else 1

if __name__=='__main__':sys.exit(main())
