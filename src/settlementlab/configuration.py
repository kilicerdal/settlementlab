"""Strict configuration with defaults < JSON file < environment < CLI overrides."""
import json
import os
from dataclasses import dataclass,asdict
from pathlib import Path
from .core.validation import DomainError


@dataclass(frozen=True)
class Settings:
    database: str='settlementlab.db'
    port: int=8080
    model: str='qwen2.5:3b'
    reports: str='artifacts/reports'
    business_date: str=''
    calendar_id: str='weekday-v1'
    closed_dates: tuple=()

    def __post_init__(self):
        from .core.calendar import FixedClock,BusinessCalendar
        if not isinstance(self.business_date,str):raise DomainError("Business date must be a string")
        if self.business_date:FixedClock(self.business_date)
        BusinessCalendar(self.calendar_id,self.closed_dates)
        if isinstance(self.port,bool) or not isinstance(self.port,int) or not 0<=self.port<=65535:
            raise DomainError('Port must be an integer from 0 to 65535')
        for field in ('database','reports'):
            value=getattr(self,field)
            if not isinstance(value,str) or not value.strip():
                raise DomainError(field+' must be a nonempty path')
        if self.database==':memory:':
            raise DomainError('Use a temporary database file; transactions use separate connections')
        if not isinstance(self.model,str):
            raise DomainError('Model must be a string; empty disables local AI')

    @classmethod
    def load(cls, path=None, environ=None, **overrides):
        values=asdict(cls());env=os.environ if environ is None else environ
        if path:
            try:
                supplied=json.loads(Path(path).read_text())
            except (OSError,ValueError) as error:
                raise DomainError('Cannot read configuration: '+str(error))
            if not isinstance(supplied,dict) or set(supplied)-set(values):
                raise DomainError('Configuration has unknown fields or is not an object')
            values.update(supplied)
        for key,name in [('database','SETTLEMENTLAB_DB'),('port','SETTLEMENTLAB_PORT'),('model','SETTLEMENTLAB_MODEL'),('reports','SETTLEMENTLAB_REPORTS'),('business_date','SETTLEMENTLAB_BUSINESS_DATE')]:
            if name in env:
                try:values[key]=int(env[name]) if key=='port' else env[name]
                except (TypeError,ValueError):raise DomainError('Invalid '+name)
        values.update({key:value for key,value in overrides.items() if value is not None})
        return cls(**values)
