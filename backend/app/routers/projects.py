from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Membership, Project, User
from app.schemas import MemberOut, ProjectOut, ProjectUpdate, UserOut
from app.security.deps import get_current_user

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return list(db.scalars(select(Project).order_by(Project.name)).all())


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(project, k, v)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}/members", response_model=list[MemberOut])
def list_members(project_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.scalars(select(Membership).where(Membership.project_id == project_id)).all()
    out = []
    for m in rows:
        user = db.get(User, m.user_id)
        if user is not None:
            out.append(MemberOut(user=UserOut.model_validate(user), role=m.role, access=m.access))
    return out
