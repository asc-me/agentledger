import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Membership, Project, User
from app.schemas import MemberOut, ProjectCreate, ProjectOut, ProjectUpdate, UserOut
from app.security import authz
from app.security.deps import get_current_user
from app.services import events as events_svc

router = APIRouter(prefix="/projects", tags=["projects"])


def _unique_slug(db: Session, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "project"
    slug = base
    n = 2
    while db.get(Project, slug) is not None:
        slug = f"{base}-{n}"
        n += 1
    return slug


def _resolve_org_id(db: Session, user: User, requested: str | None) -> str | None:
    """Pick the org a new project belongs to (hosted mode only, AL-74b).

    Self-host: always None — projects have no org. Hosted: the project MUST land in an
    org the creator belongs to, otherwise the AL-74 authz gate would make it instantly
    unreachable (org_id NULL ∉ the caller's orgs) and lock the creator out. A single-org
    user needs no choice; anyone in multiple orgs must name one."""
    if not settings.hosted_mode:
        return None
    orgs = authz.org_ids_for_user(db, user.id)
    if requested is not None:
        authz.require_org_member(db, user.id, requested)  # 404 if not a member
        return requested
    if len(orgs) == 1:
        return orgs[0]
    if not orgs:
        raise HTTPException(403, "create or join an organization before creating a project")
    raise HTTPException(422, "org_id is required: you belong to more than one organization")


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    readable = set(authz.readable_project_ids(db, user.id))
    rows = db.scalars(select(Project).order_by(Project.name)).all()
    return [p for p in rows if p.id in readable]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "project name is required")
    org_id = _resolve_org_id(db, user, body.org_id)
    project = Project(
        id=_unique_slug(db, name),
        name=name,
        accent=body.accent or "#c6f24e",
        description=body.description or "",
        org_id=org_id,
    )
    db.add(project)
    db.flush()
    # The creator is the owner with full write access.
    db.add(Membership(user_id=user.id, project_id=project.id, role="owner", access="write"))
    db.commit()
    db.refresh(project)
    events_svc.record_user(db, user, action="create_project", target_type="project",
                           target_id=project.id, project_id=project.id, meta={"name": project.name})
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    authz.require_writable(db, user.id, project_id)
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    changed = body.model_dump(exclude_unset=True)
    for k, v in changed.items():
        if v is not None:
            setattr(project, k, v)
    db.commit()
    db.refresh(project)
    events_svc.record_user(db, user, action="update_project", target_type="project",
                           target_id=project_id, project_id=project_id,
                           meta={"fields": sorted(changed.keys())})
    return project


@router.get("/{project_id}/members", response_model=list[MemberOut])
def list_members(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    authz.require_readable(db, user.id, project_id)
    rows = db.scalars(select(Membership).where(Membership.project_id == project_id)).all()
    out = []
    for m in rows:
        user = db.get(User, m.user_id)
        if user is not None:
            out.append(MemberOut(user=UserOut.model_validate(user), role=m.role, access=m.access))
    return out
