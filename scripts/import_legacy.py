import argparse
from jm_workbench.core.config import Config
from jm_workbench.core.db import Store
from jm_workbench.services.configuration import Configuration
from jm_workbench.services.migrate import import_legacy

p=argparse.ArgumentParser(description='只读导入现有业务记录，原资料保留位置')
p.add_argument('--runtime',required=True)
p.add_argument('--profile',required=True)
p.add_argument('--home')
args=p.parse_args()
config=Config(args.home)
print(import_legacy(Configuration(config,Store(config.home/'jm.db')),args.runtime,args.profile))
