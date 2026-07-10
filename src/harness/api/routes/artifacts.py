"""Artifact routes are added with workspace persistence in phase-one task 12."""

from fastapi import APIRouter

router = APIRouter(prefix="/artifacts", tags=["artifacts"])
