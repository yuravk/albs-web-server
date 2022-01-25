import itertools

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status
from syncer import sync

from alws import database
from alws.crud import build_node, test
from alws.dependencies import get_db, JWTBearer
from alws.errors import AlreadyBuiltError
from alws.schemas import build_node_schema


router = APIRouter(
    prefix='/build_node',
    tags=['builds'],
    dependencies=[Depends(JWTBearer())]
)


def build_done_task(build_done_: build_node_schema.BuildDone,
                    db: database.Session):
    sync(build_node.build_done(db, build_done_))
    if build_done_.status == 'done':
        sync(test.create_test_tasks(db, build_done_.task_id))


@router.post('/ping')
async def ping(
            node_status: build_node_schema.Ping,
            db: database.Session = Depends(get_db)
        ):
    if not node_status.active_tasks:
        return {}
    await build_node.ping_tasks(db, node_status.active_tasks)
    return {}


@router.post('/build_done')
async def build_done(
            build_done_: build_node_schema.BuildDone,
            response: Response,
            background_tasks: BackgroundTasks,
            db: database.Session = Depends(get_db),
        ):
    task_already_finished = await build_node.check_build_task_is_finished(
        db, build_done_.task_id)
    if task_already_finished:
        response.status_code = status.HTTP_409_CONFLICT
        return {'ok': False}
    background_tasks.add(build_done_task, build_done_, db)
    return {'ok': True}


@router.get('/get_task', response_model=build_node_schema.Task)
async def get_task(
            request: build_node_schema.RequestTask,
            db: database.Session = Depends(get_db)
        ):
    task = await build_node.get_available_build_task(db, request)
    if not task:
        return
    response = {
        'id': task.id,
        'arch': task.arch,
        'ref': task.ref,
        'platform': build_node_schema.TaskPlatform.from_orm(task.platform),
        'repositories': [],
        'created_by': {
            'name': task.build.user.username,
            'email': task.build.user.email
        }
    }
    for repo in itertools.chain(task.platform.repos, task.build.repos):
        if repo.arch == task.arch and repo.type != 'build_log':
            response['repositories'].append(repo)
    for build in task.build.linked_builds:
        for repo in build.repos:
            if repo.arch == task.arch and repo.type != 'build_log':
                response['repositories'].append(repo)
    if task.build.mock_options:
        response['platform'].add_mock_options(task.build.mock_options)
    if task.mock_options:
        response['platform'].add_mock_options(task.mock_options)
    return response
