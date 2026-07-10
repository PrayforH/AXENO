"""Approval routes are added with the policy engine in phase-one task 8."""

from fastapi import APIRouter

router = APIRouter(prefix="/approvals", tags=["approvals"])
