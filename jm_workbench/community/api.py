from fastapi import APIRouter, Query
from fastapi.responses import Response
from .models import CommunityAccount, CommunityPost, LinkRecord, ResolveRecord, ClearRecord, DailyPlan, BackfillInput,NativeBindInput


def router(service):
    api=APIRouter(prefix='/api/community')

    @api.get('/state')
    def state():return service.state()

    @api.post('/backfill/preview')
    def backfill_preview(payload:BackfillInput):
        return {'items':service.backfill.preview(payload.plan_ids,payload.through_day,payload.replies_per_day)}

    @api.post('/backfill/register')
    def backfill_register(payload:BackfillInput):
        return service.backfill.register(payload.plan_ids,payload.through_day,payload.replies_per_day)

    @api.post('/backfill/{ident}/prepare')
    def backfill_prepare(ident:str):
        return service.backfill.prepare(ident)

    @api.post('/backfill/{ident}/queue')
    def backfill_queue(ident:str):
        return service.backfill.queue(ident)

    @api.post('/plans')
    def save_plan(payload:DailyPlan):return service.daily.save(payload)

    @api.put('/plans/{ident}')
    def edit_plan(ident:str,payload:DailyPlan):return service.daily.save(payload,ident)

    @api.post('/plans/{ident}/{action}')
    def plan_control(ident:str,action:str):
        if action=='today':
            with service.step_lock:return service.daily.control(ident,action)
        return service.daily.control(ident,action)

    @api.post('/accounts')
    def account(payload:CommunityAccount):return service.save_account(payload)

    @api.put('/accounts/{ident}')
    def edit_account(ident:str,payload:CommunityAccount):
        service.account(ident)
        return service.save_account(payload,ident)

    @api.delete('/accounts/{ident}')
    def delete_account(ident:str,version:int=Query(...,ge=1)):
        return service.delete_account(ident,version)

    @api.post('/accounts/{ident}/check')
    def check(ident:str):return service.check_account(ident)

    @api.post('/accounts/{ident}/native')
    def native_binding(ident:str,payload:NativeBindInput):return service.bind_native(ident,payload)

    @api.post('/accounts/{ident}/sync')
    def sync(ident:str):return service.sync_account(ident)

    @api.post('/accounts/{ident}/open')
    def open_account(ident:str):return service.open_account(ident)

    @api.post('/posts')
    def save(payload:CommunityPost):return service.save(payload)

    @api.get('/posts/{ident}/export')
    def export(ident:str,format:str=Query('md',pattern='^(md|html)$')):
        value=service.export_content(ident,format)
        return Response(value,media_type='text/html' if format=='html' else 'text/markdown',
                        headers={'Content-Disposition':f'attachment; filename="JM-content-{ident}.{format}"'})

    @api.put('/posts/{ident}')
    def edit(ident:str,payload:CommunityPost):return service.save(payload,ident)

    @api.post('/posts/{ident}/launch')
    def launch(ident:str):return service.launch(ident)

    @api.post('/posts/{ident}/{action}')
    def control(ident:str,action:str):return service.control(ident,action)

    @api.post('/jobs/{ident}/open')
    def open_job(ident:str):return service.open_job(ident)

    @api.post('/jobs/{ident}/web')
    def switch_web(ident:str):return service.switch_to_web(ident)

    @api.post('/jobs/{ident}/retry-preflight')
    def retry_preflight(ident:str):return service.retry_preflight(ident)

    @api.post('/jobs/{ident}/record')
    def record(ident:str,payload:LinkRecord):return service.record_url(ident,payload.url)

    @api.post('/jobs/{ident}/resolve')
    def resolve(ident:str,payload:ResolveRecord):return service.resolve(ident,payload.outcome,payload.note,payload.url)

    @api.post('/risk/{platform}/clear')
    def clear(platform:str,payload:ClearRecord):return service.clear_risk(platform,payload.note)

    return api
