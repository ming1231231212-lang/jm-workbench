from fastapi import APIRouter
from .models import CommunityAccount, CommunityPost, LinkRecord, ResolveRecord, ClearRecord


def router(service):
    api=APIRouter(prefix='/api/community')

    @api.get('/state')
    def state():return service.state()

    @api.post('/accounts')
    def account(payload:CommunityAccount):return service.save_account(payload)

    @api.put('/accounts/{ident}')
    def edit_account(ident:str,payload:CommunityAccount):
        service.account(ident)
        return service.save_account(payload,ident)

    @api.post('/accounts/{ident}/check')
    def check(ident:str):return service.check_account(ident)

    @api.post('/accounts/{ident}/sync')
    def sync(ident:str):return service.sync_account(ident)

    @api.post('/accounts/{ident}/open')
    def open_account(ident:str):return service.open_account(ident)

    @api.post('/posts')
    def save(payload:CommunityPost):return service.save(payload)

    @api.put('/posts/{ident}')
    def edit(ident:str,payload:CommunityPost):return service.save(payload,ident)

    @api.post('/posts/{ident}/launch')
    def launch(ident:str):return service.launch(ident)

    @api.post('/posts/{ident}/{action}')
    def control(ident:str,action:str):return service.control(ident,action)

    @api.post('/jobs/{ident}/open')
    def open_job(ident:str):return service.open_job(ident)

    @api.post('/jobs/{ident}/record')
    def record(ident:str,payload:LinkRecord):return service.record_url(ident,payload.url)

    @api.post('/jobs/{ident}/resolve')
    def resolve(ident:str,payload:ResolveRecord):return service.resolve(ident,payload.outcome,payload.note,payload.url)

    @api.post('/risk/{platform}/clear')
    def clear(platform:str,payload:ClearRecord):return service.clear_risk(platform,payload.note)

    return api
