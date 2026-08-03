"""Immutable team-space collaboration models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SharingModel(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)


class SpaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    CONTRIBUTOR = "contributor"
    VIEWER = "viewer"


class TeamSpace(SharingModel):
    tenant_id: str = Field(alias="tenantId")
    space_id: str = Field(alias="spaceId")
    name: str
    description: str = ""
    created_by: str = Field(alias="createdBy")
    created_at: datetime = Field(alias="createdAt")


class TeamSpaceMember(SharingModel):
    tenant_id: str = Field(alias="tenantId")
    space_id: str = Field(alias="spaceId")
    user_id: str = Field(alias="userId")
    role: SpaceRole
    created_at: datetime = Field(alias="createdAt")


class SharedAgentVersion(SharingModel):
    tenant_id: str = Field(alias="tenantId")
    space_id: str = Field(alias="spaceId")
    agent_owner_user_id: str = Field(alias="agentOwnerUserId")
    agent_name: str = Field(alias="agentName")
    agent_version: str = Field(alias="agentVersion")
    shared_by: str = Field(alias="sharedBy")
    runnable_by_viewer: bool = Field(default=True, alias="runnableByViewer")
    created_at: datetime = Field(alias="createdAt")


class SharedKnowledgeBase(SharingModel):
    tenant_id: str = Field(alias="tenantId")
    space_id: str = Field(alias="spaceId")
    knowledge_base_reference: str = Field(alias="knowledgeBaseReference")
    shared_by: str = Field(alias="sharedBy")
    created_at: datetime = Field(alias="createdAt")
