from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from .models import PublishInput, PublishingSettings, ResolveInput


def router(publisher):
    api = APIRouter(prefix='/api/publishing')

    @api.get('/state')
    def state():
        return publisher.state()

    @api.post('/materials/upload')
    async def upload(request: Request, name: str):
        return await publisher.upload(request, name)

    @api.get('/materials/{ident}/file')
    def material_file(ident: str):
        row, path = publisher.material(ident)
        if not path.is_file():
            raise ValueError('素材原文件已被移动')
        return FileResponse(path, media_type='video/' + ('mp4' if path.suffix.lower() in ('.mp4', '.m4v') else 'webm' if path.suffix.lower()=='.webm' else 'quicktime' if path.suffix.lower()=='.mov' else 'x-matroska'))

    @api.delete('/materials/{ident}')
    def delete_material(ident: str):
        return publisher.delete_material(ident)

    @api.post('/batches')
    def save(payload: PublishInput):
        return publisher.save(payload)

    @api.put('/batches/{ident}')
    def update(ident: str, payload: PublishInput):
        return publisher.save(payload, ident)

    @api.post('/batches/{ident}/launch')
    def launch(ident: str):
        return publisher.launch(ident)

    @api.post('/batches/{ident}/{action}')
    def control(ident: str, action: str):
        return publisher.control(ident, action)

    @api.post('/jobs/{ident}/resolve')
    def resolve(ident: str, payload: ResolveInput):
        return publisher.resolve(ident, payload.outcome, payload.note)

    @api.put('/settings')
    def settings(payload: PublishingSettings):
        if publisher.store.rows("SELECT 1 FROM publish_jobs WHERE state IN ('queued','running')"):
            raise ValueError('请先暂停发布任务再修改接入设置')
        publisher.cfg.config.save(payload.model_dump())
        return {'message': '内容发布配置已保存'}

    @api.post('/service/start')
    def start():
        return publisher.bridge.start()

    return api
